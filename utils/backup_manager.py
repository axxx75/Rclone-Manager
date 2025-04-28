"""
Database backup and restore utilities for RClone Manager.
"""

import os
import shutil
import logging
import sqlite3
import json
import time
from datetime import datetime
import glob
from threading import Thread

logger = logging.getLogger(__name__)

def get_db_path(app):
    """
    Get the path to the SQLite database file from Flask app configuration.
    
    Args:
        app: Flask application instance
        
    Returns:
        str: Path to the database file
    """
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    
    # Handle SQLite URI formats
    if db_uri.startswith('sqlite:///'):
        # Remove sqlite:/// prefix (standard format)
        db_path = db_uri[10:]
    elif db_uri.startswith('sqlite://'):
        # Absolute path format used by some drivers
        db_path = db_uri[9:]
    else:
        # For non-SQLite databases, return None
        return None
    
    # If the path is relative or points to instance folder already
    if not os.path.isabs(db_path) or '/instance/' in db_path or '\\instance\\' in db_path:
        # Extract just the filename if it's a path that includes instance/
        if '/instance/' in db_path:
            db_path = db_path.split('/instance/')[1]
        elif '\\instance\\' in db_path:
            db_path = db_path.split('\\instance\\')[1]
        
        # Use the file name in the instance path
        db_path = os.path.join(app.instance_path, os.path.basename(db_path))
    
    logger.debug(f"Database path resolved to: {db_path}")
    return db_path

