import os
import logging
import time
from datetime import datetime, timedelta
from threading import Thread
from crontab import CronTab
from flask import current_app

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
        while self.running:
            try:
                if self.app:
                    app_context = self.app.app_context()
                else:
                    app_context = current_app.app_context()
                
                with app_context:
                    from app import db
                    from models import ScheduledJob, SyncJobHistory
                    
                    # Ottieni tutti i job abilitati
                    jobs = ScheduledJob.query.filter_by(enabled=True).all()
                    
                    current_time = datetime.now()
                    logger.debug(f"Checking {len(jobs)} scheduled jobs at {current_time}")
                    
                    for job in jobs:
                        # Se il job non ha un next_run, o il next_run è passato, calcola ed esegui
                        if job.next_run is None or job.next_run <= current_time:
                            logger.info(f"Scheduled job {job.id} ({job.name}) is due for execution")
                            
                            # Verifica se c'è già un job in esecuzione con gli stessi source/target
                            if self._check_if_running(job.source, job.target):
                                logger.warning(f"Skipping job {job.id}: source/target already has a running job")
                                # Calcola il prossimo orario di esecuzione ma non eseguire ora
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                                db.session.commit()
                                continue
                            
                            # Esegui il job
                            try:
                                job_info = self.rclone_handler.run_custom_job(job.source, job.target, dry_run=False)
                                
                                # Aggiorna il timestamp dell'ultimo avvio
                                job.last_run = current_time
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                                
                                # Crea entry nella history
                                history = SyncJobHistory(
                                    source=job.source,
                                    target=job.target,
                                    status="running",
                                    dry_run=False,
                                    start_time=current_time,
                                    log_file=job_info.get("log_file")
                                )
                                db.session.add(history)
                                
                                logger.info(f"Executed scheduled job {job.id} ({job.name}), next run at {job.next_run}")
                            except Exception as e:
                                logger.error(f"Error executing scheduled job {job.id}: {str(e)}")
                                # Aggiorna comunque i timestamp per ritentare alla prossima esecuzione
                                job.last_run = current_time
                                job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                            
                            db.session.commit()
                        else:
                            logger.debug(f"Job {job.id} next run at {job.next_run}")
                    
                    # Aggiorna i next_run per i job che non ne hanno uno
                    jobs_without_next_run = ScheduledJob.query.filter_by(next_run=None, enabled=True).all()
                    for job in jobs_without_next_run:
                        job.next_run = self._calculate_next_run(job.cron_expression, current_time)
                    
                    if jobs_without_next_run:
                        db.session.commit()
                        logger.info(f"Updated next_run for {len(jobs_without_next_run)} jobs")
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
            
            # Dormi per un minuto prima del prossimo controllo
            time.sleep(60)
    
    def _check_if_running(self, source, target):
        """Verifica se un job con lo stesso source e target è in esecuzione"""
        # Controlla tramite l'handler rclone
        if self.rclone_handler.is_job_running(source, target):
            return True
        
        # Controlla anche il file di lock
        tag = f"{source.replace(':', '_').replace('/', '_')}__TO__{target.replace(':', '_').replace('/', '_')}"
        lock_file = f"{self.log_dir}/sync_{tag}.lock"
        return os.path.exists(lock_file)
    
    def _calculate_next_run(self, cron_expression, from_time=None):
        """Calcola il prossimo orario di esecuzione da un'espressione cron"""
        if from_time is None:
            from_time = datetime.now()
        
        try:
            # Parse dell'espressione cron
            cron = CronTab(cron_expression)
            
            # Calcola i secondi fino alla prossima esecuzione
            delay = cron.next(default_utc=False)
            
            # Converte in datetime
            next_run = from_time + timedelta(seconds=delay)
            return next_run
        except Exception as e:
            logger.error(f"Error calculating next run time from '{cron_expression}': {str(e)}")
            # Se c'è un errore, ritorna 1 ora nel futuro come fallback
            return from_time + timedelta(hours=1)
    
    def get_schedule_summary(self):
        """Get summary of all scheduled jobs with next run times"""
        try:
            if self.app:
                app_context = self.app.app_context()
            else:
                app_context = current_app.app_context()
                
            with app_context:
                from models import ScheduledJob
                
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
