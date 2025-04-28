import os
import logging
import time
import sys
import importlib
from datetime import datetime, timedelta
from threading import Thread
from crontab import CronTab

# Rimuoviamo la dipendenza diretta da Flask
logger = logging.getLogger(__name__)

class JobScheduler:
    """Scheduler di job rclone basato su espressioni crontab"""
    
    def __init__(self, rclone_handler, log_dir, app=None):
        """Initializza lo scheduler
        
        Args:
            rclone_handler: Handler per le operazioni rclone
            log_dir: Directory dove sono archiviati i log
            app: Flask application instance
        """
        self.rclone_handler = rclone_handler
        self.log_dir = log_dir
        self.app = app
        self.running = False
        self.thread = None
        # Dizionario per tracciare i job saltati e quando ricontrollarli
        self.skipped_jobs = {}
        # Dizionario per tracciare i job attualmente in corso di avvio
        # Evita il doppio avvio dello stesso job
        self.launching_jobs = {}
    
    def start(self):
        """Avvia lo scheduler in un thread separato"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        self.running = True
        self.thread = Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Job scheduler started")
    
    def stop(self):
        """Ferma lo scheduler"""
        if not self.running:
            logger.warning("Scheduler is not running")
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Job scheduler stopped")
    
    def _run_scheduler(self):
        """Loop principale dello scheduler"""
        last_full_check = datetime.now()  # Ultima volta che abbiamo controllato tutti i job
        last_log_time = last_full_check   # Ultima volta che abbiamo registrato il log di debug
        last_stale_check = last_full_check  # Ultima volta che abbiamo controllato i job stale
        
        while self.running:
            try:
                current_time = datetime.now()
                
                # Evita di registrare troppi log di debug, solo una volta ogni 5 minuti
                if (current_time - last_log_time).total_seconds() > 300:
                    logger.debug(f"Scheduler loop tick at {current_time}")
                    last_log_time = current_time
                
                # Aggiungiamo debug esplicito per verificare se lo scheduler sta controllando i job
                logger.info(f"[DEBUG] Scheduler verifica jobs at {current_time}")
                
                try:
                    # Importiamo direttamente il modulo app
                    from app import app, db
                    from models import ScheduledJob, SyncJobHistory
                    
                    # Eseguiamo il codice all'interno di un contesto dell'applicazione
                    with app.app_context():
                        # Dobbiamo usare is_(None) invece di == None per SQLAlchemy
                        jobs_to_check = ScheduledJob.query.filter(
                            ScheduledJob.enabled == True,
                            (ScheduledJob.next_run <= current_time) | (ScheduledJob.next_run.is_(None))
                        ).all()
                        
                        # Log debug per ogni iterazione, anche se non ci sono job
                        if jobs_to_check:
                            logger.info(f"[DEBUG] Trovati {len(jobs_to_check)} jobs da verificare")
                        else:
                            logger.info(f"[DEBUG] Nessun job da verificare in questa iterazione")
                        
                        # Controllo job stale ogni 15 minuti
                        stale_check_interval = 15 * 60  # 15 minuti in secondi
                        if (current_time - last_stale_check).total_seconds() > stale_check_interval:
                            logger.info(f"Esecuzione controllo job stale (ogni {stale_check_interval/60} minuti)")
                            try:
                                # Importa la funzione per la pulizia dei job stale
                                from app import force_cleanup_jobs
                                # Esegui pulizia solo sui job stale (con timeout di 3 ore)
                                force_cleanup_jobs(only_stale_jobs=True, inactive_hours=3)
                                last_stale_check = current_time
                                logger.info("Controllo job stale completato")
                            except Exception as e:
                                logger.error(f"Errore durante il controllo dei job stale: {str(e)}")
                        
                        # Controllo completo ogni 5 minuti per assicurarci di non perdere alcun job
                        # Questo è un meccanismo di sicurezza in caso di problemi con i timestamp next_run
                        full_check = (current_time - last_full_check).total_seconds() > 300
                        if full_check:
                            all_jobs = ScheduledJob.query.filter_by(enabled=True).all()
                            logger.debug(f"Performing full check of {len(all_jobs)} scheduled jobs at {current_time}")
                            
                            # Verifica se ci sono job con next_run nullo o problematici
                            jobs_without_next_run = [j for j in all_jobs if j.next_run is None]
                            if jobs_without_next_run:
                                logger.info(f"Found {len(jobs_without_next_run)} jobs without next_run time")
                                for job in jobs_without_next_run:
                                    job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                                    logger.info(f"Updated missing next_run for job {job.id} ({job.name}) to {job.next_run}")
                                db.session.commit()
                            
                            # I job da controllare sono tutti quelli con next_run <= now
                            jobs_to_check = [j for j in all_jobs if j.next_run and j.next_run <= current_time]
                            last_full_check = current_time
                        
                        # Log con il numero di job da verificare, se ci sono
                        if jobs_to_check:
                            logger.debug(f"Checking {len(jobs_to_check)} scheduled jobs that are due at {current_time}")
                        
                        # Processa i job da eseguire
                        for job in jobs_to_check:
                            job_id = job.id
                            job_key = f"{job_id}_{job.source.strip()}_{job.target.strip()}"
                            
                            # Se abbiamo già saltato questo job e non è ancora il momento di controllarlo di nuovo, salta
                            if job_key in self.skipped_jobs:
                                next_check_time = self.skipped_jobs[job_key]
                                if current_time < next_check_time:
                                    # Non logghiamo per evitare spam di log
                                    continue
                                else:
                                    # È tempo di controllare di nuovo questo job, rimuovilo dalla lista degli skipped
                                    del self.skipped_jobs[job_key]
                            
                            # Non controlliamo qui job.next_run <= current_time perché l'abbiamo già filtrato nella query
                            logger.info(f"Scheduled job {job_id} ({job.name}) is due for execution")
                            
                            # Puliamo eventuali spazi extra nei percorsi
                            source = job.source.strip()
                            target = job.target.strip()
                            
                            # Ottiene il timestamp originale next_run per il log dettagliato
                            original_next_run = job.next_run
                            
                            # Verifica se c'è già un job in esecuzione con gli stessi source/target
                            if self._check_if_running(source, target):
                                logger.warning(f"Skipping job {job_id}: source/target already has a running job")
                                
                                # Controlla quanto tempo è passato dall'orario di esecuzione originale
                                time_since_scheduled = (current_time - original_next_run).total_seconds() if original_next_run else 0
                                
                                # Se sono passate più di 12 ore dall'orario originale di esecuzione,
                                # forziamo la ricalendarizzazione anche se il job è ancora in esecuzione
                                # Questo evita blocchi permanenti di job che restano in esecuzione troppo a lungo
                                if time_since_scheduled > 43200:  # 12 ore in secondi
                                    logger.warning(f"Job {job_id} è rimasto bloccato per più di 12 ore. Forzatura ricalendarizzazione.")
                                    
                                # Calcola il prossimo orario di esecuzione ma non eseguire ora
                                # Partendo dall'orario corrente, NON dall'orario originale, per evitare blocchi
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                                
                                # Aggiungi alla lista dei job saltati per evitare di verificarlo ad ogni ciclo
                                self.skipped_jobs[job_key] = job.next_run
                                
                                # Ora troviamo la history entry esistente per questo job 
                                # e aggiorniamo il last_run per mostrare il tempo di avvio reale
                                try:
                                    # Cerca nella history i job running per questo source/target
                                    running_jobs = SyncJobHistory.query.filter_by(
                                        source=source,
                                        target=target,
                                        status="running"
                                    ).order_by(SyncJobHistory.start_time.desc()).all()
                                    
                                    # Se ne troviamo, usiamo il primo (più recente) per aggiornare last_run
                                    if running_jobs:
                                        # Usa lo stesso start time del job attualmente in esecuzione
                                        job.last_run = running_jobs[0].start_time
                                        logger.info(f"Job {job_id}: last_run aggiornato a {job.last_run} (dal job attivo)")
                                except Exception as e:
                                    logger.warning(f"Impossibile aggiornare last_run per job {job_id}: {str(e)}")
                                
                                # Registra dettagli sul job saltato e sul prossimo tentativo
                                logger.info(f"Job {job_id} skipped. Was due at {original_next_run}, next attempt at {job.next_run}")
                                db.session.commit()
                                continue
                            
                            # Verifica se il job è già in fase di avvio
                            if job_key in self.launching_jobs:
                                launch_time = self.launching_jobs[job_key]
                                # Se è in fase di avvio da meno di 2 minuti, saltiamo
                                if (current_time - launch_time).total_seconds() < 120:
                                    logger.warning(f"Job {job_id} ({job.name}) è già in fase di avvio (avviato {launch_time})")
                                    continue
                                else:
                                    # Rimuoviamo dalla lista dei job in avvio se è passato troppo tempo
                                    logger.warning(f"Job {job_id} ({job.name}) era in fase di avvio da troppo tempo, rimuovo il blocco")
                                    del self.launching_jobs[job_key]
                                
                            # Crea un file di lock preventivo per questo job pianificato
                            scheduled_lock_file = f"{self.log_dir}/scheduled_job_{job_id}.lock"
                            
                            # Verifica se esiste già un lock file per questo job pianificato 
                            if os.path.exists(scheduled_lock_file):
                                # Controlla l'età del file di lock
                                try:
                                    lock_file_time = datetime.fromtimestamp(os.path.getmtime(scheduled_lock_file))
                                    lock_age = (current_time - lock_file_time).total_seconds()
                                    
                                    # Se il file di lock è vecchio (più di 10 minuti), lo rimuoviamo
                                    if lock_age > 600:
                                        logger.warning(f"Lock file per job pianificato {job_id} è vecchio ({lock_age}s), lo rimuovo")
                                        try:
                                            os.remove(scheduled_lock_file)
                                        except Exception as e:
                                            logger.error(f"Errore rimuovendo vecchio lock file: {str(e)}")
                                    else:
                                        # Il lock file è recente, saltiamo questo job
                                        logger.warning(f"Lock file per job pianificato {job_id} esiste già (età: {lock_age}s), salto")
                                        continue
                                except Exception as e:
                                    logger.error(f"Errore controllando età del lock file: {str(e)}")
                            
                            # Registra che stiamo avviando questo job
                            self.launching_jobs[job_key] = current_time
                            
                            try:
                                # Crea il file di lock preventivo
                                try:
                                    with open(scheduled_lock_file, 'w') as f:
                                        f.write(f"{current_time.isoformat()}\n{job.name}\n{source}\n{target}")
                                    logger.info(f"Created preventive lock file: {scheduled_lock_file}")
                                except Exception as e:
                                    logger.error(f"Error creating preventive lock file: {str(e)}")
                                
                                logger.info(f"Executing scheduled job {job.id} ({job.name}): {source} → {target}")
                                
                                # Esegui il job - questo aggiunge anche il job al dizionario active_jobs dell'handler
                                job_info = self.rclone_handler.run_custom_job(source, target, dry_run=False)
                                
                                # Aggiorna il timestamp dell'ultimo avvio
                                job.last_run = current_time
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                                
                                # Crea entry nella history (usando i valori ripuliti)
                                history = SyncJobHistory(
                                    source=source,  # Usa i valori ripuliti
                                    target=target,  # Usa i valori ripuliti
                                    status="running",
                                    dry_run=False,
                                    start_time=current_time,
                                    log_file=job_info.get("log_file")
                                )
                                db.session.add(history)
                                
                                # Registra i dettagli per il debug
                                logger.info(f"Scheduled job {job.id} started successfully:")
                                logger.info(f"  - Lock file: {job_info.get('lock_file')}")
                                logger.info(f"  - Log file: {job_info.get('log_file')}")
                                logger.info(f"  - Process PID: {job_info.get('process').pid}")
                                logger.info(f"  - Next run scheduled at: {job.next_run}")
                                
                                # Rimuoviamo il lock file preventivo dopo aver avviato con successo il job
                                try:
                                    if os.path.exists(scheduled_lock_file):
                                        os.remove(scheduled_lock_file)
                                        logger.info(f"Removed preventive lock file after successful job start: {scheduled_lock_file}")
                                except Exception as e:
                                    logger.error(f"Error removing preventive lock file: {str(e)}")
                                
                                # Rimuoviamo il job dalla lista dei job in avvio
                                if job_key in self.launching_jobs:
                                    del self.launching_jobs[job_key]
                                
                                # Notifica l'avvio del job
                                try:
                                    from utils.notification_manager import notify_job_started
                                    notify_job_started(history.id, source, target, is_scheduled=True, dry_run=False)
                                except Exception as e:
                                    logger.error(f"Failed to send notification for job start: {str(e)}")
                            except Exception as e:
                                logger.error(f"Error executing scheduled job {job.id}: {str(e)}")
                                # Aggiorna comunque i timestamp per ritentare alla prossima esecuzione
                                job.last_run = current_time
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                            
                            db.session.commit()
                except Exception as e:
                    # Registriamo errori di importazione o errori durante l'accesso al database
                    logger.error(f"Error accessing database or importing modules: {str(e)}")
                    # Attendi un po' di tempo prima di riprovare
                    time.sleep(60)
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
            
            # Dormi per un intervallo di 60 secondi (1 minuto) 
            # Riduce il carico di CPU e le possibilità di avvii duplicati
            time.sleep(60)
    
    def _check_if_running(self, source, target):
        """Verifica se un job con lo stesso source e target è in esecuzione"""
        # Controlla tramite l'handler rclone
        job_running = self.rclone_handler.is_job_running(source, target)
        
        # Controlla anche il file di lock con il nuovo formato di tag
        # Prova prima il nuovo formato
        tag = self.rclone_handler._generate_tag(source, target)
        lock_file = f"{self.log_dir}/sync_{tag}.lock"
        lock_exists = os.path.exists(lock_file)
        
        # Se non esiste, prova con il vecchio formato di tag
        if not lock_exists:
            tag_old = f"{source.replace(':', '_').replace('/', '_')}__TO__{target.replace(':', '_').replace('/', '_')}"
            lock_file_old = f"{self.log_dir}/sync_{tag_old}.lock"
            lock_exists = os.path.exists(lock_file_old)
            if lock_exists:
                lock_file = lock_file_old
                
        # Controlla anche i file di lock preventivi per job pianificati
        preventive_lock_exists = False
        preventive_lock_file = None
        
        # Cerca tutti i file di lock preventivi
        if not lock_exists and not job_running:
            try:
                # Verifica se ci sono file di lock preventivi attivi per qualsiasi job schedulato
                import glob
                preventive_lock_pattern = f"{self.log_dir}/scheduled_job_*.lock"
                preventive_lock_files = glob.glob(preventive_lock_pattern)
                
                # Verifica ogni file di lock preventivo per vedere se contiene questo source/target
                for prev_lock_file in preventive_lock_files:
                    try:
                        with open(prev_lock_file, 'r') as f:
                            lines = f.readlines()
                            # Il formato del file di lock preventivo è:
                            # linea 1: timestamp ISO
                            # linea 2: nome job
                            # linea 3: source
                            # linea 4: target
                            if len(lines) >= 4:
                                prev_source = lines[2].strip()
                                prev_target = lines[3].strip()
                                
                                # Se source e target corrispondono, consideriamo il job in esecuzione
                                if prev_source == source and prev_target == target:
                                    preventive_lock_exists = True
                                    preventive_lock_file = prev_lock_file
                                    logger.info(f"Preventive lock file found for job {source} → {target}: {prev_lock_file}")
                                    break
                    except Exception as e:
                        logger.error(f"Error reading preventive lock file {prev_lock_file}: {str(e)}")
            except Exception as e:
                logger.error(f"Error checking preventive lock files: {str(e)}")
        
        # Log dettagliato per diagnosi
        if job_running or lock_exists or preventive_lock_exists:
            logger.info(f"Job already running check for {source} → {target}: " +
                      f"rclone_handler.is_job_running={job_running}, " +
                      f"lock_file_exists={lock_exists}, lock_path={lock_file}, " +
                      f"preventive_lock_exists={preventive_lock_exists}" +
                      (f", preventive_lock_file={preventive_lock_file}" if preventive_lock_exists else ""))
            
            # Se il metodo is_job_running dice che il job è in esecuzione ma non ci sono file di lock,
            # potrebbe esserci un problema di sincronizzazione tra i record del database
            if job_running and not lock_exists and not preventive_lock_exists:
                logger.warning(f"Lock file not found but is_job_running=True for {source} → {target}. " +
                             f"Possible database status inconsistency.")
                
                # Forza un nuovo controllo immediato per essere sicuri che is_job_running restituisca il valore corretto
                # Questo dovrebbe risolvere i falsi positivi di job in esecuzione che non lo sono realmente
                time.sleep(2)  # Breve pausa per consentire eventuali operazioni concorrenti di completarsi
                job_running = self.rclone_handler.is_job_running(source, target)
        
        # Se uno qualsiasi dei controlli è positivo, consideriamo il job in esecuzione
        return job_running or lock_exists or preventive_lock_exists
    
    @staticmethod
    def calculate_next_run_static(cron_expression, from_time=None):
        """Calcola il prossimo orario di esecuzione da un'espressione cron (metodo statico)
        
        Args:
            cron_expression: Espressione cron (es. "0 3 * * *" per ogni giorno alle 3:00)
            from_time: Data/ora da cui calcolare il prossimo avvio (default: now)
        
        Returns:
            datetime: Data e ora del prossimo avvio
        """
        if from_time is None:
            from_time = datetime.now()
        
        try:
            # Parse dell'espressione cron
            cron = CronTab(cron_expression)
            
            # Calcola i secondi fino alla prossima esecuzione
            # Nota: il metodo 'next' è fornito dalla libreria python-crontab
            delay = cron.next(default_utc=False)
            
            # Converte in datetime
            next_run = from_time + timedelta(seconds=delay)
            return next_run
        except Exception as e:
            logger.error(f"Error calculating next run time from '{cron_expression}': {str(e)}")
            # Se c'è un errore, ritorna 1 ora nel futuro come fallback
            return from_time + timedelta(hours=1)
            
    def _calculate_next_run(self, cron_expression, from_time=None):
        """Calcola il prossimo orario di esecuzione da un'espressione cron"""
        return self.calculate_next_run_static(cron_expression, from_time)
    
    def get_schedule_summary(self):
        """Get summary of all scheduled jobs with next run times"""
        try:
            # Importiamo app per avere accesso al contesto
            from app import app, db
            from models import ScheduledJob
            
            # Eseguiamo il codice all'interno di un contesto dell'applicazione
            with app.app_context():
                summary = []
                now = datetime.now()
                
                jobs = ScheduledJob.query.all()
                for job in jobs:
                    # Se next_run è None, calcolalo
                    next_run = job.next_run
                    if next_run is None and job.enabled:
                        next_run = self._calculate_next_run(job.cron_expression, now)
                    
                    # Calcola quanto manca all'esecuzione
                    time_left = None
                    if next_run and job.enabled:
                        diff = (next_run - now).total_seconds()
                        if diff < 60:
                            time_left = f"{int(diff)}s"
                        elif diff < 3600:
                            time_left = f"{int(diff/60)}m"
                        else:
                            time_left = f"{diff/3600:.1f}h"
                    
                    summary.append({
                        'id': job.id,
                        'name': job.name,
                        'source': job.source,
                        'target': job.target,
                        'cron': job.cron_expression,
                        'enabled': job.enabled,
                        'last_run': job.last_run,
                        'next_run': next_run,
                        'time_left': time_left
                    })
                
                return summary
        except Exception as e:
            logger.error(f"Error getting schedule summary: {str(e)}")
            return []