def get_backup_dir(app):
    """
    Get the backup directory, creating it if it doesn't exist.
    
    Args:
        app: Flask application instance
        
    Returns:
        str: Path to the backup directory
    """
    backup_dir = os.path.join(app.instance_path, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def create_backup(app, backup_name=None):
    """
    Create a backup of the database and configuration files.
    
    Args:
        app: Flask application instance
        backup_name: Optional name for the backup (default: timestamp)
        
    Returns:
        dict: Backup information with path and timestamp
    """
    db_path = get_db_path(app)
    if not db_path or not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    
    # Use current timestamp if no name provided
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if not backup_name:
        backup_name = f"backup_{timestamp}"
    else:
        # Sanitize the name
        backup_name = backup_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        backup_name = f"{backup_name}_{timestamp}"
    
    backup_dir = get_backup_dir(app)
    backup_path = os.path.join(backup_dir, backup_name)
    os.makedirs(backup_path, exist_ok=True)
    
    # Backup database
    db_backup_path = os.path.join(backup_path, os.path.basename(db_path))
    try:
        # Usa shutil.copy2 invece della funzione backup di SQLite per compatibilità universale
        # Prima verifica che il database non sia in uso (si spera che sia in sola lettura durante il backup)
        try:
            shutil.copy2(db_path, db_backup_path)
            logger.info(f"Database backup created at {db_backup_path} using file copy")
        except Exception as copy_error:
            logger.warning(f"Error during file copy backup: {str(copy_error)}, trying SQL backup...")
            
            # Alternativa: esporta e importa i dati tramite SQL
            # Connessione al database di origine
            source_conn = sqlite3.connect(db_path)
            source_cursor = source_conn.cursor()
            
            # Connessione al database di destinazione
            dest_conn = sqlite3.connect(db_backup_path)
            dest_cursor = dest_conn.cursor()
            
            # Ottieni lo schema del database
            source_cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables_schema = source_cursor.fetchall()
            
            # Crea le tabelle nel database di destinazione
            for schema in tables_schema:
                dest_cursor.execute(schema[0])
            
            # Copia i dati per ogni tabella
            source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = source_cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                source_cursor.execute(f"SELECT * FROM {table_name}")
                rows = source_cursor.fetchall()
                
                if rows:
                    # Ottieni le colonne
                    source_cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = source_cursor.fetchall()
                    column_count = len(columns)
                    
                    # Crea la stringa di placeholder per l'INSERT
                    placeholders = ','.join(['?' for _ in range(column_count)])
                    
                    # Inserisci i dati
                    for row in rows:
                        dest_cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
            
            # Commit e chiudi le connessioni
            dest_conn.commit()
            source_conn.close()
            dest_conn.close()
            logger.info(f"Database backup created at {db_backup_path} using SQL export/import")
    except Exception as e:
        logger.error(f"Error creating database backup: {str(e)}")
        raise
    
    # Backup configuration files
    configs = {
        'rclone_scheduled.conf': os.environ.get("RCLONE_CONFIG_PATH", "./data/rclone_scheduled.conf"),
        'rclone.conf': os.environ.get("RCLONE_MAIN_CONFIG_PATH", "/root/.config/rclone/rclone.conf")
    }
    
    config_backup_info = {}
    for config_name, config_path in configs.items():
        if os.path.exists(config_path):
            config_backup_path = os.path.join(backup_path, config_name)
            try:
                shutil.copy2(config_path, config_backup_path)
                config_backup_info[config_name] = config_backup_path
                logger.info(f"Configuration file {config_name} backed up to {config_backup_path}")
            except Exception as e:
                logger.error(f"Error backing up {config_name}: {str(e)}")
    
    # Create backup metadata
    backup_info = {
        'timestamp': timestamp,
        'name': backup_name,
        'database': db_backup_path,
        'configs': config_backup_info,
        'path': backup_path
    }
    
    # Save backup metadata
    with open(os.path.join(backup_path, 'backup_info.json'), 'w') as f:
        json.dump(backup_info, f, indent=2)
    
    logger.info(f"Backup completed: {backup_name}")
    return backup_info

def list_backups(app):
    """
    List all available backups.
    
    Args:
        app: Flask application instance
        
    Returns:
        list: List of backup information dictionaries
    """
    backup_dir = get_backup_dir(app)
    backup_info_files = glob.glob(os.path.join(backup_dir, '**/backup_info.json'), recursive=True)
    
    backups = []
    for info_file in backup_info_files:
        try:
            with open(info_file, 'r') as f:
                backup_info = json.load(f)
                # Check if the backup files still exist
                if os.path.exists(backup_info.get('database', '')):
                    # Add some useful derived information
                    backup_info['date'] = datetime.strptime(
                        backup_info['timestamp'], '%Y%m%d_%H%M%S'
                    ).strftime('%Y-%m-%d %H:%M:%S')
                    backup_info['size'] = os.path.getsize(backup_info['database'])
                    backup_info['size_formatted'] = format_size(backup_info['size'])
                    backups.append(backup_info)
        except Exception as e:
            logger.error(f"Error reading backup info from {info_file}: {str(e)}")
    
    # Sort backups by timestamp, newest first
    return sorted(backups, key=lambda x: x['timestamp'], reverse=True)

def format_size(size_bytes):
    """
    Format file size in a human-readable format.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        str: Formatted size string
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024 or unit == 'GB':
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024

def restore_backup(app, backup_name):
    """
    Restore database and configs from a backup.
    
    Args:
        app: Flask application instance
        backup_name: Name of the backup to restore
        
    Returns:
        bool: True if successful, False otherwise
    """
    backup_dir = get_backup_dir(app)
    backup_path = os.path.join(backup_dir, backup_name)
    info_file = os.path.join(backup_path, 'backup_info.json')
    
    if not os.path.exists(info_file):
        logger.error(f"Backup information file not found: {info_file}")
        return False
    
    try:
        with open(info_file, 'r') as f:
            backup_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading backup information: {str(e)}")
        return False
    
    # Check if database backup exists
    db_backup_path = backup_info.get('database')
    if not db_backup_path or not os.path.exists(db_backup_path):
        logger.error(f"Database backup not found: {db_backup_path}")
        return False
    
    # Get current database path
    db_path = get_db_path(app)
    if not db_path:
        logger.error("Could not determine database path from application configuration")
        return False
    
    # First, create a backup of the current state before restoring
    try:
        create_backup(app, "pre_restore_backup")
    except Exception as e:
        logger.warning(f"Failed to create pre-restore backup: {str(e)}")
    
    # Restore database
    try:
        # Prova prima con il metodo più semplice: copia diretta del file
        try:
            # Prima crea una copia di sicurezza
            temp_backup = f"{db_path}.before_restore"
            shutil.copy2(db_path, temp_backup)
            logger.info(f"Created temporary backup at {temp_backup}")
            
            # Poi copia il file di backup sul database corrente
            shutil.copy2(db_backup_path, db_path)
            logger.info(f"Database restored from {db_backup_path} using file copy")
            
            # Se tutto è andato bene, elimina la copia temporanea
            # os.remove(temp_backup)  # Commentiamo questa riga per mantenere un backup locale
        except Exception as copy_error:
            logger.warning(f"Error during file copy restore: {str(copy_error)}, trying SQL restore...")
            
            # Ripristino tramite SQL
            source_conn = sqlite3.connect(db_backup_path)
            source_cursor = source_conn.cursor()
            
            # Connessione al database di destinazione
            dest_conn = sqlite3.connect(db_path, isolation_level='EXCLUSIVE')
            dest_cursor = dest_conn.cursor()
            
            # Avvia una transazione esclusiva
            dest_conn.execute('BEGIN EXCLUSIVE')
            
            # Elimina tutte le tabelle nel database di destinazione
            dest_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = dest_cursor.fetchall()
            for table in tables:
                dest_cursor.execute(f"DROP TABLE IF EXISTS {table[0]}")
            
            # Ottieni lo schema del database di origine
            source_cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables_schema = source_cursor.fetchall()
            
            # Crea le tabelle nel database di destinazione
            for schema in tables_schema:
                dest_cursor.execute(schema[0])
            
            # Copia i dati per ogni tabella
            source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = source_cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                source_cursor.execute(f"SELECT * FROM {table_name}")
                rows = source_cursor.fetchall()
                
                if rows:
                    # Ottieni le colonne
                    source_cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = source_cursor.fetchall()
                    column_count = len(columns)
                    
                    # Crea la stringa di placeholder per l'INSERT
                    placeholders = ','.join(['?' for _ in range(column_count)])
                    
                    # Inserisci i dati
                    for row in rows:
                        dest_cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
            
            # Commit e chiudi le connessioni
            dest_conn.commit()
            source_conn.close()
            dest_conn.close()
            logger.info(f"Database restored from {db_backup_path} using SQL export/import")
        
        logger.info(f"Database restored successfully from {db_backup_path}")
    except Exception as e:
        logger.error(f"Error restoring database: {str(e)}")
        return False
    
    # Restore configuration files
    for config_name, config_path in backup_info.get('configs', {}).items():
        if os.path.exists(config_path):
            try:
                # Determine destination path
                if config_name == 'rclone_scheduled.conf':
                    dest_path = os.environ.get("RCLONE_CONFIG_PATH", "./data/rclone_scheduled.conf")
                elif config_name == 'rclone.conf':
                    dest_path = os.environ.get("RCLONE_MAIN_CONFIG_PATH", "/root/.config/rclone/rclone.conf")
                else:
                    logger.warning(f"Unknown configuration file: {config_name}")
                    continue
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                # Copy file
                shutil.copy2(config_path, dest_path)
                logger.info(f"Configuration file {config_name} restored to {dest_path}")
            except Exception as e:
                logger.error(f"Error restoring {config_name}: {str(e)}")
    
    logger.info(f"Backup {backup_name} restored successfully")
    return True

def delete_backup(app, backup_name):
    """
    Delete a backup.
    
    Args:
        app: Flask application instance
        backup_name: Name of the backup to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    backup_dir = get_backup_dir(app)
    backup_path = os.path.join(backup_dir, backup_name)
    
    if not os.path.exists(backup_path):
        logger.error(f"Backup not found: {backup_path}")
        return False
    
    try:
        shutil.rmtree(backup_path)
        logger.info(f"Backup {backup_name} deleted")
        return True
    except Exception as e:
        logger.error(f"Error deleting backup {backup_name}: {str(e)}")
        return False

def setup_auto_backup(app, interval_hours=24):
    """
    Set up automatic database backups.
    
    Args:
        app: Flask application instance
        interval_hours: Backup interval in hours
        
    Returns:
        Thread: The backup thread
    """
    def backup_job():
        while True:
            try:
                with app.app_context():
                    logger.info(f"Running automatic backup")
                    create_backup(app, "auto_backup")
                    
                    # Clean up old automatic backups (keep only the last 5)
                    all_backups = list_backups(app)
                    auto_backups = [b for b in all_backups if 'auto_backup' in b['name']]
                    
                    if len(auto_backups) > 5:
                        for backup in auto_backups[5:]:
                            try:
                                delete_backup(app, backup['name'])
                            except Exception as e:
                                logger.error(f"Error deleting old auto backup: {str(e)}")
            except Exception as e:
                logger.error(f"Error in automatic backup: {str(e)}")
            
            # Sleep for the specified interval
            time.sleep(interval_hours * 3600)
    
    backup_thread = Thread(target=backup_job, daemon=True)
    backup_thread.start()
    return backup_thread