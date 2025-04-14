from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ScheduledJob(db.Model):
    """Model for scheduled sync jobs"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(255), nullable=False)
    target = db.Column(db.String(255), nullable=False)
    cron_expression = db.Column(db.String(100), nullable=False)  # Espressione cron (minuto, ora, giorno, mese, giorno settimana)
    enabled = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    retry_on_error = db.Column(db.Boolean, default=False)
    max_retries = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<ScheduledJob {self.name}>"


class SyncJob(db.Model):
    """Model for configured sync jobs"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(255), nullable=False)
    target = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime,
                           default=datetime.now,
                           onupdate=datetime.now)

    def __repr__(self):
        return f"<SyncJob {self.name}>"


class SyncJobHistory(db.Model):
    """Model for job execution history"""
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(255), nullable=False)
    target = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50),
                       default="pending")  # pending, running, completed, error
    dry_run = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, default=datetime.now)
    end_time = db.Column(db.DateTime, nullable=True)
    log_file = db.Column(db.String(255), nullable=True)
    exit_code = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f"<SyncJobHistory {self.id}>"

    @property
    def duration(self):
        """Calculate job duration"""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        elif self.start_time:
            return (datetime.now() - self.start_time).total_seconds()
        return 0

    @property
    def duration_formatted(self):
        """Format duration as human-readable string"""
        seconds = self.duration
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}m"
        else:
            return f"{seconds/3600:.1f}h"
