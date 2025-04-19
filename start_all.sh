#!/bin/bash
#source /opt/Rclone-Manager/venv/bin/activate

# Script di avvio per l'intero sistema
# Avvia lo scheduler in background
echo "Avvio scheduler..."
nohup python scheduler_runner.py > scheduler.log 2>&1 &
SCHEDULER_PID=$!
echo "Scheduler avviato con PID: $SCHEDULER_PID"

# Attendi un po' per verificare che lo scheduler sia avviato correttamente
sleep 2
if ! ps -p $SCHEDULER_PID > /dev/null; then
    echo "ERRORE: Lo scheduler si è arrestato rapidamente, controlla scheduler.log per i dettagli"
    cat scheduler.log
    exit 1
fi

# Avvia l'applicazione web
echo "Avvio applicazione web..."
exec gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app \
--access-logfile /opt/Rclone-Manager/data/logs/access.log \
--error-logfile /opt/Rclone-Manager/data/logs/error.log
