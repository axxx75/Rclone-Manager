![License](https://img.shields.io/github/license/axxx75/Rclone-Manager)
![Version](https://img.shields.io/github/v/release/axxx75/Rclone-Manager)


# RClone Manager

A Flask web application to reliably manage rclone sync jobs.

Key Features:
* Create and manage synchronization jobs
* Automatic job scheduling with cron expressions
* Detailed logs and advanced log search
* Browser notifications for important job events
* Advanced user interface with filters and pagination

## Requirements

- Python 3.6+
- Rclone (1.50+ recommended)  [Documentation](https://rclone.org/install/)
  ```
  sudo -v ; curl https://rclone.org/install.sh | sudo bash
  ```
- Install necessary packages :
  ```
  apt install -y python3-dev libpq-dev gcc python3.12-venv
  ```

## Installation and start application
Assuming you install under the /opt directory:

1. Clone this repository
  ```
  cd /opt
  git clone https://github.com/axxx75/Rclone-Manager.git
  ```
2. Prepare enviroment
  ```
  cd /opt/Rclone-Manager
  python3 -m venv venv
  source venv/bin/activate
  ```
3. Install Python dependencies:
  ```
  pip3 install tqdm flask flask-sqlalchemy gunicorn psycopg2-binary email-validator crontab
  ```
4. Configure App with service

Open file `rclone-manager.service` and modify section:
  ```
  User=YOUR_USERNAME
  Group=YOUR_USERNAME
  WorkingDirectory=/path/to/rclone-manager
  ExecStart=/bin/bash -c 'source /path/to/rclone-manager/venv/bin/activate && ./start_all.sh'
  ExecStartPre=/bin/mkdir -p /path/to/rclone-manager/data/logs
  ```
Configure the service:
  ```
  cp /opt/Rclone-Manager/rclone-manager.service /etc/systemd/system/
  systemctl daemon-reexec
  systemctl daemon-reload
  systemctl enable rclone-manager
  systemctl start rclone-manager
  ```

## Service Management

- **Restart the service**:
  ```bash
  sudo systemctl restart rclone-manager
  ```

- **Stop the service**:
  ```bash
  sudo systemctl stop rclone-manager
  ```


- **Status of the service**:
  ```bash
  sudo systemctl status rclone-manager
  ```

- **View log**:
  ```bash
  sudo journalctl -u rclone-manager -f
  ```

## Problem resolution

If the service does not start correctly, check the log with:

```bash
sudo journalctl -u rclone-manager -e
```

## Usage

The application is very user friendly:

![Home page](/img/index.png)

![Jobs page](/img/job.png)

![History page](/img/history.png)

![Configuration page](/img/configuration1.png)

![Configuration page](/img/configuration2.png)

## Configuration

You can customize default settings by:

1. To configure REMOTE: Customizing /root/.config/rclone/rclone.conf. You can also do it from the GUI, under the "Maintenance" - "Configuration" menu.
  Detail to common provider at page [DETAIL_PROVIDER.md](./DETAIL_PROVIDER.md)
2. To configure JOB: Customizing <INSTALL_DIR>/data/rclone_scheduled.conf. You can also do it from the GUI, under the "Manutenzione" - "Configurazione" menu 
3. To configure CRONTAB: From GUI, in "Pianificazione" page
5. To configure BACKUP DB: From GUI, under "Manutenzione" - "Backup & Restore"

## File structure

See [File strutcture](./FILE_STRUCTURE.md) of application 

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT [LICENSE](./LICENSE)
