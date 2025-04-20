import os
import re
import json
import time
import logging
import subprocess
from datetime import datetime
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
                    path_part = path_part.replace('http://', '').replace('https://', '')
                
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
                    logger.info(f"Rimosso lock file stale: {lock_file} (età: {file_age:.1f}s)")
                except Exception as e:
                    logger.error(f"Errore durante la rimozione del lock file stale: {str(e)}")
            else:
                # Il file esiste ed è recente, segnaliamo che il job è già in esecuzione
                raise Exception(f"A job with the same source and target is already running: {source} → {target}")
        
        # Prepare command
        cmd = ["/bin/bash", "-c", f"rclone sync '{source}' '{target}' --progress --stats=15s"]
        
        # Add dry-run flag if needed
        if dry_run:
            cmd[-1] += " --dry-run"
        
        # Add other common options
        cmd[-1] += " --log-level INFO"
        cmd[-1] += f" --log-file '{log_file}'"
        cmd[-1] += " --no-check-certificate"
        
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
                for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
                    if proxy_var in my_env:
                        del my_env[proxy_var]
                        logger.info(f"Unset proxy variable for hash check: {proxy_var}")
                
                # Utilizzare Popen invece di run per maggiore compatibilità con versioni Python più vecchie
                src_process = subprocess.Popen(
                    src_hashes_cmd, 
                    shell=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    universal_newlines=True,
                    env=my_env
                )
                src_stdout, src_stderr = src_process.communicate()
                src_result_text = src_stdout
                src_returncode = src_process.returncode

                tgt_process = subprocess.Popen(
                    tgt_hashes_cmd, 
                    shell=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    universal_newlines=True,
                    env=my_env
                )
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
                logger.warning(f"Error determining hash capability: {str(e)}. Using --size-only")
                cmd[-1] += " --size-only"
        else:
            # Default to size-only if we can't determine
            cmd[-1] += " --size-only"
        
        # Add other common options
        cmd[-1] += " --transfers=4 --checkers=8 --retries=10"
        
        # Add user-requested default flags
        cmd[-1] += " --metadata --use-server-modtime --gcs-bucket-policy-only"
        
        # Prepara il comando esatto con tutti gli argomenti
        full_command = cmd[-1]
        
        # Log the complete command being executed
        logger.info(f"Executing command: {full_command}")
        
        # Scrivi il comando completo direttamente nel file di log
        try:
            with open(log_file, 'w') as f:
                f.write(f"=============== COMANDO RCLONE ESEGUITO ===============\n")
                f.write(f"{full_command}\n")
                f.write(f"======================================================\n\n")
                
            # Verifica che il contenuto sia stato effettivamente scritto
            with open(log_file, 'r') as f:
                file_content = f.read(100)  # Leggi i primi 100 caratteri 
                if "COMANDO RCLONE ESEGUITO" not in file_content:
                    logger.error(f"Il comando non è stato scritto nel file di log correttamente: {log_file}")
        except Exception as e:
            logger.error(f"Errore durante la scrittura del comando nel file di log: {str(e)}")
        
        # Crea un ambiente senza variabili proxy
        my_env = os.environ.copy()
        for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
            if proxy_var in my_env:
                del my_env[proxy_var]
                logger.info(f"Unset proxy variable: {proxy_var}")
        
        # Modifica: utilizza il parametro shell=True per assicurarci di ottenere l'exit code corretto
        # quando rclone incontra errori (come directory non trovate)
        process = subprocess.Popen(
            full_command,  # Passiamo il comando completo come stringa 
            shell=True,  # Eseguiamo tramite shell per una gestione migliore degli errori
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            universal_newlines=True,  # Equivalente a text=True nelle versioni più recenti
            env=my_env
        )
        
        logger.info(f"Started rclone process with PID {process.pid}")
        
        # Create lock file
        with open(lock_file, 'w') as f:
            f.write(str(process.pid))
        
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
        Thread(target=self._monitor_job, args=(job_key,), daemon=True).start()
        
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
        
        if job_key not in self.active_jobs:
            return
        
        job = self.active_jobs[job_key]
        process = job['process']
        
        # Wait for process to finish
        process.wait()
        
        # Remove lock file
        if os.path.exists(job['lock_file']):
            try:
                os.remove(job['lock_file'])
                logger.info(f"Removed lock file: {job['lock_file']}")
            except Exception as e:
                logger.error(f"Failed to remove lock file {job['lock_file']}: {str(e)}")
        
        # Update job info with end time and status
        job['end_time'] = datetime.now()
        job['exit_code'] = process.returncode
        
        # Verifica se il job ha prodotto errori nei log
        success = process.returncode == 0
        if success and job.get('log_file') and os.path.exists(job.get('log_file')):
            try:
                with open(job.get('log_file'), 'r') as f:
                    log_content = f.read()
                    # Controlla se ci sono indicazioni di errore nei log, anche se l'exit code è 0
                    # Rclone a volte termina con successo anche se ci sono stati errori
                    # Verifichiamo il contenuto escludendo le righe di INFO
                    if (
                        (" ERROR " in log_content.upper() or " ERROR:" in log_content.upper()) or 
                        (" FATAL " in log_content.upper() or " FATAL:" in log_content.upper()) or
                        "NOTICE: Failed" in log_content or
                        ("Errors:" in log_content and "0)" not in log_content.split("Errors:")[1].split("\n")[0])
                    ):
                        # Manteniamo il job come successo se il messaggio di errore è solo informativo
                        # o se il job ha riguardato 0 file (nothing to transfer)
                        if "There was nothing to transfer" in log_content:
                            # Non consideriamo un errore il caso "nothing to transfer"
                            logger.info(f"Job reported 'nothing to transfer' - keeping as success")
                        else:
                            success = False
                            logger.warning(f"Job exit code was 0 but errors found in log, marking as failed")
            except Exception as e:
                logger.error(f"Error reading log file for job completion: {str(e)}")
        
        status = "completed successfully" if success else f"failed with exit code {process.returncode}"
        logger.info(f"Job {job['source']} → {job['target']} {status}")
        
        # Registra anche l'exit code nel file di log per riferimento futuro
        if job.get('log_file') and os.path.exists(job.get('log_file')):
            try:
                with open(job.get('log_file'), 'a') as f:
                    f.write(f"\n\n=============== RISULTATO DEL JOB ===============\n")
                    f.write(f"Exit code: {process.returncode}\n")
                    if success:
                        f.write(f"Status: Completato con successo\n")
                    else:
                        f.write(f"Status: Completato con errori\n")
                    f.write(f"Data/ora fine: {job['end_time'].strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"======================================================\n")
                logger.info(f"Updated log file with job result information")
            except Exception as e:
                logger.error(f"Error updating log file with job result: {str(e)}")
        
        # Aggiorna il database e invia notifica di completamento
        try:
            # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
            # Eseguiamo una chiamata diretta al modulo models importandolo nel contesto attuale
            import sys
            import os
            
            # Aggiungiamo la directory principale al path per l'import
            app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
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
                    log_file=job['log_file']
                ).first()
                
                if history_job:
                    # Aggiorna lo stato
                    history_job.status = "completed" if success else "error"
                    history_job.end_time = job['end_time']
                    history_job.exit_code = job['exit_code']
                    db.session.commit()
                    
                    # Invia notifica di completamento
                    duration = (job['end_time'] - job['start_time']).total_seconds()
                    notify_job_completed(history_job.id, job['source'], job['target'], 
                                        success=success, duration=duration)
                    
                    logger.info(f"Successfully updated job status in database to {'completed' if success else 'error'}")
                else:
                    logger.warning(f"No database entry found for job {job_key}")
        except Exception as e:
            logger.error(f"Error updating job status in database: {str(e)}")
        
        # Remove from active jobs after a delay
        time.sleep(60)  # Keep in active jobs list for 1 minute after completion
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
                    del self.active_jobs[job_key]
        
        # Crea una lista di job attivi dal dizionario self.active_jobs
        active_jobs = []
        for job_key, job in self.active_jobs.items():
            active_jobs.append({
                'source': job['source'],
                'target': job['target'],
                'dry_run': job['dry_run'],
                'log_file': job['log_file'],
                'start_time': job['start_time'],
                'duration': (datetime.now() - job['start_time']).total_seconds()
            })
        
        # Se richiesto, aggiungi anche i job segnati come running nel database
        if include_db_jobs:
            try:
                # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
                # Aggiungiamo la directory principale al path per l'import
                app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                if app_dir not in sys.path:
                    sys.path.insert(0, app_dir)
                
                # Importiamo i moduli necessari
                from models import SyncJobHistory, db
                from app import app  # Import diretto dell'app Flask
                
                # Utilizziamo il contesto dell'app esplicitamente
                with app.app_context():
                    # Ottieni tutti i job in stato "running" dal database
                    running_jobs = SyncJobHistory.query.filter_by(status="running").all()
                    
                    for db_job in running_jobs:
                        # Verifica se il job è già presente nella lista
                        job_key = f"{db_job.source}|{db_job.target}"
                        if job_key not in self.active_jobs:
                            # Verifica se il file di lock esiste ancora
                            tag = self._generate_tag(db_job.source, db_job.target)
                            lock_file = f"{self.log_dir}/sync_{tag}.lock"
                            
                            if os.path.exists(lock_file):
                                # Il job è ancora in esecuzione
                                job_exists = False
                                for job in active_jobs:
                                    if job['source'] == db_job.source and job['target'] == db_job.target:
                                        job_exists = True
                                        break
                                
                                if not job_exists:
                                    # Aggiungi alla lista dei job attivi
                                    active_jobs.append({
                                        'source': db_job.source,
                                        'target': db_job.target,
                                        'dry_run': db_job.dry_run,
                                        'log_file': db_job.log_file,
                                        'start_time': db_job.start_time,
                                        'duration': (datetime.now() - db_job.start_time).total_seconds(),
                                        'from_scheduler': True  # Flag per identificare i job avviati dallo scheduler
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
                                logger.warning(f"Job {db_job.id} ({db_job.source} → {db_job.target}) in stato running senza file di lock, marcato come error")
                                db.session.commit()
            except Exception as e:
                logger.error(f"Error getting database running jobs: {str(e)}")
        
        return active_jobs
    
    def is_job_running(self, source, target):
        """Check if a job with the given source and target is running
        
        - Controlla se il job è nei job attivi dell'handler
        - Verifica l'esistenza del file di lock (e la sua validità)
        - Controlla nel database se presente
        """
        # Import necessari per il contesto esterno alla funzione
        import sys
        # os è già importato a livello globale
        
        job_key = f"{source}|{target}"
        
        # Verifica nei job attivi nell'handler
        if job_key in self.active_jobs:
            job = self.active_jobs[job_key]
            if job['process'].poll() is None:
                # Process is still running
                return True
        
        # Verifica l'esistenza del file di lock
        tag = self._generate_tag(source, target)
        lock_file = f"{self.log_dir}/sync_{tag}.lock"
        if os.path.exists(lock_file):
            # Verifica se il lock file è stale (più vecchio di 1 ora)
            file_age = time.time() - os.path.getmtime(lock_file)
            
            if file_age > 3600:  # Se è più vecchio di 1 ora, non è un job in esecuzione
                try:
                    # Rimuovi il lock file stale
                    os.remove(lock_file)
                    logger.info(f"Rimosso lock file stale durante il controllo job: {lock_file} (età: {file_age:.1f}s)")
                    return False  # Il job non è in esecuzione
                except Exception as e:
                    logger.error(f"Errore durante la rimozione del lock file stale: {str(e)}")
                    # In caso di errore nella rimozione, assumiamo che il job sia ancora in esecuzione
                    return True
            else:
                # Il lock file esiste ed è recente, il job è in esecuzione
                return True
            
        # Verifica anche nel database se c'è un job attivo
        try:
            # Utilizziamo una soluzione più robusta che non richiede un contesto Flask attivo
            # Eseguiamo una chiamata diretta al modulo models importandolo nel contesto attuale
            import sys
            import os
            
            # Aggiungiamo la directory principale al path per l'import
            app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)
            
            # Importiamo i moduli necessari
            from models import SyncJobHistory, db
            from app import app  # Import diretto dell'app Flask
            
            # Utilizziamo il contesto dell'app esplicitamente
            with app.app_context():
                # Cerca job attivi con lo stesso source/target
                running_jobs = SyncJobHistory.query.filter_by(
                    source=source,
                    target=target,
                    status="running"
                ).all()
                
                return len(running_jobs) > 0
        except Exception as e:
            logger.error(f"Error checking database for running jobs: {str(e)}")
            # In caso di errore, basati solo sul file di lock
            return False
    
    def get_recent_logs(self, limit=10):
        """Get recent log files"""
        logs = []
        
        if not os.path.exists(self.log_dir):
            return logs
        
        try:
            # Get all log files
            files = os.listdir(self.log_dir)
            log_files = [f for f in files if f.startswith("sync_") and f.endswith(".log")]
            
            # Sort by modification time (newest first)
            log_files.sort(key=lambda x: os.path.getmtime(os.path.join(self.log_dir, x)), reverse=True)
            
            # Get limited number of logs
            for log_file in log_files[:limit]:
                file_path = os.path.join(self.log_dir, log_file)
                
                # Parse source and target from filename
                # Prima prova il nuovo pattern (con i : preservati)
                match = re.search(r'sync_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+?)_TO_(.+?)\.log$', log_file)
                
                if match:
                    source = match.group(1)  # Il source è già nel formato originale
                    target = match.group(2)  # Il target è già nel formato originale
                else:
                    # Prova il vecchio pattern
                    match = re.search(r'sync_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+?)__TO__(.+?)\.log$', log_file)
                    if match:
                        source = match.group(1).replace('_', ':').replace('-', '/') 
                        target = match.group(2).replace('_', ':').replace('-', '/')
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
                logger.warning(f"Main config file not found: {self.main_config_path}")
                return "# Config file not found"
            
            # Read file content
            with open(self.main_config_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading main config file: {str(e)}")
            return f"# Error reading file: {str(e)}"
    
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

