#!/bin/bash
# Script per installare RClone Manager come servizio systemd

# Verifica se l'utente ha i privilegi di root
if [ "$(id -u)" -ne 0 ]; then
    echo "Questo script deve essere eseguito come root o con sudo."
    exit 1
fi

# Imposta le variabili
INSTALL_DIR=$(pwd)
USER=$(whoami)
GROUP=$(id -gn)
SERVICE_FILE="rclone-manager.service"
DESTINATION="/etc/systemd/system/${SERVICE_FILE}"

echo "=== Installazione RClone Manager come servizio systemd ==="
echo "Directory di installazione: $INSTALL_DIR"
echo "Utente: $USER"
echo "Gruppo: $GROUP"

# Verifica se il file di servizio esiste
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Errore: Il file $SERVICE_FILE non esiste nella directory corrente."
    exit 1
fi

# Verifica se start_all.sh esiste ed è eseguibile
if [ ! -f "$INSTALL_DIR/start_all.sh" ]; then
    echo "Errore: Lo script start_all.sh non è presente nella directory corrente."
    exit 1
fi

# Rendi eseguibile start_all.sh
chmod +x "$INSTALL_DIR/start_all.sh"
echo "Reso eseguibile start_all.sh"

# Crea directory logs se non esiste
mkdir -p "$INSTALL_DIR/data/logs"
echo "Verificata directory dei log: $INSTALL_DIR/data/logs"

# Sosituisci i placeholder nel file di servizio
echo "Personalizzazione del file di servizio..."
sed -i "s|User=YOUR_USERNAME|User=$USER|g" "$SERVICE_FILE"
sed -i "s|Group=YOUR_USERNAME|Group=$GROUP|g" "$SERVICE_FILE"
sed -i "s|/path/to/rclone-manager|$INSTALL_DIR|g" "$SERVICE_FILE"

# Richiedi informazioni per il database
read -p "Inserisci l'URL del database PostgreSQL [postgresql://user:password@localhost/rclone_manager]: " DB_URL
DB_URL=${DB_URL:-postgresql://user:password@localhost/rclone_manager}
sed -i "s|postgresql://user:password@localhost/rclone_manager|$DB_URL|g" "$SERVICE_FILE"

# Copia il file di servizio
echo "Copia del file di servizio in $DESTINATION..."
cp "$SERVICE_FILE" "$DESTINATION"

# Ricarica systemd
echo "Ricarica della configurazione systemd..."
systemctl daemon-reload

# Abilita il servizio
echo "Abilitazione del servizio per l'avvio automatico..."
systemctl enable rclone-manager.service

echo
echo "=== Installazione completata ==="
echo "Per avviare il servizio: sudo systemctl start rclone-manager"
echo "Per verificare lo stato: sudo systemctl status rclone-manager"
echo "Per visualizzare i log: sudo journalctl -u rclone-manager -f"
echo

# Chiedi se avviare subito il servizio
read -p "Vuoi avviare il servizio adesso? (s/n): " START_NOW
if [[ "$START_NOW" =~ ^[Ss]$ ]]; then
    echo "Avvio del servizio..."
    systemctl start rclone-manager.service
    sleep 2
    systemctl status rclone-manager.service
else
    echo "Il servizio non è stato avviato. Puoi avviarlo manualmente quando vuoi."
fi
