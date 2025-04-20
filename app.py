import os
import logging
import time
import json
import threading
from threading import Thread
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, send_from_directory
from models import db, SyncJob, SyncJobHistory, ScheduledJob, UserSettings, Notification
from utils.rclone_handler import RCloneHandler
from utils.scheduler import JobScheduler
from utils.notification_manager import get_notifications, mark_notification_read, mark_all_read, add_notification
from utils.notification_manager import notify_job_started, notify_job_completed, get_user_settings, update_settings
from utils.backup_manager import create_backup as create_backup_func, list_backups, restore_backup, delete_backup, setup_auto_backup, get_backup_dir

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")

# Configure SQLite database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///rclone_manager.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize database
db.init_app(app)

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

# Initialize RClone handler - use current directory for logs in Replit environment
RCLONE_CONFIG_PATH = os.environ.get("RCLONE_CONFIG_PATH", "./data/rclone_scheduled.conf")
LOG_DIR = os.environ.get("RCLONE_LOG_DIR", "./data/logs")

# Create necessary directories
os.makedirs(os.path.dirname(RCLONE_CONFIG_PATH), exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Initialize the rclone handler
rclone_handler = RCloneHandler(RCLONE_CONFIG_PATH, LOG_DIR)

# Initialize job scheduler with the Flask app
job_scheduler = JobScheduler(rclone_handler, LOG_DIR, app=app)

# Log rclone configuration paths for easy reference
logger.info("=== RCLONE Configuration Paths ===")
logger.info(f"Jobs Config: {RCLONE_CONFIG_PATH}")
logger.info(f"Main Config: {rclone_handler.main_config_path}")
logger.info(f"Log Directory: {LOG_DIR}")
logger.info("==================================")

# Lo scheduler viene avviato esternamente:
# - In modalità sviluppo: viene avviato da main.py
# - In modalità produzione: viene avviato da scheduler_runner.py

# Add template context processors
@app.context_processor
def inject_now():
    """Inject the current datetime into templates"""
    return {'now': datetime.now()}

def check_orphaned_jobs():
    """Check for jobs stuck in 'running' status and clean them up"""
    try:
        with app.app_context():
            running_jobs = SyncJobHistory.query.filter_by(status="running").all()
            
            for job in running_jobs:
                # Verifica se il job è ancora in esecuzione
                if not rclone_handler.is_job_running(job.source, job.target):
                    # Se il job non è più in esecuzione, controlla se c'è stato un errore
                    # Cerchiamo di controllare il log file per determinare il risultato
                    if job.log_file and os.path.exists(job.log_file):
                        try:
                            with open(job.log_file, 'r') as f:
                                log_content = f.read()
                                # Cerca indicazioni di errore nel log
                                # Controlliamo i messaggi di errore in diversi formati comuni
                                if ("ERROR" in log_content.upper() or 
                                    "FATAL" in log_content.upper() or 
                                    "ERROR :" in log_content or 
                                    "NOTICE: Failed" in log_content or
                                    "Errors:" in log_content and "0)" not in log_content.split("Errors:")[1].split("\n")[0]):
                                    job.status = "error"
                                    logger.info(f"Job {job.id} terminated with errors")
                                else:
                                    job.status = "completed"
                                    logger.info(f"Job {job.id} completed successfully")
                        except Exception as e:
                            logger.error(f"Error reading log file: {str(e)}")
                            job.status = "error"  # Assumiamo errore se non possiamo leggere il log
                    else:
                        # Non abbiamo un log file, assumiamo completamento con successo
                        job.status = "completed"
                    
                    job.end_time = datetime.now()
                    
                    # Inoltre, elimina eventuali file di lock persistenti
                    tag = rclone_handler._generate_tag(job.source, job.target)
                    lock_file = f"{LOG_DIR}/sync_{tag}.lock"
                    if os.path.exists(lock_file):
                        try:
                            os.remove(lock_file)
                            logger.info(f"Removed orphaned lock file: {lock_file}")
                        except Exception as e:
                            logger.error(f"Error removing lock file: {str(e)}")
                    
                    logger.info(f"Updated orphaned job status: {job.id} {job.source} → {job.target}")
            
            db.session.commit()
    except Exception as e:
        logger.error(f"Error checking orphaned jobs: {str(e)}")

def force_cleanup_jobs():
    """Force cleanup of all jobs marked as running"""
    try:
        with app.app_context():
            # Ottieni tutti i job in stato running
            running_jobs = SyncJobHistory.query.filter_by(status="running").all()
            cleaned_count = 0
            
            for job in running_jobs:
                # Determina lo stato corretto in base ai log e all'exit_code
                if job.log_file and os.path.exists(job.log_file):
                    try:
                        with open(job.log_file, 'r') as f:
                            log_content = f.read()
                            # Cerca indicazioni di errore nel log
                            # Controlliamo i messaggi di errore in diversi formati comuni
                            # Usiamo criteri più restrittivi per evitare falsi positivi
                            if (
                                (" ERROR " in log_content.upper() or " ERROR:" in log_content.upper()) or 
                                (" FATAL " in log_content.upper() or " FATAL:" in log_content.upper()) or
                                "NOTICE: Failed" in log_content or
                                ("Errors:" in log_content and "0)" not in log_content.split("Errors:")[1].split("\n")[0])
                            ):
                                # Manteniamo il job come successo se non ci sono veri errori o
                                # se il job ha riguardato 0 file (nothing to transfer)
                                if "There was nothing to transfer" in log_content:
                                    # Non consideriamo un errore il caso "nothing to transfer"
                                    job.status = "completed"
                                    logger.info(f"Forced cleanup job {job.id} marked as completed (nothing to transfer)")
                                else:
                                    job.status = "error"
                                    logger.info(f"Forced cleanup job {job.id} marked as error based on log content")
                            else:
                                job.status = "completed"
                                logger.info(f"Forced cleanup job {job.id} marked as completed")
                    except Exception as e:
                        logger.error(f"Error reading log file for forced cleanup job {job.id}: {str(e)}")
                        # In caso di errore di lettura, assumiamo completato con errore
                        job.status = "error"
                else:
                    # Se non abbiamo log file, controlliamo l'exit_code
                    if job.exit_code is not None and job.exit_code != 0:
                        job.status = "error"
                        logger.info(f"Forced cleanup job {job.id} marked as error based on exit code {job.exit_code}")
                    else:
                        job.status = "completed"
                        logger.info(f"Forced cleanup job {job.id} marked as completed (no log file)")
                
                job.end_time = datetime.now() if not job.end_time else job.end_time
                
                # Rimuovi i file di lock associati
                tag = rclone_handler._generate_tag(job.source, job.target)
                lock_file = f"{LOG_DIR}/sync_{tag}.lock"
                if os.path.exists(lock_file):
                    try:
                        os.remove(lock_file)
                        logger.info(f"Removed lock file: {lock_file}")
                    except Exception as e:
                        logger.error(f"Error removing lock file: {str(e)}")
                
                logger.info(f"Force cleaned job: {job.id} {job.source} → {job.target}")
                cleaned_count += 1
            
            # Commit the changes
            db.session.commit()
            return cleaned_count
            
    except Exception as e:
        logger.error(f"Error in force cleanup: {str(e)}")
        return 0

# Funzione per pulire gli spazi nei percorsi
def clean_path_whitespace():
    """Rimuove gli spazi extra nei percorsi salvati nel database"""
    try:
        # Correggi eventuali spazi nei job pianificati
        scheduled_jobs = ScheduledJob.query.all()
        jobs_updated = 0
        
        for job in scheduled_jobs:
            source_stripped = job.source.strip()
            target_stripped = job.target.strip()
            
            if source_stripped != job.source or target_stripped != job.target:
                logger.info(f"Pulizia spazi nel job pianificato {job.id}: '{job.source}' → '{source_stripped}', '{job.target}' → '{target_stripped}'")
                job.source = source_stripped
                job.target = target_stripped
                jobs_updated += 1
        
        if jobs_updated > 0:
            db.session.commit()
            logger.info(f"Puliti {jobs_updated} job pianificati con spazi nei percorsi")
            
        # Correggi eventuali spazi nella cronologia dei job
        history_jobs = SyncJobHistory.query.all()
        history_updated = 0
        
        for job in history_jobs:
            source_stripped = job.source.strip()
            target_stripped = job.target.strip()
            
            if source_stripped != job.source or target_stripped != job.target:
                logger.info(f"Pulizia spazi nel job storico {job.id}: '{job.source}' → '{source_stripped}', '{job.target}' → '{target_stripped}'")
                job.source = source_stripped
                job.target = target_stripped
                history_updated += 1
        
        if history_updated > 0:
            db.session.commit()
            logger.info(f"Puliti {history_updated} job storici con spazi nei percorsi")
            
        # Correggi eventuali spazi nei job configurati
        sync_jobs = SyncJob.query.all()
        sync_updated = 0
        
        for job in sync_jobs:
            source_stripped = job.source.strip()
            target_stripped = job.target.strip()
            
            if source_stripped != job.source or target_stripped != job.target:
                logger.info(f"Pulizia spazi nel job configurato {job.id}: '{job.source}' → '{source_stripped}', '{job.target}' → '{target_stripped}'")
                job.source = source_stripped
                job.target = target_stripped
                sync_updated += 1
        
        if sync_updated > 0:
            db.session.commit()
            logger.info(f"Puliti {sync_updated} job configurati con spazi nei percorsi")
            
    except Exception as e:
        logger.error(f"Errore durante la pulizia degli spazi nei percorsi: {str(e)}")

# Esegui il controllo all'avvio
with app.app_context():
    db.create_all()
    check_orphaned_jobs()  # Controllo iniziale all'avvio
    clean_path_whitespace()  # Pulizia spazi nei percorsi


@app.route("/")
def index():
    """Home page with options to create new jobs or run existing ones"""
    # Controlla e aggiorna eventuali job orfani prima di mostrare la pagina
    check_orphaned_jobs()
    active_jobs = rclone_handler.get_active_jobs()
    
    # Controllo aggiuntivo: verifica se esistono job in stato "running" nel DB 
    # che non compaiono nella lista degli active jobs
    running_jobs_count = 0
    try:
        with app.app_context():
            running_jobs = SyncJobHistory.query.filter_by(status="running").all()
            for job in running_jobs:
                # Se non è presente negli active jobs ma è segnato come running nel DB
                is_active = False
                for active_job in active_jobs:
                    if active_job.get("source") == job.source and active_job.get("target") == job.target:
                        is_active = True
                        break
                
                if not is_active:
                    # Il job non è attivo ma è segnato come running: verifica se il lock file esiste
                    tag = rclone_handler._generate_tag(job.source, job.target)
                    lock_file = f"{LOG_DIR}/sync_{tag}.lock"
                    if not os.path.exists(lock_file):
                        # Verifica se il job ha prodotto errori dal log file
                        if job.log_file and os.path.exists(job.log_file):
                            try:
                                with open(job.log_file, 'r') as f:
                                    log_content = f.read()
                                    # Cerca indicazioni di errore nel log
                                    # Controlliamo i messaggi di errore in diversi formati comuni
                                    # Utilizziamo gli stessi criteri più restrittivi
                                    if (
                                        (" ERROR " in log_content.upper() or " ERROR:" in log_content.upper()) or 
                                        (" FATAL " in log_content.upper() or " FATAL:" in log_content.upper()) or
                                        "NOTICE: Failed" in log_content or
                                        ("Errors:" in log_content and "0)" not in log_content.split("Errors:")[1].split("\n")[0])
                                    ):
                                        # Escludiamo il caso "nothing to transfer"
                                        if "There was nothing to transfer" in log_content:
                                            job.status = "completed"
                                            logger.info(f"Ghost job {job.id} marked as completed (nothing to transfer)")
                                        else:
                                            job.status = "error"
                                            logger.info(f"Ghost job {job.id} marked as error based on log content")
                                    else:
                                        job.status = "completed"
                                        logger.info(f"Ghost job {job.id} marked as completed")
                            except Exception as e:
                                logger.error(f"Error reading log file for ghost job {job.id}: {str(e)}")
                                # In caso di errore nella lettura del log, assumiamo completato con errore
                                job.status = "error"
                        else:
                            # Se non abbiamo log file, controlliamo se il job ha un exit_code
                            if job.exit_code is not None and job.exit_code != 0:
                                job.status = "error"
                                logger.info(f"Ghost job {job.id} marked as error based on exit code {job.exit_code}")
                            else:
                                job.status = "completed"
                                logger.info(f"Ghost job {job.id} marked as completed (no log file)")
                        
                        job.end_time = datetime.now() if not job.end_time else job.end_time
                        db.session.commit()
                        logger.info(f"Auto-fixed ghost job: {job.id} {job.source} → {job.target}")
                        running_jobs_count += 1
    except Exception as e:
        logger.error(f"Error checking ghost jobs: {str(e)}")
    
    if running_jobs_count > 0:
        flash(f"Aggiornati {running_jobs_count} job fantasma che risultavano in esecuzione ma erano terminati", "info")
    
    return render_template("index.html", active_jobs=active_jobs, rclone_handler=rclone_handler)


@app.route("/jobs")
def jobs():
    """Page for creating new sync jobs and viewing/running configured jobs"""
    # Aggiorna lo stato dei job pendenti
    check_orphaned_jobs()
    configured_jobs = rclone_handler.get_configured_jobs()
    return render_template("jobs.html", configured_jobs=configured_jobs)


@app.route("/run_job", methods=["POST"])
def run_job():
    """Run a configured job"""
    job_id = request.form.get("job_id")
    dry_run = request.form.get("dry_run") == "on"
    
    if not job_id:
        flash("No job selected", "danger")
        return redirect(url_for("jobs"))
    
    try:
        job = rclone_handler.run_configured_job(job_id, dry_run)
        
        # Create history entry
        with app.app_context():
            history = SyncJobHistory(
                source=job.get("source"),
                target=job.get("target"),
                status="running",
                dry_run=dry_run,
                start_time=datetime.now(),
                log_file=job.get("log_file")
            )
            db.session.add(history)
            db.session.commit()
            
            # Notifica l'avvio del job
            notify_job_started(history.id, job.get("source"), job.get("target"), is_scheduled=False, dry_run=dry_run)
            
        flash(f"Job started successfully: {job_id}", "success")
    except Exception as e:
        logger.error(f"Error running job: {str(e)}")
        flash(f"Error running job: {str(e)}", "danger")
    
    return redirect(url_for("jobs"))


@app.route("/create_job", methods=["POST"])
def create_job():
    """Create and run a new sync job"""
    source = request.form.get("source")
    target = request.form.get("target")
    dry_run = request.form.get("dry_run") == "on"
    
    if not source or not target:
        flash("Source and target are required", "danger")
        return redirect(url_for("jobs"))
    
    try:
        job = rclone_handler.run_custom_job(source, target, dry_run)
        
        # Create history entry
        with app.app_context():
            history = SyncJobHistory(
                source=source,
                target=target,
                status="running",
                dry_run=dry_run,
                start_time=datetime.now(),
                log_file=job.get("log_file")
            )
            db.session.add(history)
            db.session.commit()
            
            # Notifica l'avvio del job
            notify_job_started(history.id, source, target, is_scheduled=False, dry_run=dry_run)
            
        flash("Job started successfully", "success")
    except Exception as e:
        logger.error(f"Error creating job: {str(e)}")
        flash(f"Error creating job: {str(e)}", "danger")
    
    return redirect(url_for("jobs"))


@app.route("/history")
def history():
    """View history of executed jobs with filtering and pagination"""
    # Controlla e aggiorna eventuali job orfani
    check_orphaned_jobs()
    
    # Parametri di filtro
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    id_filter = request.args.get('id', '')
    source_filter = request.args.get('source', '')
    target_filter = request.args.get('target', '')
    status_filter = request.args.get('status', '')
    mode_filter = request.args.get('mode', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Costruzione della query con filtri
    query = SyncJobHistory.query
    
    if id_filter:
        query = query.filter(SyncJobHistory.id == id_filter)
    if source_filter:
        query = query.filter(SyncJobHistory.source.ilike(f'%{source_filter}%'))
    if target_filter:
        query = query.filter(SyncJobHistory.target.ilike(f'%{target_filter}%'))
    if status_filter:
        query = query.filter(SyncJobHistory.status == status_filter)
    if mode_filter:
        if mode_filter.lower() == 'dry':
            query = query.filter(SyncJobHistory.dry_run == True)
        elif mode_filter.lower() == 'live':
            query = query.filter(SyncJobHistory.dry_run == False)
    
    # Filtro per data
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(SyncJobHistory.start_time >= date_from_obj)
        except ValueError:
            # Ignora se il formato della data non è valido
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            # Aggiunge un giorno per inclusività
            date_to_obj = date_to_obj + timedelta(days=1)
            query = query.filter(SyncJobHistory.start_time <= date_to_obj)
        except ValueError:
            # Ignora se il formato della data non è valido
            pass
    
    # Ordinamento e paginazione
    paginated_history = query.order_by(SyncJobHistory.start_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Opzioni per i filtri dropdown
    status_options = ['running', 'completed', 'error', 'pending']
    mode_options = ['dry', 'live']
    
    return render_template(
        "history.html", 
        paginated_history=paginated_history,
        job_history=paginated_history.items,
        status_options=status_options,
        mode_options=mode_options,
        filters={
            'id': id_filter,
            'source': source_filter,
            'target': target_filter,
            'status': status_filter,
            'mode': mode_filter,
            'date_from': date_from,
            'date_to': date_to,
            'page': page,
            'per_page': per_page
        }
    )


@app.route("/job_log/<int:job_id>")
def job_log(job_id):
    """View log for a specific job (JSON endpoint)"""
    job = SyncJobHistory.query.get_or_404(job_id)
    
    log_content = "Log file not found or empty."
    
    if job.log_file and os.path.exists(job.log_file):
        try:
            with open(job.log_file, 'r') as f:
                log_content = f.read()
        except Exception as e:
            logger.error(f"Error reading log file: {str(e)}")
            log_content = f"Error reading log file: {str(e)}"
    
    return jsonify({"log": log_content})


@app.route("/view_log/<int:job_id>")
def view_log(job_id):
    """View log file for a specific job with search capability"""
    job = SyncJobHistory.query.get_or_404(job_id)
    
    log_content = "Log file not found or empty."
    log_filename = "N/A"
    
    if job.log_file and os.path.exists(job.log_file):
        try:
            with open(job.log_file, 'r') as f:
                log_content = f.read()
            log_filename = os.path.basename(job.log_file)
        except Exception as e:
            logger.error(f"Error reading log file: {str(e)}")
            log_content = f"Error reading log file: {str(e)}"
    
    # Per evitare l'errore con job.duration_formatted che viene trattato come callable
    # ma è una proprietà, creiamo una versione stringa esplicita
    if hasattr(job, 'duration_formatted'):
        if callable(job.duration_formatted):
            job.duration_formatted_str = job.duration_formatted()
        else:
            job.duration_formatted_str = job.duration_formatted
    else:
        job.duration_formatted_str = "N/A"
        
    return render_template('view_log.html', 
                           job=job, 
                           job_id=job_id, 
                           log_content=log_content, 
                           log_filename=log_filename)


@app.route("/logs/<path:filename>")
def log_file(filename):
    """Serve log files from the log directory"""
    return send_from_directory(LOG_DIR, filename)


@app.route("/api/active_jobs")
def api_active_jobs():
    """Restituisce i job attivi in formato JSON per aggiornamenti AJAX"""
    # Controlla e aggiorna eventuali job orfani prima di restituire i dati
    check_orphaned_jobs()
    active_jobs = rclone_handler.get_active_jobs()
    
    # Formatta i dati per il client
    formatted_jobs = []
    for job in active_jobs:
        formatted_job = {
            'source': job.get('source'),
            'target': job.get('target'),
            'start_time': job.get('start_time').strftime('%Y-%m-%d %H:%M:%S'),
            'duration': job.get('duration'),
            'duration_formatted': format_duration(job.get('duration')),
            'dry_run': job.get('dry_run'),
            'log_file': job.get('log_file'),
            'from_scheduler': job.get('from_scheduler', False)
        }
        formatted_jobs.append(formatted_job)
    
    return jsonify({
        "active_jobs": formatted_jobs,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


def format_duration(seconds):
    """Formatta una durata in secondi in un formato leggibile"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


@app.route("/job_status/<int:job_id>")
def job_status(job_id):
    """Get the status of a specific job"""
    job = SyncJobHistory.query.get_or_404(job_id)
    
    # Check if job is still running
    if job.status == "running":
        if rclone_handler.is_job_running(job.source, job.target):
            status = "running"
        else:
            # Job finished, check log for errors
            if job.log_file and os.path.exists(job.log_file):
                try:
                    with open(job.log_file, 'r') as f:
                        log_content = f.read()
                        # Check for error indicators
                        if "ERROR" in log_content.upper() or "FATAL" in log_content.upper():
                            status = "error"
                            job.status = status
                            logger.info(f"Job {job.id} marked as error")
                            
                            # Invia notifica di completamento con errore
                            notify_job_completed(job.id, job.source, job.target, success=False, duration=job.duration)
                        else:
                            status = "completed"
                            job.status = status
                            logger.info(f"Job {job.id} marked as completed")
                            
                            # Invia notifica di completamento con successo
                            notify_job_completed(job.id, job.source, job.target, success=True, duration=job.duration)
                except Exception as e:
                    logger.error(f"Error reading log file: {str(e)}")
                    status = "error"
                    job.status = status
            else:
                status = "completed"
                job.status = status
                
            job.end_time = datetime.now()
            db.session.commit()
    else:
        status = job.status
    
    # Restituisci anche la durata aggiornata e altre informazioni utili
    return jsonify({
        "status": status,
        "duration": job.duration_formatted(),
        "end_time": job.end_time.strftime('%Y-%m-%d %H:%M:%S') if job.end_time else None
    })


@app.route("/force_cleanup", methods=["POST"])
@app.route("/clean_all_jobs")
def clean_all_jobs():
    """Force cleanup all running jobs"""
    # Controlla se c'è un parametro che indica di pulire anche i percorsi
    clean_paths_too = request.args.get("clean_paths") == "1"
    
    try:
        cleaned_count = force_cleanup_jobs()
        
        if clean_paths_too:
            # Esegui la pulizia degli spazi nei percorsi
            try:
                clean_path_whitespace()
                flash("Pulizia dei percorsi completata. Gli spazi extra sono stati rimossi.", "success")
            except Exception as e:
                logger.error(f"Errore durante la pulizia dei percorsi: {str(e)}")
                flash(f"Errore durante la pulizia dei percorsi: {str(e)}", "danger")
        
        if cleaned_count > 0:
            flash(f"Puliti {cleaned_count} job bloccati", "success")
        elif not clean_paths_too:  # Non mostrare questo messaggio se abbiamo già mostrato quello della pulizia percorsi
            flash("Nessun job bloccato trovato", "info")
    except Exception as e:
        logger.error(f"Errore durante la pulizia dei job: {str(e)}")
        flash(f"Errore durante la pulizia dei job: {str(e)}", "danger")
    
    return redirect(url_for("index"))

@app.route("/cancel_job/<int:job_id>", methods=["POST"])
def cancel_job(job_id):
    """Cancel a specific running job"""
    try:
        with app.app_context():
            # Gestione caso speciale per job dalla dashboard
            source = request.form.get("source")
            target = request.form.get("target")
            
            # Se abbiamo source e target ma non un job ID valido, troviamo il job corrispondente
            if job_id < 0 and source and target:
                jobs = SyncJobHistory.query.filter_by(
                    source=source, 
                    target=target,
                    status="running"
                ).order_by(SyncJobHistory.id.desc()).all()
                
                if jobs:
                    job = jobs[0]  # Prendiamo il job più recente con quel source/target
                    job_id = job.id
                    logger.info(f"Found job {job_id} for source={source}, target={target}")
                else:
                    flash(f"No running job found for {source} → {target}", "warning")
                    return redirect(request.referrer or url_for("index"))
            else:
                # Ottieni il job con l'ID specificato
                job = SyncJobHistory.query.get_or_404(job_id)
            
            if job.status != "running":
                flash(f"Job {job_id} is not running", "warning")
                return redirect(request.referrer or url_for("history"))
            
            # Remove any lock files
            tag = f"{job.source.replace(':', '_').replace('/', '_')}__TO__{job.target.replace(':', '_').replace('/', '_')}"
            lock_file = f"{LOG_DIR}/sync_{tag}.lock"
            
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    logger.info(f"Removed lock file for job {job_id}: {lock_file}")
                except Exception as e:
                    logger.error(f"Error removing lock file: {str(e)}")
            
            # Update job status
            job.status = "cancelled"
            job.end_time = datetime.now()
            db.session.commit()
            
            # Also check if the job is in active_jobs and try to terminate it
            job_key = f"{job.source}|{job.target}"
            if job_key in rclone_handler.active_jobs:
                try:
                    process = rclone_handler.active_jobs[job_key]['process']
                    if process.poll() is None:  # Process is still running
                        process.terminate()
                        logger.info(f"Process for job {job_id} terminated")
                except Exception as e:
                    logger.error(f"Error terminating process: {str(e)}")
            
            flash(f"Job {job_id} cancelled", "success")
        
    except Exception as e:
        logger.error(f"Error cancelling job: {str(e)}")
        flash(f"Error cancelling job: {str(e)}", "danger")
    
    return redirect(request.referrer or url_for("history"))


@app.route("/config")
def config():
    """View and edit rclone configuration"""
    config_content = rclone_handler.read_config_file()
    main_config_content = rclone_handler.read_main_config_file()
    return render_template("config.html", 
                          config_content=config_content,
                          main_config_content=main_config_content)


@app.route("/save_config", methods=["POST"])
def save_config():
    """Save changes to rclone configuration"""
    config_content = request.form.get("config_content")
    
    if not config_content:
        flash("No configuration provided", "danger")
        return redirect(url_for("config"))
    
    try:
        rclone_handler.save_config_file(config_content)
        flash("Configuration saved successfully", "success")
    except Exception as e:
        logger.error(f"Error saving configuration: {str(e)}")
        flash(f"Error saving configuration: {str(e)}", "danger")
    
    return redirect(url_for("config"))


@app.route("/save_main_config", methods=["POST"])
def save_main_config():
    """Save changes to main rclone configuration file"""
    config_content = request.form.get("main_config_content")
    
    if not config_content:
        flash("No configuration provided", "danger")
        return redirect(url_for("config"))
    
    try:
        rclone_handler.save_main_config_file(config_content)
        flash("Main configuration file saved successfully", "success")
    except Exception as e:
        logger.error(f"Error saving main configuration: {str(e)}")
        flash(f"Error saving main configuration: {str(e)}", "danger")
    
    return redirect(url_for("config"))


# Routes per la gestione della pianificazione

@app.route("/schedule")
def schedule():
    """View and manage scheduled jobs"""
    scheduled_jobs = job_scheduler.get_schedule_summary()
    return render_template("schedule.html", scheduled_jobs=scheduled_jobs)


@app.route("/create_scheduled_job", methods=["POST"])
def create_scheduled_job():
    """Create a new scheduled job"""
    name = request.form.get("name")
    source = request.form.get("source", "").strip()
    target = request.form.get("target", "").strip()
    cron_expression = request.form.get("cron_expression")
    enabled = request.form.get("enabled") == "1"
    retry_on_error = request.form.get("retry_on_error") == "1"
    max_retries = int(request.form.get("max_retries", "0"))
    
    if not name or not source or not target or not cron_expression:
        flash("Tutti i campi sono obbligatori", "danger")
        return redirect(url_for("schedule"))
    
    try:
        # Valida l'espressione cron
        from crontab import CronTab
        try:
            cron = CronTab(cron_expression)
            _ = cron.next(default_utc=False)  # Verifica la validità calcolando la prossima esecuzione
        except Exception as e:
            flash(f"Espressione cron non valida: {str(e)}", "danger")
            return redirect(url_for("schedule"))
        
        # Crea il job pianificato
        with app.app_context():
            scheduled_job = ScheduledJob(
                name=name,
                source=source,
                target=target,
                cron_expression=cron_expression,
                enabled=enabled,
                retry_on_error=retry_on_error,
                max_retries=max_retries
            )
            db.session.add(scheduled_job)
            db.session.commit()
            
            # Calcola il prossimo orario di esecuzione
            next_run = job_scheduler._calculate_next_run(cron_expression)
            scheduled_job.next_run = next_run
            db.session.commit()
            
            flash(f"Job pianificato creato con successo. Prossima esecuzione: {next_run}", "success")
    except Exception as e:
        logger.error(f"Error creating scheduled job: {str(e)}")
        flash(f"Error creating scheduled job: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))


@app.route("/edit_scheduled_job/<int:job_id>")
def edit_scheduled_job(job_id):
    """Edit a scheduled job"""
    job = ScheduledJob.query.get_or_404(job_id)
    return render_template("edit_schedule.html", job=job)


@app.route("/update_scheduled_job/<int:job_id>", methods=["POST"])
def update_scheduled_job(job_id):
    """Update a scheduled job"""
    job = ScheduledJob.query.get_or_404(job_id)
    
    name = request.form.get("name")
    source = request.form.get("source", "").strip()
    target = request.form.get("target", "").strip()
    cron_expression = request.form.get("cron_expression")
    enabled = request.form.get("enabled") == "1"
    retry_on_error = request.form.get("retry_on_error") == "1"
    max_retries = int(request.form.get("max_retries", "0"))
    
    if not name or not source or not target or not cron_expression:
        flash("Tutti i campi sono obbligatori", "danger")
        return redirect(url_for("edit_scheduled_job", job_id=job_id))
    
    try:
        # Valida l'espressione cron
        from crontab import CronTab
        try:
            cron = CronTab(cron_expression)
            _ = cron.next(default_utc=False)  # Verifica la validità calcolando la prossima esecuzione
        except Exception as e:
            flash(f"Espressione cron non valida: {str(e)}", "danger")
            return redirect(url_for("edit_scheduled_job", job_id=job_id))
        
        # Aggiorna il job
        job.name = name
        job.source = source
        job.target = target
        job.cron_expression = cron_expression
        job.enabled = enabled
        job.retry_on_error = retry_on_error
        job.max_retries = max_retries
        
        # Ricalcola il prossimo orario di esecuzione
        job.next_run = job_scheduler._calculate_next_run(cron_expression)
        
        db.session.commit()
        
        flash("Job pianificato aggiornato con successo", "success")
    except Exception as e:
        logger.error(f"Error updating scheduled job: {str(e)}")
        flash(f"Error updating scheduled job: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))


@app.route("/toggle_scheduled_job/<int:job_id>", methods=["POST"])
def toggle_scheduled_job(job_id):
    """Toggle enabled status for a scheduled job"""
    job = ScheduledJob.query.get_or_404(job_id)
    
    try:
        # Toggle status
        job.enabled = not job.enabled
        
        # Se è stato attivato, calcola il prossimo orario di esecuzione
        if job.enabled:
            job.next_run = job_scheduler._calculate_next_run(job.cron_expression)
        else:
            job.next_run = None
        
        db.session.commit()
        
        if job.enabled:
            flash(f"Job pianificato '{job.name}' attivato", "success")
        else:
            flash(f"Job pianificato '{job.name}' disattivato", "info")
    except Exception as e:
        logger.error(f"Error toggling scheduled job: {str(e)}")
        flash(f"Error: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))


@app.route("/delete_scheduled_job/<int:job_id>", methods=["POST"])
def delete_scheduled_job(job_id):
    """Delete a scheduled job"""
    job = ScheduledJob.query.get_or_404(job_id)
    
    try:
        name = job.name
        db.session.delete(job)
        db.session.commit()
        flash(f"Job pianificato '{name}' eliminato", "success")
    except Exception as e:
        logger.error(f"Error deleting scheduled job: {str(e)}")
        flash(f"Error deleting scheduled job: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))


@app.route("/run_scheduled_job_now/<int:job_id>", methods=["POST"])
def run_scheduled_job_now(job_id):
    """Run a scheduled job immediately"""
    job = ScheduledJob.query.get_or_404(job_id)
    
    try:
        # Rimuovo eventuali spazi extra alla fine dei percorsi
        source = job.source.strip()
        target = job.target.strip()
        
        # Check if source/target already has a running job
        if rclone_handler.is_job_running(source, target):
            flash(f"Impossibile avviare il job: {source} → {target} ha già un job in esecuzione", "warning")
            return redirect(url_for("schedule"))
        
        # Run the job
        job_info = rclone_handler.run_custom_job(source, target, dry_run=False)
        
        # Create history entry
        history = SyncJobHistory(
            source=source,  # Usiamo i valori puliti
            target=target,  # Usiamo i valori puliti
            status="running",
            dry_run=False,
            start_time=datetime.now(),
            log_file=job_info.get("log_file")
        )
        db.session.add(history)
        
        # Update last run time
        job.last_run = datetime.now()
        db.session.commit()
        
        # Crea notifica per l'avvio del job
        notify_job_started(history.id, source, target, is_scheduled=True, dry_run=False)
        
        flash(f"Job pianificato '{job.name}' avviato manualmente", "success")
    except Exception as e:
        logger.error(f"Error running scheduled job now: {str(e)}")
        flash(f"Error running job: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))


# API per notifiche
@app.route("/api/notifications")
def api_notifications():
    """Get recent notifications"""
    limit = request.args.get('limit', 10, type=int)
    include_read = request.args.get('include_read', 'false').lower() == 'true'
    
    notifications = get_notifications(limit=limit, include_read=include_read)
    
    # Includi anche lo stato corrente delle impostazioni
    settings = get_user_settings()
    
    return jsonify({
        "notifications": notifications,
        "settings": {
            "notifications_enabled": settings.notifications_enabled
        },
        "unread_count": Notification.query.filter_by(read=False).count()
    })


@app.route("/api/notifications/mark-read/<int:notification_id>", methods=["POST"])
def api_mark_notification_read(notification_id):
    """Mark a notification as read"""
    success = mark_notification_read(notification_id)
    return jsonify({"success": success})


@app.route("/api/notifications/mark-all-read", methods=["POST"])
def api_mark_all_read():
    """Mark all notifications as read"""
    count = mark_all_read()
    return jsonify({"success": True, "count": count})


@app.route("/settings", methods=["GET", "POST"])
def user_settings():
    """View and update user settings"""
    settings = get_user_settings()
    
    if request.method == "POST":
        notifications_enabled = request.form.get("notifications_enabled") == "on"
        
        # Salva le impostazioni aggiornate
        update_settings(notifications_enabled=notifications_enabled)
        flash("Impostazioni aggiornate con successo", "success")
    
    return render_template("settings.html", settings=settings)


@app.route("/clean_paths")
def clean_paths():
    """Pulisci gli spazi nei percorsi del database"""
    try:
        # Esegui la funzione di pulizia
        clean_path_whitespace()
        flash("Pulizia dei percorsi completata. Gli spazi extra sono stati rimossi.", "success")
    except Exception as e:
        logger.error(f"Errore durante la pulizia dei percorsi: {str(e)}")
        flash(f"Errore durante la pulizia dei percorsi: {str(e)}", "danger")
    
    return redirect(url_for('index'))


@app.route("/search_logs")
def search_logs():
    """Search in log files"""
    import re
    import os
    import glob
    from datetime import datetime
    
    # Recupera parametri dalla request
    search_text = request.args.get('search_text', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    context_lines = int(request.args.get('context_lines', 5))
    max_results = int(request.args.get('max_results', 1000))
    case_sensitive = request.args.get('case_sensitive') == 'on'
    
    # Flag per indicare se è stata effettuata una ricerca
    searched = bool(search_text or date_from or date_to)
    
    # Preparazione dei filtri
    filters = {
        'search_text': search_text,
        'date_from': date_from,
        'date_to': date_to,
        'context_lines': context_lines,
        'max_results': max_results,
        'case_sensitive': case_sensitive
    }
    
    results = []
    
    # Se almeno un filtro è attivo, procedi con la ricerca
    if searched and (search_text or date_from or date_to):
        try:
            # Converte le date in oggetti datetime
            date_from_obj = None
            date_to_obj = None
            
            if date_from:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            
            if date_to:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
                # Aggiungi un giorno per inclusività
                date_to_obj = date_to_obj + timedelta(days=1)
            
            # Ottieni la lista di tutti i file di log
            log_files = []
            for job in SyncJobHistory.query.all():
                if job.log_file and os.path.exists(job.log_file):
                    # Estrai la data dal file
                    try:
                        file_date = job.start_time
                        
                        # Filtra per data se specificata
                        if date_from_obj and file_date < date_from_obj:
                            continue
                        if date_to_obj and file_date > date_to_obj:
                            continue
                        
                        log_files.append((job.id, job.log_file, file_date))
                    except Exception as e:
                        logger.error(f"Error parsing log file date: {str(e)}")
            
            # Prepara la regex per la ricerca
            if search_text:
                flags = 0 if case_sensitive else re.IGNORECASE
                search_pattern = re.compile(re.escape(search_text), flags)
            
            # Cerca in ogni file di log
            result_count = 0
            for job_id, log_file, file_date in log_files:
                if result_count >= max_results:
                    break
                
                try:
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                    
                    # Se non c'è testo da cercare, mostra l'intero file
                    if not search_text:
                        # Limita le linee mostrate per file
                        content = ''.join(lines[:100])
                        if len(lines) > 100:
                            content += '\n... (truncated, too many lines) ...'
                        
                        results.append({
                            'job_id': job_id,
                            'filename': os.path.basename(log_file),
                            'date': file_date.strftime('%Y-%m-%d %H:%M:%S'),
                            'content': content
                        })
                        
                        result_count += 1
                        continue
                    
                    # Cerca il testo nel file
                    for i, line in enumerate(lines):
                        if search_pattern.search(line):
                            # Calcola l'intervallo di linee da mostrare
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            
                            # Estrai le linee con contesto
                            content_lines = lines[start:end]
                            
                            # Evidenzia il testo cercato
                            highlighted_content = []
                            for j, content_line in enumerate(content_lines):
                                line_num = start + j
                                # Aggiungi numeri di riga
                                prefix = f"{line_num + 1:4d} | "
                                
                                # Evidenzia la linea corrente
                                if line_num == i:
                                    # Evidenzia il testo cercato
                                    if case_sensitive:
                                        highlighted_line = content_line.replace(search_text, 
                                                                           f'<mark class="bg-warning text-dark">{search_text}</mark>')
                                    else:
                                        # Per case insensitive, dobbiamo usare regex
                                        highlighted_line = re.sub(f'({re.escape(search_text)})', 
                                                             r'<mark class="bg-warning text-dark">\1</mark>', 
                                                             content_line, 
                                                             flags=re.IGNORECASE)
                                    
                                    highlighted_content.append(f"<strong>{prefix}{highlighted_line}</strong>")
                                else:
                                    highlighted_content.append(f"{prefix}{content_line}")
                            
                            content = ''.join(highlighted_content)
                            
                            results.append({
                                'job_id': job_id,
                                'filename': os.path.basename(log_file),
                                'date': file_date.strftime('%Y-%m-%d %H:%M:%S'),
                                'content': content
                            })
                            
                            result_count += 1
                            
                            # Limita il numero di risultati per lo stesso file
                            if result_count >= max_results:
                                break
                
                except Exception as e:
                    logger.error(f"Error searching log file {log_file}: {str(e)}")
                    continue
        
        except Exception as e:
            logger.error(f"Error in search_logs: {str(e)}")
            flash(f"Si è verificato un errore durante la ricerca: {str(e)}", "danger")
    
    return render_template(
        "search_logs.html", 
        filters=filters,
        results=results,
        searched=searched
    )


@app.route("/backup")
def backup():
    """View and manage database backups"""
    # Ottieni la lista dei backup
    backups = list_backups(app)
    
    # Ottieni le impostazioni di backup automatico
    user_settings = get_user_settings()
    settings = user_settings.settings
    
    auto_backup_enabled = settings.get('auto_backup_enabled', False)
    auto_backup_interval = settings.get('auto_backup_interval', 24)
    auto_backup_keep = settings.get('auto_backup_keep', 5)
    
    return render_template(
        "backup.html",
        backups=backups,
        auto_backup_enabled=auto_backup_enabled,
        auto_backup_interval=auto_backup_interval,
        auto_backup_keep=auto_backup_keep
    )


@app.route("/create_backup", methods=["POST"])
def create_backup():
    """Create a new database backup"""
    backup_name = request.form.get("backup_name", "").strip()
    
    try:
        # Crea il backup
        backup_info = create_backup_func(app, backup_name if backup_name else None)
        flash(f"Backup creato con successo: {backup_info['name']}", "success")
        add_notification("Backup creato", f"Backup del database creato con successo: {backup_info['name']}", "success")
    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        flash(f"Errore durante la creazione del backup: {str(e)}", "danger")
        add_notification("Errore backup", f"Errore durante la creazione del backup: {str(e)}", "error")
    
    return redirect(url_for("backup"))


@app.route("/restore_backup", methods=["POST"])
def restore_backup_route():
    """Restore a database backup"""
    backup_name = request.form.get("backup_name")
    
    if not backup_name:
        flash("Nome del backup non specificato", "danger")
        return redirect(url_for("backup"))
    
    try:
        # Ripristina il backup
        if restore_backup(app, backup_name):
            flash(f"Backup ripristinato con successo: {backup_name}", "success")
            add_notification("Backup ripristinato", f"Backup del database ripristinato con successo: {backup_name}", "success")
        else:
            flash(f"Errore durante il ripristino del backup: {backup_name}", "danger")
            add_notification("Errore ripristino", f"Errore durante il ripristino del backup: {backup_name}", "error")
    except Exception as e:
        logger.error(f"Error restoring backup: {str(e)}")
        flash(f"Errore durante il ripristino del backup: {str(e)}", "danger")
        add_notification("Errore ripristino", f"Errore durante il ripristino del backup: {str(e)}", "error")
    
    return redirect(url_for("backup"))


@app.route("/delete_backup", methods=["POST"])
def delete_backup_route():
    """Delete a database backup"""
    backup_name = request.form.get("backup_name")
    
    if not backup_name:
        flash("Nome del backup non specificato", "danger")
        return redirect(url_for("backup"))
    
    try:
        # Elimina il backup
        if delete_backup(app, backup_name):
            flash(f"Backup eliminato con successo: {backup_name}", "success")
        else:
            flash(f"Errore durante l'eliminazione del backup: {backup_name}", "danger")
    except Exception as e:
        logger.error(f"Error deleting backup: {str(e)}")
        flash(f"Errore durante l'eliminazione del backup: {str(e)}", "danger")
    
    return redirect(url_for("backup"))


@app.route("/backup_settings", methods=["POST"])
def backup_settings():
    """Save backup settings"""
    auto_backup_enabled = request.form.get("auto_backup_enabled") == "on"
    
    try:
        auto_backup_interval = int(request.form.get("auto_backup_interval", "24"))
        auto_backup_keep = int(request.form.get("auto_backup_keep", "5"))
    except ValueError:
        flash("Valori numerici non validi per intervallo o numero di backup", "danger")
        return redirect(url_for("backup"))
    
    # Valida i valori
    if auto_backup_interval < 1 or auto_backup_interval > 168:
        auto_backup_interval = 24
    
    if auto_backup_keep < 1 or auto_backup_keep > 50:
        auto_backup_keep = 5
    
    # Salva le impostazioni
    settings = {
        'auto_backup_enabled': auto_backup_enabled,
        'auto_backup_interval': auto_backup_interval,
        'auto_backup_keep': auto_backup_keep
    }
    
    user_settings = update_settings(other_settings=settings)
    
    # Configura il backup automatico se abilitato
    if auto_backup_enabled:
        # Avvia il thread di backup automatico
        setup_auto_backup(app, auto_backup_interval)
        flash(f"Backup automatico configurato ogni {auto_backup_interval} ore", "success")
    
    flash("Impostazioni di backup salvate con successo", "success")
    return redirect(url_for("backup"))


@app.route("/download_backup", methods=["POST"])
def download_backup():
    """Download a backup file"""
    backup_name = request.form.get("backup_name")
    
    if not backup_name:
        flash("Nome del backup non specificato", "danger")
        return redirect(url_for("backup"))
    
    try:
        # Trova il backup
        backups = list_backups(app)
        backup_info = None
        
        for backup in backups:
            if backup['name'] == backup_name:
                backup_info = backup
                break
        
        if not backup_info:
            flash(f"Backup non trovato: {backup_name}", "danger")
            return redirect(url_for("backup"))
        
        # Ottieni il percorso del file di database
        db_path = backup_info.get('database')
        
        if not db_path or not os.path.exists(db_path):
            flash("File di backup non trovato", "danger")
            return redirect(url_for("backup"))
        
        # Invia il file come attachment
        return send_from_directory(
            os.path.dirname(db_path),
            os.path.basename(db_path),
            as_attachment=True,
            download_name=f"rclone_manager_backup_{backup_name}.db"
        )
    
    except Exception as e:
        logger.error(f"Error downloading backup: {str(e)}")
        flash(f"Errore durante il download del backup: {str(e)}", "danger")
        return redirect(url_for("backup"))


@app.route("/upload_backup", methods=["POST"])
def upload_backup():
    """Upload a backup file"""
    if 'backup_file' not in request.files:
        flash("Nessun file selezionato", "danger")
        return redirect(url_for("backup"))
    
    backup_file = request.files['backup_file']
    
    if backup_file.filename == '':
        flash("Nessun file selezionato", "danger")
        return redirect(url_for("backup"))
    
    try:
        # Crea una directory temporanea per il backup caricato
        backup_dir = get_backup_dir(app)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"uploaded_backup_{timestamp}"
        backup_path = os.path.join(backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)
        
        # Salva il file caricato
        db_filename = os.path.basename(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        db_backup_path = os.path.join(backup_path, db_filename)
        backup_file.save(db_backup_path)
        
        # Crea il file di metadata
        backup_info = {
            'timestamp': timestamp,
            'name': backup_name,
            'database': db_backup_path,
            'configs': {},
            'path': backup_path,
            'uploaded': True
        }
        
        # Salva il file di metadata
        with open(os.path.join(backup_path, 'backup_info.json'), 'w') as f:
            json.dump(backup_info, f, indent=2)
        
        flash(f"Backup caricato con successo: {backup_name}", "success")
        
    except Exception as e:
        logger.error(f"Error uploading backup: {str(e)}")
        flash(f"Errore durante il caricamento del backup: {str(e)}", "danger")
    
    return redirect(url_for("backup"))

