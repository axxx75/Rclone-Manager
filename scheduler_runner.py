#!/usr/bin/env python
"""
Standalone scheduler runner per l'applicazione rclone_manager.
Questo script avvia il job scheduler in un processo separato.

Usato per garantire che esista solo un'istanza attiva dello scheduler,
anche in presenza di più worker Gunicorn.

NOTA: Questa modalità è mantenuta per compatibilità, ma è preferibile
utilizzare l'avvio automatico tramite thread in main.py quando possibile.
"""
import os
import sys
import time
import logging
import signal
import atexit
import socket
from datetime import datetime

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("scheduler_runner")

# File di lock
LOCK_FILE = "scheduler.lock"
PID_FILE = "scheduler.pid"

def is_port_in_use(port=5000):
    """Verifica se la porta è in uso (se l'app Flask è attiva)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def create_lock_file():
    """Crea un file di lock per prevenire esecuzioni multiple"""
    if os.path.exists(LOCK_FILE):
        # Verifica se il processo è ancora in esecuzione
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                
                # Prova a inviare un segnale al processo (0 non fa nulla, solo test)
                try:
                    os.kill(pid, 0)
                    logger.info(f"Processo {pid} è ancora in esecuzione, esco")
                    return False
                except OSError:
                    # Processo non esiste
                    logger.info(f"Lock file trovato ma processo {pid} non esiste, rimuovo i file di lock")
                    os.remove(LOCK_FILE)
                    os.remove(PID_FILE)
            except Exception as e:
                logger.error(f"Errore nella verifica del processo: {e}")
                os.remove(LOCK_FILE)
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
        else:
            logger.info("Lock file trovato ma nessun PID file, rimuovo il lock")
            os.remove(LOCK_FILE)
    
    # Crea il file di lock
    with open(LOCK_FILE, 'w') as f:
        f.write(f"Scheduler avviato il {datetime.now()}")
    
    # Crea il file PID
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    return True

def cleanup():
    """Pulizia risorse all'uscita"""
    logger.info("Arresto dello scheduler")
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception as e:
        logger.error(f"Errore nella pulizia dei file di lock: {e}")

def handle_signal(signum, frame):
    """Gestione dei segnali (SIGTERM, SIGINT)"""
    logger.info(f"Ricevuto segnale {signum}, arresto in corso")
    cleanup()
    sys.exit(0)

def main():
    """Funzione principale"""
    # Registra handler per pulizia all'uscita
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    # Verifica che non ci siano già istanze in esecuzione
    logger.info("Avvio scheduler runner")
    if not create_lock_file():
        logger.error("Impossibile creare file di lock, un'altra istanza potrebbe essere in esecuzione")
        sys.exit(1)
    
    logger.info("In attesa dell'avvio dell'applicazione web...")
    
    # Attendi che l'applicazione sia avviata
    max_wait = 30  # secondi
    waited = 0
    while not is_port_in_use() and waited < max_wait:
        time.sleep(1)
        waited += 1
    
    if not is_port_in_use():
        logger.error(f"L'applicazione web non è stata avviata entro {max_wait} secondi")
        cleanup()
        sys.exit(1)
    
    logger.info("Applicazione web rilevata, avvio dello scheduler")
    
    # Importa l'app solo dopo aver verificato che sia in esecuzione
    try:
        from app import app, job_scheduler
        
        with app.app_context():
            # Avvia lo scheduler
            job_scheduler.start()
            logger.info("Scheduler avviato con successo")
            
            # Mantieni lo script in esecuzione
            while True:
                time.sleep(60)
                if not is_port_in_use():
                    logger.warning("L'applicazione web sembra essere stata arrestata, controllo...")
                    # Aspetta un po' per confermare
                    time.sleep(5)
                    if not is_port_in_use():
                        logger.error("L'applicazione web non è più in esecuzione, arresto dello scheduler")
                        break
    
    except KeyboardInterrupt:
        logger.info("Interruzione manuale, arresto dello scheduler")
    except Exception as e:
        logger.error(f"Errore durante l'esecuzione dello scheduler: {e}")
    
    # Pulizia
    cleanup()
    return 0

if __name__ == "__main__":
    sys.exit(main())