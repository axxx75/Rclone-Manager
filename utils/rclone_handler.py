import os
import re
import json
import time
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from threading import Thread

logger = logging.getLogger(__name__)


class RCloneHandler:
    """Handler for interacting with rclone and the bash script"""

    def __init__(self, config_path, log_dir):
        """Initialize the RClone handler
        
        Args:
            config_path: Path to the rclone configuration file with scheduled jobs
            log_dir: Directory where logs are stored
        """
        self.config_path = config_path
        self.log_dir = log_dir
        self.active_jobs = {}
        self.main_config_path = "/root/.config/rclone/rclone.conf"

        # Create log directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)

    def _generate_tag(self, source, target):
        """Generate a consistent tag for source and target paths
        
        Replaces special characters that could cause issues in filenames.
        Preserves important remote and path information for better recognition.
        """

        # Funzione per sanitizzare i percorsi preservando le informazioni essenziali
        def sanitize_path(path):
            # Conserva la struttura remoto:percorso se presente
            if ':' in path:
                parts = path.split(':', 1)
                remote = parts[0]  # La parte del remoto
                path_part = parts[1]  # La parte del percorso

                # Rimuovi i prefissi comuni come '/', '//', 'http://', etc.
                path_part = path_part.lstrip('/')
                if path_part.startswith('http'):
                    path_part = path_part.replace('http://',
                                                  '').replace('https://', '')

                # Sostituisci i caratteri problematici nel percorso
                replacements = {
                    '/': '-',
                    ' ': '_',
                    '\\': '-',
                    '?': '_',
                    '*': '_',
                    '|': '_',
                    '<': '_',
                    '>': '_',
                    '"': '',
                    '\'': '',
                    '`': '',
                    '&': '_',
                    ';': '_'
                }

                # Applica le sostituzioni solo alla parte del percorso
                for char, replacement in replacements.items():
                    path_part = path_part.replace(char, replacement)

                # Rimuovi underscore e trattini multipli consecutivi
                while '__' in path_part:
                    path_part = path_part.replace('__', '_')
                while '--' in path_part:
                    path_part = path_part.replace('--', '-')

                # Ricostruisci il path con il formato originale
                result = f"{remote}:{path_part}"
            else:
                # Se non c'è un remoto, sanitizza tutto il percorso
                replacements = {
                    ':': '-',
                    '/': '-',
                    ' ': '_',
                    '\\': '-',
                    '?': '_',
                    '*': '_',
                    '|': '_',
                    '<': '_',
                    '>': '_',
                    '"': '',
                    '\'': '',
                    '`': '',
                    '&': '_',
                    ';': '_'
                }

                result = path
                for char, replacement in replacements.items():
                    result = result.replace(char, replacement)

            # Rimuovi eventuali caratteri di controllo o non stampabili
            import re
            result = re.sub(r'[\x00-\x1F\x7F]', '', result)

            return result

        # Sanitizza source e target
        source_tag = sanitize_path(source)
        target_tag = sanitize_path(target)

        # Crea il tag finale per il nome del file
        return f"{source_tag}_TO_{target_tag}"

    def get_configured_jobs(self):
        """Get list of jobs from configuration file"""
        jobs = []

        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path}")
            return jobs

        try:
            with open(self.config_path, 'r') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        source, target = parts
                        jobs.append({
                            'id': i,
                            'source': source,
                            'target': target
                        })
        except Exception as e:
            logger.error(f"Error reading config file: {str(e)}")

        return jobs

    def read_config_file(self):
        """Read the current configuration file content"""
        if not os.path.exists(self.config_path):
            return ""

        try:
            with open(self.config_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading config file: {str(e)}")
            return f"# Error reading file: {str(e)}"

    def save_config_file(self, content):
        """Save changes to the configuration file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            with open(self.config_path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Error saving config file: {str(e)}")
            raise

    def run_custom_job(self, source, target, dry_run=False):
        """Run a custom job with source and target"""
        # Puliamo eventuali spazi extra nelle sorgenti/destinazioni
        source = source.strip()
        target = target.strip()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        tag = self._generate_tag(source, target)
        log_file = f"{self.log_dir}/sync_{timestamp}_{tag}.log"

        # Check if a job with the same source and target is already running
        lock_file = f"{self.log_dir}/sync_{tag}.lock"

        # Se esiste un lock file, verifichiamo quanto è vecchio
        # e rimuoviamolo se è più vecchio di 1 ora (possibile lock file orfano)
        if os.path.exists(lock_file):
            # Verifica l'età del file
            file_age = time.time() - os.path.getmtime(lock_file)

            # Se il file è più vecchio di 1 ora (3600 secondi), potrebbe essere orfano
            if file_age > 3600:
                try:
                    os.remove(lock_file)
                    logger.info(
                        f"Rimosso lock file stale: {lock_file} (età: {file_age:.1f}s)"
                    )
                except Exception as e:
                    logger.error(
                        f"Errore durante la rimozione del lock file stale: {str(e)}"
                    )
            else:
                # Il file esiste ed è recente, segnaliamo che il job è già in esecuzione
                raise Exception(
                    f"A job with the same source and target is already running: {source} → {target}"
                )

        # Prepare command
        cmd = [
            "/bin/bash", "-c",
            f"rclone sync '{source}' '{target}' --progress --stats=15s"
        ]

        # Add dry-run flag if needed
        if dry_run:
            cmd[-1] += " --dry-run"

        # Add other common options
        cmd[-1] += " --log-level INFO"
        cmd[-1] += f" --log-file '{log_file}'"
        cmd[-1] += " --no-check-certificate"
        
        # Aggiungi parametri di timeout per migliorare la resilienza
        cmd[-1] += " --timeout 30m"        # Timeout per operazioni singole (30 minuti)
        cmd[-1] += " --contimeout 2m"      # Timeout per connessione iniziale (2 minuti)
        cmd[-1] += " --low-level-retries 10" # Aumenta i tentativi per errori di basso livello
        cmd[-1] += " --retries 3"          # Numero di tentativi per fallimenti
        cmd[-1] += " --retries-sleep 10s"  # Attendi 10 secondi tra i tentativi

        # Add checksum or size-only based on source/target
        src_remote = source.split(':', 1)[0] if ':' in source else ""
        tgt_remote = target.split(':', 1)[0] if ':' in target else ""

        if src_remote and tgt_remote:
            # Determine if we can use checksums
            src_hashes_cmd = f"rclone backend features {src_remote}: --json --no-check-certificate"
            tgt_hashes_cmd = f"rclone backend features {tgt_remote}: --json --no-check-certificate"

            # Log the hash capability check commands
            logger.info(f"Checking source hash capabilities: {src_hashes_cmd}")
            logger.info(f"Checking target hash capabilities: {tgt_hashes_cmd}")

            try:
                # Crea un ambiente senza variabili proxy
                my_env = os.environ.copy()
                for proxy_var in [
                        'http_proxy', 'https_proxy', 'HTTP_PROXY',
                        'HTTPS_PROXY'
                ]:
                    if proxy_var in my_env:
                        del my_env[proxy_var]
                        logger.info(
                            f"Unset proxy variable for hash check: {proxy_var}"
                        )

                # Utilizzare Popen invece di run per maggiore compatibilità con versioni Python più vecchie
                src_process = subprocess.Popen(src_hashes_cmd,
                                               shell=True,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               universal_newlines=True,
                                               env=my_env)
                src_stdout, src_stderr = src_process.communicate()
                src_result_text = src_stdout
                src_returncode = src_process.returncode

                tgt_process = subprocess.Popen(tgt_hashes_cmd,
                                               shell=True,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               universal_newlines=True,
                                               env=my_env)
                tgt_stdout, tgt_stderr = tgt_process.communicate()
                tgt_result_text = tgt_stdout
                tgt_returncode = tgt_process.returncode

                src_hashes = []
                tgt_hashes = []

                if src_returncode == 0:
                    src_json = json.loads(src_result_text)
                    src_hashes = src_json.get('Hashes', [])

                if tgt_returncode == 0:
                    tgt_json = json.loads(tgt_result_text)
                    tgt_hashes = tgt_json.get('Hashes', [])

                common_hashes = set(src_hashes) & set(tgt_hashes)

                if common_hashes:
                    cmd[-1] += " --checksum"
                else:
                    cmd[-1] += " --size-only"
            except Exception as e:
                logger.warning(
                    f"Error determining hash capability: {str(e)}. Using --size-only"
                )
                cmd[-1] += " --size-only"
        else:
            # Default to size-only if we can't determine
            cmd[-1] += " --size-only"

        # Add other common options
        # Non sovrascriviamo i parametri già impostati sopra
        cmd[-1] += " --transfers=4 --checkers=8"

        # Add user-requested default flags
        cmd[-1] += " --metadata --use-server-modtime --gcs-bucket-policy-only"

        # Prepara il comando esatto con tutti gli argomenti
        full_command = cmd[-1]

        # Log the complete command being executed
        logger.info(f"Executing command: {full_command}")

        # Scrivi il comando completo direttamente nel file di log
        try:
            with open(log_file, 'w') as f:
                f.write(
                    f"=============== COMANDO RCLONE ESEGUITO ===============\n"
                )
                f.write(f"{full_command}\n")
                f.write(
                    f"======================================================\n\n"
                )

            # Verifica che il contenuto sia stato effettivamente scritto
            with open(log_file, 'r') as f:
                file_content = f.read(100)  # Leggi i primi 100 caratteri
                if "COMANDO RCLONE ESEGUITO" not in file_content:
                    logger.error(
                        f"Il comando non è stato scritto nel file di log correttamente: {log_file}"
                    )
        except Exception as e:
            logger.error(
                f"Errore durante la scrittura del comando nel file di log: {str(e)}"
            )

        # Crea un ambiente senza variabili proxy
        my_env = os.environ.copy()
        for proxy_var in [
                'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'
        ]:
            if proxy_var in my_env:
                del my_env[proxy_var]
                logger.info(f"Unset proxy variable: {proxy_var}")

        # Modifica: utilizza il parametro shell=True per assicurarci di ottenere l'exit code corretto
        # quando rclone incontra errori (come directory non trovate)
        process = subprocess.Popen(
            full_command,  # Passiamo il comando completo come stringa 
            shell=
            True,  # Eseguiamo tramite shell per una gestione migliore degli errori
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=
            True,  # Equivalente a text=True nelle versioni più recenti
            env=my_env)

        logger.info(f"Started rclone process with PID {process.pid}")

        # Create lock file
        with open(lock_file, 'w') as f:
            f.write(str(process.pid))

        # Crea anche una copia di backup del file di lock
        # Questo ci permetterà di recuperare il PID anche dopo che il file di lock viene rimosso
        try:
            with open(f"{lock_file}.bak", 'w') as f:
                f.write(str(process.pid))
        except Exception as e:
            logger.warning(f"Could not create backup lock file: {str(e)}")

        logger.info(f"Created lock file: {lock_file} for PID {process.pid}")

        # Nota: il comando è già stato salvato all'inizio del file di log
        # Non è necessario ripeterlo qui

        # Store job info
        job_info = {
            'source': source,
            'target': target,
            'dry_run': dry_run,
            'process': process,
            'log_file': log_file,
            'lock_file': lock_file,
            'start_time': datetime.now()
        }

        job_key = f"{source}|{target}"
        self.active_jobs[job_key] = job_info
        logger.info(f"Added job to active_jobs dictionary: {job_key}")

        # Start a thread to monitor the job
        Thread(target=self._monitor_job, args=(job_key, ), daemon=True).start()

        return job_info

    def run_configured_job(self, job_id, dry_run=False):
        """Run a configured job from the config file"""
        jobs = self.get_configured_jobs()
        job_id = int(job_id)

        if job_id < 0 or job_id >= len(jobs):
            raise Exception(f"Invalid job ID: {job_id}")

        job = jobs[job_id]
        return self.run_custom_job(job['source'], job['target'], dry_run)

    def _monitor_job(self, job_key):
        """Monitor a running job and clean up when done"""
        import os  # Importiamo os esplicitamente all'interno della funzione
        import sys
        import time

        # Verifica iniziale se il job è ancora attivo
        if job_key not in self.active_jobs:
            logger.warning(f"Job {job_key} not found in active_jobs, cannot monitor")
            return

        # Copia locale del job per evitare problemi se viene rimosso mentre è in esecuzione
        job_copy = self.active_jobs[job_key].copy()
        process = job_copy['process']
        
        # Crea anche un riferimento al job originale ma lo aggiorna ad ogni utilizzo
        # per evitare race condition se il job viene rimosso
        
        try:
            # Wait for process to finish
            logger.info(f"Monitoring job {job_key} with PID {process.pid}")
            process.wait()
            logger.info(
                f"Job {job_key} with PID {process.pid} has completed with exit code {process.returncode}"
            )
        except Exception as e:
            logger.error(f"Error while waiting for process to complete: {str(e)}")
            
        # Aggiorna il riferimento al job originale
        job = self.active_jobs.get(job_key)
        if not job:
            logger.warning(f"Job {job_key} was removed while monitoring, using local copy")
            job = job_copy

        # Verifica se il processo è stato terminato da un segnale esterno (come SIGTERM)
        if process.returncode < 0:
            logger.warning(
                f"Job {job_key} was terminated by signal {-process.returncode}"
            )

        # Check if this was a scheduled job and if it was terminated prematurely
        # This could help us identify if a new scheduled instance tried to start while this was running
        terminated_prematurely = False
        try:
            import signal
            # Check if the process was terminated by a signal
            if process.returncode < 0:
                signal_num = -process.returncode
                signal_name = next(
                    (name for name, val in vars(signal).items()
                     if name.startswith('SIG') and not name.startswith('SIG_')
                     and val == signal_num), f"Signal {signal_num}")
                logger.warning(
                    f"Job {job_key} terminated by signal {signal_name}")
                terminated_prematurely = True
        except Exception as e:
            logger.error(f"Error checking process termination cause: {str(e)}")

        # Update job info with end time and status
        job['end_time'] = datetime.now()
        job['exit_code'] = process.returncode
        job['terminated_prematurely'] = terminated_prematurely

        # Remove lock file
        if os.path.exists(job['lock_file']):
            try:
                os.remove(job['lock_file'])
                logger.info(f"Removed lock file: {job['lock_file']}")
            except Exception as e:
                logger.error(
                    f"Failed to remove lock file {job['lock_file']}: {str(e)}")
        else:
            logger.warning(
                f"Lock file {job['lock_file']} already removed - job may have been restarted by scheduler"
            )

        # Rimuovi anche l'eventuale file di backup (.bak)
        try:
            backup_lock_file = f"{job['lock_file']}.bak"
            if os.path.exists(backup_lock_file):
                os.remove(backup_lock_file)
                logger.debug(f"Removed backup lock file: {backup_lock_file}")
        except Exception as e:
            logger.debug(f"Error removing backup lock file: {str(e)}")

        # Verifica se il job ha prodotto errori nei log
        success = process.returncode == 0
        if success and job.get('log_file') and os.path.exists(
                job.get('log_file')):
            try:
                with open(job.get('log_file'), 'r') as f:
                    log_content = f.read()
                    # Controlla se ci sono indicazioni di errore nei log, anche se l'exit code è 0
                    # Rclone a volte termina con successo anche se ci sono stati errori
                    # Verifichiamo il contenuto escludendo le righe di INFO
                    if ((" ERROR " in log_content.upper()
                         or " ERROR:" in log_content.upper())
                            or (" FATAL " in log_content.upper()
                                or " FATAL:" in log_content.upper())
                            or "NOTICE: Failed" in log_content or
                        ("Errors:" in log_content and "0)" not in
                         log_content.split("Errors:")[1].split("\n")[0])):
                        # Manteniamo il job come successo se il messaggio di errore è solo informativo
                        # o se il job ha riguardato 0 file (nothing to transfer)
                        if "There was nothing to transfer" in log_content:
                            # Non consideriamo un errore il caso "nothing to transfer"
                            logger.info(
                                f"Job reported 'nothing to transfer' - keeping as success"
                            )
                        else:
                            success = False
                            logger.warning(
                                f"Job exit code was 0 but errors found in log, marking as failed"
                            )
            except Exception as e:
                logger.error(
                    f"Error reading log file for job completion: {str(e)}")

        status = "completed successfully" if success else f"failed with exit code {process.returncode}"
        logger.info(f"Job {job['source']} → {job['target']} {status}")

        # Registra anche l'exit code nel file di log per riferimento futuro
        log_file = job.get('log_file')
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, 'a') as f:
                    f.write(
                        f"\n\n=============== RISULTATO DEL JOB ===============\n"
                    )
                    f.write(f"Exit code: {process.returncode}\n")
                    if success:
                        f.write(f"Status: Completato con successo\n")
                    else:
                        f.write(f"Status: Completato con errori\n")
                    f.write(
                        f"Data/ora fine: {job['end_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write(
                        f"======================================================\n"
                    )
                logger.info(f"Updated log file with job result information")
            except Exception as e:
                logger.error(
                    f"Error updating log file with job result: {str(e)}")

        # Aggiorna il database e invia notifica di completamento
        try:
            # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
            # Eseguiamo una chiamata diretta al modulo models importandolo nel contesto attuale
            import sys
            import os

            # Aggiungiamo la directory principale al path per l'import
            app_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..'))
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)

            # Importiamo i moduli necessari
            from models import SyncJobHistory, db
            from app import app  # Import diretto dell'app Flask
            from utils.notification_manager import notify_job_completed

            # Utilizziamo il contesto dell'app esplicitamente
            with app.app_context():
                # Trova il job nel database
                history_job = SyncJobHistory.query.filter_by(
                    source=job['source'],
                    target=job['target'],
                    status="running",
                    log_file=job['log_file']).first()

                if history_job:
                    # Aggiorna lo stato
                    history_job.status = "completed" if success else "error"
                    history_job.end_time = job['end_time']
                    history_job.exit_code = job['exit_code']
                    db.session.commit()

                    # Invia notifica di completamento
                    duration = (job['end_time'] -
                                job['start_time']).total_seconds()
                    notify_job_completed(history_job.id,
                                         job['source'],
                                         job['target'],
                                         success=success,
                                         duration=duration)

                    logger.info(
                        f"Successfully updated job status in database to {'completed' if success else 'error'}"
                    )
                else:
                    logger.warning(
                        f"No database entry found for job {job_key}")
        except Exception as e:
            logger.error(f"Error updating job status in database: {str(e)}")

        # Remove from active jobs after a delay
        time.sleep(
            60)  # Keep in active jobs list for 1 minute after completion
        if job_key in self.active_jobs:
            logger.info(f"Removing job from active_jobs: {job_key}")
            del self.active_jobs[job_key]

    def get_active_jobs(self, include_db_jobs=True):
        """Get list of currently active jobs
        
        Args:
            include_db_jobs: Se True, include anche i job segnati come running nel database
        """
        # Import necessari per il contesto esterno alla funzione
        import os
        import sys

        # Clean up any dead jobs
        job_keys = list(self.active_jobs.keys())
        for job_key in job_keys:
            job = self.active_jobs[job_key]
            if job['process'].poll() is not None:
                # Process has finished
                if not os.path.exists(job['lock_file']):
                    logger.info(f"Removing finished job from active_jobs: {job_key}")
                    del self.active_jobs[job_key]

        # Crea una lista di job attivi dal dizionario self.active_jobs
        active_jobs = []
        for job_key, job in self.active_jobs.items():
            # Ottieni PID e altri dettagli estesi per il monitoraggio
            process = job.get('process')
            pid = process.pid if process else None
            
            active_jobs.append({
                'source': job['source'],
                'target': job['target'],
                'dry_run': job['dry_run'],
                'log_file': job['log_file'],
                'start_time': job['start_time'],
                'duration': (datetime.now() - job['start_time']).total_seconds(),
                'recovered': job.get('recovered', False),  # Aggiungiamo il flag per processi recuperati
                'pid': pid  # Aggiungiamo il PID per tracciamento avanzato
            })

        # Cerchiamo processi rclone attivi nel sistema che non sono nei job attivi
        try:
            self._find_and_register_orphaned_processes(active_jobs)
        except Exception as e:
            logger.error(f"Error finding orphaned processes: {str(e)}")
        
        # Se richiesto, aggiungi anche i job segnati come running nel database
        if include_db_jobs:
            try:
                # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
                # Aggiungiamo la directory principale al path per l'import
                app_dir = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), '..'))
                if app_dir not in sys.path:
                    sys.path.insert(0, app_dir)

                # Importiamo i moduli necessari
                from models import SyncJobHistory, ScheduledJob, db
                from app import app  # Import diretto dell'app Flask

                # Utilizziamo il contesto dell'app esplicitamente
                with app.app_context():
                    # Ottieni tutti i job in stato "running" dal database
                    running_jobs = SyncJobHistory.query.filter_by(
                        status="running").all()

                    for db_job in running_jobs:
                        # Verifica se il job è già presente nella lista
                        job_key = f"{db_job.source}|{db_job.target}"
                        if job_key not in self.active_jobs:
                            # Verifica se il file di lock esiste ancora (entrambi i formati)
                            # Nuovo formato
                            tag_new = self._generate_tag(
                                db_job.source, db_job.target)
                            lock_file_new = f"{self.log_dir}/sync_{tag_new}.lock"

                            # Vecchio formato
                            tag_old = f"{db_job.source.replace(':', '_').replace('/', '_')}__TO__{db_job.target.replace(':', '_').replace('/', '_')}"
                            lock_file_old = f"{self.log_dir}/sync_{tag_old}.lock"

                            # Controlla entrambi i possibili file di lock
                            if os.path.exists(lock_file_new) or os.path.exists(
                                    lock_file_old):
                                # Il job è ancora in esecuzione
                                job_exists = False
                                for job in active_jobs:
                                    if job['source'] == db_job.source and job[
                                            'target'] == db_job.target:
                                        job_exists = True
                                        break

                                if not job_exists:
                                    # Aggiungi alla lista dei job attivi
                                    active_jobs.append({
                                        'source':
                                        db_job.source,
                                        'target':
                                        db_job.target,
                                        'dry_run':
                                        db_job.dry_run,
                                        'log_file':
                                        db_job.log_file,
                                        'start_time':
                                        db_job.start_time,
                                        'duration':
                                        (datetime.now() -
                                         db_job.start_time).total_seconds(),
                                        'from_scheduler': True,  # Flag per identificare i job avviati dallo scheduler
                                        'recovered': False  # Questi non sono job recuperati automaticamente
                                    })
                            else:
                                # Il file di lock non esiste più, aggiorniamo lo stato del job
                                # Se il job non ha un file di lock ma è in stato running, probabilmente
                                # si è interrotto inaspettatamente, quindi lo marchiamo come error
                                db_job.status = "error"
                                if not db_job.end_time:  # Se end_time non è già impostato
                                    db_job.end_time = datetime.now()
                                if not db_job.exit_code:  # Se exit_code non è impostato
                                    db_job.exit_code = -1  # Codice di errore generico
                                logger.warning(
                                    f"Job {db_job.id} ({db_job.source} → {db_job.target}) in stato running senza file di lock, marcato come error"
                                )
                                db.session.commit()
            except Exception as e:
                logger.error(f"Error getting database running jobs: {str(e)}")

        return active_jobs

    def is_job_running(self, source, target):
        """Check if a job with the given source and target is running
        
        - Controlla se il job è nei job attivi dell'handler
        - Verifica l'esistenza del file di lock (e la sua validità)
        - Controlla nel database se presente, ma solo se anche il lock file esiste
        
        IMPORTANTE: Questa funzione è progettata per essere "READ-ONLY" e non deve
        modificare lo stato di processi attivi o eseguire operazioni distruttive.
        """
        # Import necessari per il contesto esterno alla funzione
        import sys
        import os  # Reimportiamo os per garantire che sia disponibile nel contesto locale
        import time  # Reimportiamo time per garantire che sia disponibile nel contesto locale

        job_key = f"{source}|{target}"
        lock_exists = False
        process_running = False
        db_status_running = False

        # 1. Verifica nei job attivi nell'handler
        if job_key in self.active_jobs:
            job = self.active_jobs[job_key]
            try:
                if job['process'].poll() is None:
                    # Process is still running
                    process_running = True
                    logger.debug(
                        f"Job {job_key} has process running with PID {job['process'].pid}"
                    )
            except Exception as e:
                logger.error(f"Error checking process status: {str(e)}")
        
        # 1b. NON rimuoviamo questa parte ma la rendiamo più robusta, in modo che non modifichi processi
        # Se non troviamo il processo nei job attivi, controlliamo anche i processi di sistema
        # usando lo stesso filtro migliorato che esclude falsi positivi come journalctl
        if not process_running:
            try:
                import subprocess
                import re
                
                # Utilizziamo un timeout più breve per prevenire blocchi
                ps_output = subprocess.check_output(['ps', 'aux'], universal_newlines=True, timeout=5)
                lines = ps_output.split('\n')
                
                # Utilizziamo un filtro ancora più restrittivo
                rclone_lines = []
                for line in lines:
                    parts = line.split()
                    if len(parts) > 10:
                        command = ' '.join(parts[10:])
                        
                        # Verifichiamo che sia un vero comando rclone
                        is_rclone_command = False
                        
                        # Caso 1: Il comando è esattamente 'rclone'
                        if parts[10] == 'rclone' and len(parts) > 11:
                            # Verifichiamo che ci sia un'operazione rclone valida (sync, copy, check, etc.)
                            rclone_operations = ['sync', 'copy', 'move', 'check', 'ls', 'lsd', 'lsl', 'md5sum', 'sha1sum', 'size', 'delete', 'mkdir', 'rmdir', 'rcat', 'cat', 'copyto', 'moveto', 'copyurl', 'mount', 'about', 'cleanup', 'dedupe', 'version', 'touch', 'serve']
                            if parts[11] in rclone_operations:
                                is_rclone_command = True
                                
                        # Caso 2: Il comando è un percorso a rclone (come /usr/bin/rclone)
                        elif ('/rclone' in parts[10]) and len(parts) > 11:
                            if parts[10].endswith('/rclone') and parts[11] in ['sync', 'copy', 'move', 'check', 'ls', 'lsd', 'lsl', 'md5sum', 'sha1sum', 'size', 'delete', 'mkdir', 'rmdir', 'rcat', 'cat', 'copyto', 'moveto', 'copyurl', 'mount', 'about', 'cleanup', 'dedupe', 'version', 'touch', 'serve']:
                                is_rclone_command = True
                        
                        if is_rclone_command:
                            rclone_lines.append(line)
                
                # Cerchiamo se uno di questi processi contiene source e target
                source_pattern = re.escape(source)
                target_pattern = re.escape(target)
                # Proviamo prima una corrispondenza esatta
                exact_pattern = f"{source_pattern}.*{target_pattern}"
                
                # Poi proviamo una corrispondenza meno rigorosa con parti del percorso
                alternative_source = source.split('/')[-1] if '/' in source else source
                alternative_target = target.split('/')[-1] if '/' in target else target
                alt_pattern = f"{re.escape(alternative_source)}.*{re.escape(alternative_target)}"
                
                for line in rclone_lines:
                    if re.search(exact_pattern, line) or re.search(alt_pattern, line):
                        # Abbiamo trovato un processo rclone attivo per questo job
                        process_running = True
                        parts = line.split()
                        if len(parts) > 1:
                            pid = int(parts[1])
                            logger.debug(f"Found active rclone process with PID {pid} for job {source} → {target}")
                        break
            except Exception as e:
                logger.error(f"Error searching for active rclone processes: {str(e)}")
                # In caso di errore nell'analisi dei processi, NON modifichiamo lo stato

        # 2. Verifica l'esistenza del file di lock (entrambi i formati)
        # Nuovo formato
        tag_new = self._generate_tag(source, target)
        lock_file_new = f"{self.log_dir}/sync_{tag_new}.lock"

        # Vecchio formato
        tag_old = f"{source.replace(':', '_').replace('/', '_')}__TO__{target.replace(':', '_').replace('/', '_')}"
        lock_file_old = f"{self.log_dir}/sync_{tag_old}.lock"

        # Controlla prima il formato nuovo
        lock_file = None
        if os.path.exists(lock_file_new):
            lock_file = lock_file_new
            lock_exists = True
        elif os.path.exists(lock_file_old):
            lock_file = lock_file_old
            lock_exists = True

        # MODIFICA IMPORTANTE: NON rimuoviamo lock file in questa funzione
        # Serve solo a verificare, non a modificare lo stato

        # 3. Verifica anche nel database
        if process_running or lock_exists:
            try:
                # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
                import sys
                import os

                # Aggiungiamo la directory principale al path per l'import
                app_dir = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), '..'))
                if app_dir not in sys.path:
                    sys.path.insert(0, app_dir)

                # Importiamo i moduli necessari
                from models import SyncJobHistory, db
                from app import app  # Import diretto dell'app Flask

                # Utilizziamo il contesto dell'app esplicitamente
                with app.app_context():
                    # Cerca job attivi con lo stesso source/target
                    running_jobs = SyncJobHistory.query.filter_by(
                        source=source, target=target, status="running").all()

                    db_status_running = len(running_jobs) > 0
                    
                    # IMPORTANTE: NON modifichiamo lo stato del database in questa funzione
                    # Questo è cruciale per evitare di interrompere job attivi
                    
            except Exception as e:
                logger.error(
                    f"Error checking database for running jobs: {str(e)}")

        # Un job è considerato in esecuzione se:
        # 1. Il processo è attivo, OPPURE
        # 2. Il lock file esiste E lo stato nel database è "running"
        is_running = process_running or (lock_exists and db_status_running)

        if is_running:
            logger.debug(
                f"Job {source} → {target} is running: process={process_running}, lock={lock_exists}, db={db_status_running}"
            )

        return is_running

    def get_recent_logs(self, limit=10):
        """Get recent log files"""
        logs = []

        if not os.path.exists(self.log_dir):
            return logs

        try:
            # Get all log files
            files = os.listdir(self.log_dir)
            log_files = [
                f for f in files
                if f.startswith("sync_") and f.endswith(".log")
            ]

            # Sort by modification time (newest first)
            log_files.sort(
                key=lambda x: os.path.getmtime(os.path.join(self.log_dir, x)),
                reverse=True)

            # Get limited number of logs
            for log_file in log_files[:limit]:
                file_path = os.path.join(self.log_dir, log_file)

                # Parse source and target from filename
                # Prima prova il nuovo pattern (con i : preservati)
                match = re.search(
                    r'sync_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+?)_TO_(.+?)\.log$',
                    log_file)

                if match:
                    source = match.group(
                        1)  # Il source è già nel formato originale
                    target = match.group(
                        2)  # Il target è già nel formato originale
                else:
                    # Prova il vecchio pattern
                    match = re.search(
                        r'sync_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+?)__TO__(.+?)\.log$',
                        log_file)
                    if match:
                        source = match.group(1).replace('_',
                                                        ':').replace('-', '/')
                        target = match.group(2).replace('_',
                                                        ':').replace('-', '/')
                    else:
                        source = "Unknown"
                        target = "Unknown"

                # Get file stats
                stats = os.stat(file_path)

                logs.append({
                    'file': log_file,
                    'path': file_path,
                    'source': source,
                    'target': target,
                    'size': stats.st_size,
                    'modified': datetime.fromtimestamp(stats.st_mtime)
                })
        except Exception as e:
            logger.error(f"Error reading log directory: {str(e)}")

        return logs

    def read_main_config_file(self):
        """Read the main rclone config file content"""
        try:
            # Check if file exists
            if not os.path.exists(self.main_config_path):
                logger.warning(
                    f"Main config file not found: {self.main_config_path}")
                return "# Config file not found"

            # Read file content
            with open(self.main_config_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading main config file: {str(e)}")
            return f"# Error reading file: {str(e)}"

    def _find_and_register_orphaned_processes(self, active_jobs):
        """Cerca processi rclone orfani sul sistema e li registra nel database
        
        Trova processi rclone in esecuzione che non sono negli active_jobs
        e li registra nel database se corrispondono a job pianificati.
        
        Args:
            active_jobs: Lista dei job attivi corrente
        """
        # Import necessari per questa funzione
        import subprocess
        import re
        import os
        import sys
        import time
        from datetime import datetime
        
        # Troviamo tutti i processi rclone in esecuzione
        try:
            # Ottieni la lista dei processi in esecuzione con dettagli
            ps_output = subprocess.check_output(['ps', 'aux'], universal_newlines=True)
            lines = ps_output.split('\n')
            
            # Ottieni anche la lista di tutti i log file
            log_files = []
            if os.path.exists(self.log_dir):
                log_files = [f for f in os.listdir(self.log_dir) if f.startswith('sync_') and f.endswith('.log')]
            
            # Filtra solo i processi che sono effettivamente rclone (non quelli che lo contengono nei parametri)
            rclone_processes = []
            for line in lines:
                parts = line.split()
                if len(parts) > 10:
                    command = ' '.join(parts[10:])
                    # Verifica che sia un comando rclone reale e non ad esempio journalctl che monitora rclone
                    if (parts[10] == 'rclone' or 
                        '/rclone' in parts[10] or 
                        (command.startswith('/') and '/rclone' in command.split()[0])):
                        rclone_processes.append(line)
            
            if not rclone_processes:
                return  # Nessun processo rclone trovatoo
                
            # Aggiungiamo la directory principale al path per l'import
            app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)
            
            # Importiamo i moduli necessari
            from models import SyncJobHistory, ScheduledJob, db
            from app import app  # Import diretto dell'app Flask
            
            # Utilizziamo il contesto dell'app esplicitamente
            with app.app_context():
                # Ottieni tutti i job pianificati dal database
                scheduled_jobs = ScheduledJob.query.all()
                
                for process_line in rclone_processes:
                    # Estrai PID e comando
                    parts = process_line.split()
                    if len(parts) < 12:
                        continue  # Non abbastanza parti nella linea
                    
                    try:
                        pid = int(parts[1])
                        command = ' '.join(parts[10:])  # Comando completo
                        
                        # Verifica se questo processo è già nei job attivi OPPURE ha già un pid memorizzato
                        process_already_tracked = False
                        for job in active_jobs:
                            if 'source' in job and 'target' in job:
                                # Verifica se è lo stesso pid
                                if 'pid' in job and job['pid'] == pid:
                                    process_already_tracked = True
                                    break
                                # Verifica se sono gli stessi source/target
                                source_pattern = re.escape(job['source'])
                                target_pattern = re.escape(job['target'])
                                if re.search(source_pattern, command) and re.search(target_pattern, command):
                                    process_already_tracked = True
                                    # Aggiorna il PID se non era stato salvato
                                    if 'pid' not in job or job['pid'] is None:
                                        job['pid'] = pid
                                    break
                        
                        if process_already_tracked:
                            # Se questo processo è già tracciato, lo saltiamo silenziosamente
                            # Registra un'informazione solo la prima volta e poi silenzioso
                            if getattr(self, '_tracked_processes', None) is None:
                                self._tracked_processes = set()
                            
                            # Se è la prima volta che vediamo questo PID, logghiamo
                            if pid not in self._tracked_processes:
                                self._tracked_processes.add(pid)
                                logger.info(f"Processo rclone (PID {pid}) già registrato nel database")
                            
                            continue  # Processo già tracciato, passa al prossimo
                        
                        # Cerca di estrarre source e target dal comando
                        # Cerca pattern: rclone [operazione] source:path target:path
                        # Nota: questo è un'approssimazione, potrebbe richiedere regolazioni
                        words = command.split()
                        source = None
                        target = None
                        
                        # Trova la prima parola dopo 'rclone' che contiene ':'
                        source_index = -1
                        for i, word in enumerate(words):
                            if i > 0 and ':' in word and not word.startswith('-'):
                                source = word
                                source_index = i
                                break
                        
                        # Se abbiamo trovato source, cerca target (la prossima parola che contiene ':' o la successiva)
                        if source_index > 0 and source_index < len(words) - 1:
                            # Prima cerca se c'è un'altra parola con ':'
                            for word in words[source_index + 1:]:
                                if not word.startswith('-') and ((':' in word) or ('/' in word)):
                                    target = word
                                    break
                            
                            # Se non lo trova, prova a usare la parola immediatamente successiva
                            if target is None and source_index + 1 < len(words):
                                target = words[source_index + 1]
                        
                        # Se non siamo riusciti a estrarre source o target, continua
                        if source is None or target is None:
                            logger.debug(f"Impossibile estrarre source/target dal processo rclone PID {pid}")
                            continue
                        
                        # Verifica se source e target corrispondono a qualche job pianificato
                        matched_scheduled_job = None
                        for job in scheduled_jobs:
                            # Verifica se il source e target corrispondono completamente o sono parte del comando
                            if (job.source == source or job.source in command) and \
                               (job.target == target or job.target in command):
                                matched_scheduled_job = job
                                break
                        
                        if matched_scheduled_job:
                            # Verifica se esiste già un record nella history per questo job
                            existing_history = SyncJobHistory.query.filter_by(
                                source=matched_scheduled_job.source,
                                target=matched_scheduled_job.target,
                                status="running"
                            ).first()
                            
                            if existing_history:
                                # Controlliamo se il processo è già registrato nei job attivi
                                source_exists = False
                                for job in active_jobs:
                                    if job.get('source') == matched_scheduled_job.source and \
                                       job.get('target') == matched_scheduled_job.target:
                                        source_exists = True
                                        break
                                
                                # Solo la prima volta logghiamo che il processo è già registrato
                                if not source_exists:
                                    # Registra un'informazione solo la prima volta e poi silenzioso
                                    if getattr(self, '_tracked_processes', None) is None:
                                        self._tracked_processes = set()
                                    
                                    # Se è la prima volta che vediamo questo PID e source/target, logghiamo
                                    process_key = f"{pid}_{matched_scheduled_job.source}_{matched_scheduled_job.target}"
                                    first_detection = process_key not in self._tracked_processes
                                    
                                    if first_detection:
                                        self._tracked_processes.add(process_key)
                                        logger.info(f"Processo rclone (PID {pid}) già registrato nel database: {matched_scheduled_job.source} → {matched_scheduled_job.target}")
                                    
                                    # Prova a trovare il timestamp reale di inizio dal log
                                    real_start_time = existing_history.start_time
                                    
                                    # Creiamo una chiave specifica per il calcolo del tempo
                                    time_key = f"time_calculated_{pid}"
                                    if time_key not in self._tracked_processes:
                                        self._tracked_processes.add(time_key)
                                        try:
                                            # Se possiamo trovare informazioni su quando è stato effettivamente avviato il processo
                                            proc_stat_file = f"/proc/{pid}/stat"
                                            if os.path.exists(proc_stat_file):
                                                # Leggi il tempo di avvio dal file stat
                                                with open(proc_stat_file, 'r') as f:
                                                    stat_content = f.read().split()
                                                    if len(stat_content) > 21:  # Assicurati che ci siano abbastanza campi
                                                        # Campo 22 (indice 21) è il tempo di avvio in clock tick
                                                        start_time_ticks = int(stat_content[21])
                                                        # Converti in secondi dal boot
                                                        with open('/proc/uptime', 'r') as uptime_file:
                                                            uptime = float(uptime_file.read().split()[0])
                                                        # Determina clock ticks per secondo (normalmente 100)
                                                        clock_ticks = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                                                        # Calcola quanto tempo fa è stato avviato il processo (in secondi)
                                                        seconds_since_boot = start_time_ticks / clock_ticks
                                                        # Calcola il timestamp reale
                                                        seconds_ago = uptime - seconds_since_boot
                                                        real_start_time = datetime.now() - timedelta(seconds=seconds_ago)
                                                        
                                                        # Aggiorna anche il record nel database per mostrare il tempo reale
                                                        # anche nella history view
                                                        existing_history.start_time = real_start_time
                                                        db.session.commit()
                                                        
                                                        logger.info(f"Tempo di avvio reale del processo {pid} calcolato: {real_start_time} e aggiornato nel database")
                                        except Exception as e:
                                            logger.warning(f"Impossibile determinare il tempo reale di avvio del processo {pid}: {e}")
                                    
                                    # Aggiungiamo alla lista dei job attivi
                                    active_jobs.append({
                                        'source': matched_scheduled_job.source,
                                        'target': matched_scheduled_job.target,
                                        'dry_run': False,  # Assumiamo che non sia in dry-run
                                        'log_file': existing_history.log_file,
                                        'start_time': real_start_time,  # Usa il timestamp reale se disponibile
                                        'duration': (datetime.now() - real_start_time).total_seconds(),
                                        'recovered': True,  # Flag per indicare che è stato recuperato
                                        'pid': pid  # Salviamo il PID
                                    })
                                    
                                    # Log solo alla prima aggiunta
                                    if first_detection:
                                        logger.info(f"Job {matched_scheduled_job.source} → {matched_scheduled_job.target} aggiunto alla lista dei job attivi")
                            else:
                                # Cerca di trovare un log file esistente per questo comando rclone
                                now = datetime.now()
                                timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
                                source_tag = self._generate_tag(matched_scheduled_job.source, matched_scheduled_job.target)
                                
                                # Prima tenta di trovare un file di log esistente nel comando
                                existing_log_file = None
                                log_path_pattern = re.compile(r"--log-file[= ]([^ ]+)")
                                log_match = log_path_pattern.search(command)
                                if log_match:
                                    cmd_log_file = log_match.group(1)
                                    if os.path.exists(cmd_log_file):
                                        existing_log_file = cmd_log_file
                                        logger.info(f"Trovato file di log nel comando: {existing_log_file}")
                                
                                # Se non trova nel comando, cerca nei file log esistenti con questo tag
                                if not existing_log_file:
                                    for log_name in log_files:
                                        if source_tag in log_name:
                                            # Verifica se il file è recente (ultime 24 ore)
                                            log_path = os.path.join(self.log_dir, log_name)
                                            if os.path.exists(log_path):
                                                mtime = os.path.getmtime(log_path)
                                                if (now - datetime.fromtimestamp(mtime)).total_seconds() < 86400:  # 24 ore
                                                    existing_log_file = log_path
                                                    logger.info(f"Trovato file di log esistente per questo job: {existing_log_file}")
                                                    break
                                
                                # Se non troviamo un log file esistente, ne creiamo uno nuovo
                                if existing_log_file:
                                    log_file = existing_log_file
                                else:
                                    log_file = f"{self.log_dir}/sync_{timestamp}_{source_tag}.log"
                                
                                # Creiamo anche un file di lock
                                lock_file = f"{self.log_dir}/sync_{source_tag}.lock"
                                try:
                                    with open(lock_file, 'w') as f:
                                        f.write(str(pid))
                                    
                                    # Backup del PID
                                    with open(f"{lock_file}.bak", 'w') as f:
                                        f.write(str(pid))
                                        
                                    logger.info(f"Creato lock file per processo orfano: {lock_file}")
                                    
                                    # Crea o aggiorna il file di log
                                    # Se abbiamo trovato un file esistente, aggiungiamo solo una nota
                                    if existing_log_file:
                                        # Apriamo il file in modalità append
                                        with open(log_file, 'a') as f:
                                            f.write(f"\n\n=== JOB RICONNESSO AL PROCESSO ESISTENTE ===\n")
                                            f.write(f"Source: {matched_scheduled_job.source}\n")
                                            f.write(f"Target: {matched_scheduled_job.target}\n")
                                            f.write(f"PID: {pid}\n")
                                            f.write(f"Data Riconnessione: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                                            f.write(f"Comando originale: {command}\n")
                                            f.write(f"=================================\n\n")
                                    else:
                                        # Altrimenti creiamo un nuovo file
                                        with open(log_file, 'w') as f:
                                            f.write(f"=== JOB RECUPERATO AUTOMATICAMENTE ===\n")
                                            f.write(f"Source: {matched_scheduled_job.source}\n")
                                            f.write(f"Target: {matched_scheduled_job.target}\n")
                                            f.write(f"PID: {pid}\n")
                                            f.write(f"Data: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                                            f.write(f"Comando originale: {command}\n")
                                            f.write(f"=================================\n\n")
                                    
                                    # Crea nuovo record nella history
                                    # Se abbiamo un file di log esistente, stimiamo il tempo di inizio dal timestamp nel nome
                                    estimated_start_time = now
                                    if existing_log_file:
                                        try:
                                            # Cerca di estrarre il timestamp dal nome del file o leggi la data di modifica
                                            if os.path.exists(existing_log_file):
                                                # Prova prima dal nome file se è uno dei nostri file di log
                                                if 'sync_' in os.path.basename(existing_log_file):
                                                    # Il formato è sync_YYYY-MM-DD_HH-MM-SS_*.log
                                                    basename = os.path.basename(existing_log_file)
                                                    date_part = basename.split('sync_')[1].split('_')[0]
                                                    time_part = basename.split('sync_')[1].split('_')[1]
                                                    if len(date_part) == 10 and len(time_part) == 8:  # YYYY-MM-DD e HH-MM-SS
                                                        try:
                                                            str_datetime = f"{date_part} {time_part.replace('-', ':')}"
                                                            estimated_start_time = datetime.strptime(str_datetime, "%Y-%m-%d %H:%M:%S")
                                                            logger.info(f"Tempo di inizio stimato dal nome del file: {estimated_start_time}")
                                                        except Exception as e:
                                                            logger.warning(f"Impossibile estrarre timestamp dal nome file: {e}")
                                                
                                                # Se non riusciamo dal nome, usiamo la data di creazione/modifica del file
                                                if estimated_start_time == now:
                                                    file_ctime = os.path.getctime(existing_log_file)
                                                    estimated_start_time = datetime.fromtimestamp(file_ctime)
                                                    logger.info(f"Tempo di inizio stimato dalla data di creazione del file: {estimated_start_time}")
                                        except Exception as e:
                                            logger.warning(f"Errore stimando il tempo di inizio: {e}, uso il tempo corrente")
                                            estimated_start_time = now
                                    
                                    new_history = SyncJobHistory(
                                        source=matched_scheduled_job.source,
                                        target=matched_scheduled_job.target,
                                        status="running",
                                        dry_run=False,  # Assumiamo che non sia in dry-run
                                        start_time=estimated_start_time,
                                        log_file=log_file
                                    )
                                    db.session.add(new_history)
                                    db.session.commit()
                                    logger.info(f"Creato nuovo record nella history per processo orfano: {matched_scheduled_job.source} → {matched_scheduled_job.target}")
                                    
                                    # Aggiungi alla lista dei job attivi
                                    active_jobs.append({
                                        'source': matched_scheduled_job.source,
                                        'target': matched_scheduled_job.target,
                                        'dry_run': False,  # Assumiamo che non sia in dry-run
                                        'log_file': log_file,
                                        'start_time': estimated_start_time,  # Usa lo stesso timestamp che abbiamo calcolato
                                        'duration': (now - estimated_start_time).total_seconds(),  # Calcola la durata corretta
                                        'recovered': True,  # Flag per indicare che è stato recuperato
                                        'pid': pid  # Salviamo il PID
                                    })
                                except Exception as e:
                                    logger.error(f"Errore durante la registrazione del processo orfano: {str(e)}")
                        else:
                            logger.debug(f"Nessun job pianificato trovato per il processo rclone: {source} → {target}")
                    except Exception as e:
                        logger.error(f"Errore durante l'analisi del processo rclone: {str(e)}")
                        continue
        except Exception as e:
            logger.error(f"Errore durante la ricerca di processi rclone orfani: {str(e)}")
            return

    def save_main_config_file(self, content):
        """Save changes to the main rclone config file"""
        try:
            # Create parent directory if needed
            os.makedirs(os.path.dirname(self.main_config_path), exist_ok=True)

            # Backup the original file before overwrite
            if os.path.exists(self.main_config_path):
                backup_path = f"{self.main_config_path}.bak"
                with open(self.main_config_path, 'r') as src:
                    with open(backup_path, 'w') as dst:
                        dst.write(src.read())
                logger.info(f"Backup created: {backup_path}")

            # Write the new content
            with open(self.main_config_path, 'w') as f:
                f.write(content)

            logger.info(f"Main config file updated: {self.main_config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving main config file: {str(e)}")
            raise
