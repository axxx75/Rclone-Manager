"""
Notification manager module for handling browser notifications.
"""
import logging
from datetime import datetime
from models import db, Notification, UserSettings

logger = logging.getLogger(__name__)


def get_notifications(limit=10, include_read=False):
    """Get recent notifications
    
    Args:
        limit: Maximum number of notifications to return
        include_read: Whether to include already read notifications
    
    Returns:
        List of notifications as dictionaries
    """
    query = Notification.query
    
    if not include_read:
        query = query.filter_by(read=False)
    
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [n.to_dict() for n in notifications]


def mark_notification_read(notification_id):
    """Mark a notification as read
    
    Args:
        notification_id: ID of the notification to mark as read
    
    Returns:
        Boolean indicating success
    """
    try:
        notification = Notification.query.get(notification_id)
        if notification:
            notification.read = True
            db.session.commit()
            return True
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
    
    return False


def mark_all_read():
    """Mark all notifications as read
    
    Returns:
        Number of notifications marked as read
    """
    try:
        count = Notification.query.filter_by(read=False).update({"read": True})
        db.session.commit()
        return count
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {str(e)}")
        db.session.rollback()
        return 0


def add_notification(title, message, level="info"):
    """Add a new notification
    
    Args:
        title: Notification title
        message: Notification message
        level: Notification level (info, success, warning, error)
    
    Returns:
        The created notification or None if there was an error
    """
    try:
        # Check if notifications are enabled
        settings = get_user_settings()
        if not settings.notifications_enabled:
            logger.info("Notifications are disabled, skipping")
            return None
        
        notification = Notification(
            title=title,
            message=message,
            level=level,
            created_at=datetime.now()
        )
        db.session.add(notification)
        db.session.commit()
        
        return notification
    except Exception as e:
        logger.error(f"Error adding notification: {str(e)}")
        db.session.rollback()
        return None


def notify_job_started(job_id, source, target, is_scheduled=False, dry_run=False):
    """Send notification for job start
    
    Args:
        job_id: ID of the job
        source: Source path
        target: Target path
        is_scheduled: Whether the job was started by the scheduler
        dry_run: Whether the job is a dry run
    
    Returns:
        The created notification or None if there was an error
    """
    mode = "Dry Run" if dry_run else "Live"
    trigger = "schedulatore" if is_scheduled else "manualmente"
    
    title = f"Job {job_id} avviato"
    message = f"Il job di sincronizzazione da {source} a {target} è stato avviato {trigger} in modalità {mode}"
    
    return add_notification(title, message, level="info")


def notify_job_completed(job_id, source, target, success=True, duration=None):
    """Send notification for job completion
    
    Args:
        job_id: ID of the job
        source: Source path
        target: Target path
        success: Whether the job completed successfully
        duration: Duration of the job in seconds
    
    Returns:
        The created notification or None if there was an error
    """
    level = "success" if success else "error"
    status = "completato con successo" if success else "terminato con errori"
    
    title = f"Job {job_id} {status}"
    
    duration_text = ""
    if duration is not None:
        if duration < 60:
            duration_text = f" in {duration:.1f} secondi"
        elif duration < 3600:
            duration_text = f" in {duration/60:.1f} minuti"
        else:
            duration_text = f" in {duration/3600:.1f} ore"
    
    message = f"Il job di sincronizzazione da {source} a {target} è stato {status}{duration_text}"
    
    return add_notification(title, message, level=level)


def get_user_settings():
    """Get the user settings, creating if needed
    
    Returns:
        UserSettings object
    """
    # In a single-user system we just use ID 1
    settings = UserSettings.query.get(1)
    
    if not settings:
        # Create default settings
        settings = UserSettings(
            id=1,
            notifications_enabled=True,
            settings_json='{}'
        )
        db.session.add(settings)
        db.session.commit()
    
    return settings


def update_settings(notifications_enabled=None, other_settings=None):
    """Update user settings
    
    Args:
        notifications_enabled: Whether notifications are enabled
        other_settings: Dictionary of other settings to update
    
    Returns:
        Updated UserSettings object
    """
    settings = get_user_settings()
    
    if notifications_enabled is not None:
        settings.notifications_enabled = bool(notifications_enabled)
    
    if other_settings and isinstance(other_settings, dict):
        current = settings.settings
        current.update(other_settings)
        settings.settings = current
    
    db.session.commit()
    return settings