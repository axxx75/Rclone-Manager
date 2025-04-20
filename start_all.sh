#!/bin/bash
# Script di avvio per l'intero sistema

# Ottieni la directory dello script
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_DIR="$BASE_DIR/data/logs"

# Assicurati che la cartella di log esista
mkdir -p "$LOG_DIR"

# Avvia lo scheduler in background
echo "🚀 Start Scheduler..."
nohup python "$BASE_DIR/scheduler_runner.py" > "$LOG_DIR/scheduler.log" 2>&1 &
SCHEDULER_PID=$!
echo "✅ Scheduler started with PID: $SCHEDULER_PID"

# Attendi un po' per verificare che lo scheduler sia avviato correttamente
sleep 2
if ! ps -p $SCHEDULER_PID > /dev/null; then
    echo "❌ ERROR: Scheduler crashed quickly, please check log below:"
    cat "$LOG_DIR/scheduler.log"
    exit 1
fi

# Avvia l'applicazione web
echo "🌐 Start Web Application..."
exec gunicorn --bind 0.0.0.0:5000 --reuse-port --reload --timeout 60 --graceful-timeout 60 --keep-alive 5 main:app \
  --access-logfile "$LOG_DIR/access.log" \
  --error-logfile "$LOG_DIR/error.log"
