import os
import sys
import logging
import threading
import time
import atexit

# Configura logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Importa l'app
from app import app, job_scheduler

# Gestione dello scheduler per Gunicorn/Flask
SCHEDULER_LOCK_FILE = ".scheduler_lock"

def cleanup_lock():
    """Rimuove il file di lock all'uscita"""
    try:
        if os.path.exists(SCHEDULER_LOCK_FILE):
            os.remove(SCHEDULER_LOCK_FILE)
            logger.info("Scheduler lock rimosso")
    except:
        pass

def cleanup_sync_lock_files():
    """Pulisce i file di lock stale per i job di sincronizzazione"""
    from app import LOG_DIR
    import glob
    
    if not os.path.exists(LOG_DIR):
        return
    
    # Cerca tutti i file di lock nella directory di log
    lock_pattern = os.path.join(LOG_DIR, "sync_*.lock")
    lock_files = glob.glob(lock_pattern)
    
    for lock_file in lock_files:
        try:
            # Verifica l'età del file
            file_age = time.time() - os.path.getmtime(lock_file)
            
            # Prova a trovare il file di log corrispondente
            log_file = lock_file.replace(".lock", ".log")
            is_stale = False
            
            if os.path.exists(log_file):
                # Verifica se il file di log è fermo da più di 6 ore
                log_age = time.time() - os.path.getmtime(log_file)
                
                # Considera stale solo se entrambi i file sono fermi da più di 6 ore
                if log_age > 21600 and file_age > 21600:  # 6 ore = 21600 secondi
                    logger.warning(f"Job considerato stale - file di log ({log_age:.1f}s) e lock ({file_age:.1f}s) fermi da più di 6 ore")
                    is_stale = True
            else:
                # Se non c'è file di log, verifica solo il lock file
                if file_age > 21600:  # 6 ore = 21600 secondi
                    logger.warning(f"Job considerato stale - lock file fermo da più di 6 ore: {file_age:.1f}s")
                    is_stale = True
                    
            # Rimuovi il lock file solo se considerato stale
            if is_stale:
                os.remove(lock_file)
                logger.info(f"Rimozione file di lock stale: {os.path.basename(lock_file)} (età: {file_age:.1f}s)")
        except Exception as e:
            logger.error(f"Errore durante la verifica/rimozione del lock file {lock_file}: {str(e)}")

def start_scheduler_thread():
    """Avvia lo scheduler in un thread daemon"""
    logger.info("Inizializzazione thread scheduler...")
    
    # Pulisci i file di lock stale per i job di sincronizzazione
    cleanup_sync_lock_files()
    
    # Verifica se esiste già un file di lock
    if os.path.exists(SCHEDULER_LOCK_FILE):
        # Verifica l'età del file per determinare se è stale
        file_age = time.time() - os.path.getmtime(SCHEDULER_LOCK_FILE)
        if file_age < 60:  # Se il file ha meno di 60 secondi
            logger.info(f"File di lock recente trovato (età: {file_age:.1f}s). Scheduler già in esecuzione?")
            return
        else:
            # Il file è vecchio, possiamo rimuoverlo
            logger.info(f"Rimozione file di lock stale (età: {file_age:.1f}s)")
            os.remove(SCHEDULER_LOCK_FILE)
    
    # Crea il file di lock
    try:
        with open(SCHEDULER_LOCK_FILE, "w") as f:
            f.write(f"Scheduler avviato: {time.ctime()}")
        
        # Registra la funzione di pulizia all'uscita
        atexit.register(cleanup_lock)
        
        # Attendi un momento per assicurarsi che l'applicazione sia completamente inizializzata
        time.sleep(2)
        
        # Avvia lo scheduler nel contesto dell'applicazione
        with app.app_context():
            job_scheduler.start()
            logger.info("Scheduler avviato correttamente")
    except Exception as e:
        logger.error(f"Errore nell'avvio dello scheduler: {e}")

# Avvia il thread dello scheduler (sia per Flask che per Gunicorn)
# Questo è il metodo preferito: funziona sia con Flask che con Gunicorn
scheduler_thread = threading.Thread(target=start_scheduler_thread, daemon=True)
scheduler_thread.start()

# Se il processo è avviato direttamente con python (non tramite gunicorn)
if __name__ == "__main__":
    # Avvia il server di sviluppo Flask
    app.run(host="0.0.0.0", port=5000, debug=True)
