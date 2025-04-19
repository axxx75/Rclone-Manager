# Struttura dei File di RClone Manager

Questo documento descrive la struttura e la funzione di ciascun file e directory nel repository.

## File Principali

| File | Descrizione |
|------|-------------|
| main.py | Punto di ingresso principale dell'applicazione con pulizia di file di lock e avvio dello scheduler in modalità thread |
| app.py | Gestione delle route Flask, logica di controllo dei job orfani e API per aggiornamenti asincroni |
| models.py | Definizione dei modelli del database (SyncJob, SyncJobHistory, ScheduledJob, UserSettings, Notification) |
| rclone-manager.service | File di configurazione del servizio systemd per l'esecuzione in produzione |
| install_service.sh | Script per installare automaticamente il servizio con la configurazione dell'ambiente |
| SERVICE_INSTALL.md | Documentazione dettagliata per l'installazione del servizio |
| scheduler_runner.py | Processo per l'esecuzione indipendente dello scheduler (alternativa alla modalità thread) |
| pyproject.toml | Configurazione delle dipendenze e metadati del progetto |

## Directory e sottodirectory

### /utils

| File | Descrizione |
|------|-------------|
| rclone_handler.py | Gestione delle operazioni rclone con miglioramenti nella pulizia dei percorsi e monitoraggio dei job |
| scheduler.py | Implementazione del sistema di pianificazione dei job con sicurezza thread |
| notification_manager.py | Gestione delle notifiche browser con API per notifiche di job e impostazioni utente |
| backup_manager.py | Utilità per il backup e il ripristino del database e configurazioni |

### /templates

| File | Descrizione |
|------|-------------|
| base.html | Template principale con navigazione, menu e sistema di notifiche |
| index.html | Dashboard con monitoraggio dei job attivi, aggiornamenti asincroni e anelli di progresso |
| jobs.html | Pagina per la creazione e l'esecuzione di job di sincronizzazione |
| history.html | Cronologia dei job con filtri, paginazione e aggiornamenti in tempo reale |
| schedule.html | Gestione della pianificazione dei job con espressioni cron e controlli |
| config.html | Visualizzazione e modifica della configurazione rclone |
| backup.html | Interfaccia per il backup e il ripristino del database |
| search_logs.html | Ricerca nei file di log con evidenziazione dei risultati |
| user_settings.html | Gestione delle impostazioni utente incluse le notifiche |

### /static

| Directory/File | Descrizione |
|----------------|-------------|
| css/custom.css | Personalizzazioni CSS per la visualizzazione dei log e animazioni degli anelli di progresso |
| js/app.js | Logica frontend per gestione job, notifiche e animazioni degli anelli di progresso |

### /data

| Directory/File | Descrizione |
|----------------|-------------|
| rclone_scheduled.conf | File di configurazione per i job pianificati |
| logs/ | Directory contenente i log di esecuzione dei job |

### /instance

| Directory/File | Descrizione |
|----------------|-------------|
| rclone_manager.db | Database SQLite principale dell'applicazione |
| backups/ | Directory contenente i backup del database |

## Flusso di lavoro dell'applicazione

1. **Avvio**:
   - `main.py` avvia l'applicazione
   - Inizializza il thread dello scheduler
   - Pulisce eventuali file di lock stale

2. **Operazioni di sincronizzazione**:
   - La creazione/esecuzione di un job avviene tramite `app.py`
   - `rclone_handler.py` gestisce l'esecuzione dei comandi rclone
   - I job vengono tracciati nel database e come file di lock

3. **Pianificazione**:
   - `scheduler.py` gestisce l'esecuzione temporizzata dei job
   - Controlla i conflitti e aggiorna i tempi di esecuzione

4. **Interfaccia utente**:
   - Visualizzazione e gestione dei job attivi/completati
   - Notifiche in tempo reale degli eventi
   - Ricerca e filtri per log e cronologia

5. **Manutenzione**:
   - Backup e ripristino del database
   - Configurazione rclone
   - Pulizia di job bloccati o orfani
