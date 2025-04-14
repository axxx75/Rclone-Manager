import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, send_from_directory
from models import db, SyncJob, SyncJobHistory, ScheduledJob
from utils.rclone_handler import RCloneHandler
from utils.scheduler import JobScheduler

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
                                if "ERROR" in log_content.upper() or "FATAL" in log_content.upper():
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
                    tag = f"{job.source.replace(':', '_').replace('/', '_')}__TO__{job.target.replace(':', '_').replace('/', '_')}"
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
                # Forza il reset dello stato
                job.status = "completed"
                job.end_time = datetime.now() if not job.end_time else job.end_time
                
                # Rimuovi i file di lock associati
                tag = f"{job.source.replace(':', '_').replace('/', '_')}__TO__{job.target.replace(':', '_').replace('/', '_')}"
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

# Esegui il controllo all'avvio
with app.app_context():
    db.create_all()
    check_orphaned_jobs()  # Controllo iniziale all'avvio
    
    # Avvia lo scheduler dei job
    job_scheduler.start()
    logger.info("Job scheduler started")


@app.route("/")
def index():
    """Home page with options to create new jobs or run existing ones"""
    active_jobs = rclone_handler.get_active_jobs()
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
            
        flash("Job started successfully", "success")
    except Exception as e:
        logger.error(f"Error creating job: {str(e)}")
        flash(f"Error creating job: {str(e)}", "danger")
    
    return redirect(url_for("jobs"))


@app.route("/history")
def history():
    """View history of executed jobs"""
    # Controlla e aggiorna eventuali job orfani
    check_orphaned_jobs()
    job_history = SyncJobHistory.query.order_by(SyncJobHistory.start_time.desc()).all()
    return render_template("history.html", job_history=job_history)


@app.route("/job_log/<int:job_id>")
def job_log(job_id):
    """View log for a specific job"""
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


@app.route("/logs/<path:filename>")
def log_file(filename):
    """Serve log files from the log directory"""
    return send_from_directory(LOG_DIR, filename)


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
                        else:
                            status = "completed"
                            job.status = status
                            logger.info(f"Job {job.id} marked as completed")
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
    
    return jsonify({"status": status})


@app.route("/force_cleanup", methods=["POST"])
def clean_all_jobs():
    """Force cleanup all running jobs"""
    cleaned_count = force_cleanup_jobs()
    flash(f"Forced cleanup of {cleaned_count} job(s)", "info")
    return redirect(url_for("history"))

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
    source = request.form.get("source")
    target = request.form.get("target")
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
    source = request.form.get("source")
    target = request.form.get("target")
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
        # Check if source/target already has a running job
        if rclone_handler.is_job_running(job.source, job.target):
            flash(f"Impossibile avviare il job: {job.source} → {job.target} ha già un job in esecuzione", "warning")
            return redirect(url_for("schedule"))
        
        # Run the job
        job_info = rclone_handler.run_custom_job(job.source, job.target, dry_run=False)
        
        # Create history entry
        history = SyncJobHistory(
            source=job.source,
            target=job.target,
            status="running",
            dry_run=False,
            start_time=datetime.now(),
            log_file=job_info.get("log_file")
        )
        db.session.add(history)
        
        # Update last run time
        job.last_run = datetime.now()
        db.session.commit()
        
        flash(f"Job pianificato '{job.name}' avviato manualmente", "success")
    except Exception as e:
        logger.error(f"Error running scheduled job now: {str(e)}")
        flash(f"Error running job: {str(e)}", "danger")
    
    return redirect(url_for("schedule"))
