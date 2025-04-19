# RClone Manager

A robust Python wrapper for efficient bucket synchronization using rclone with enhanced features for:

- Checksum verification for data integrity
- Performance tuning for unstable networks
- Automatic retry mechanism with exponential backoff
- Comprehensive error handling
- Detailed logging and progress reporting

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

1. Clone this repository
  ```
  cd /opt
  git clone [https://github.com/axxx75/Rclone-Manager/rclone-manager.git](https://github.com/axxx75/Rclone-Manager.git)
  ```
2. Prepare enviroment
  ```
  cd /opt/Rclone-Manager
  python3 -m venv venv
  source venv/bin/activate
  ```
3. Install Python dependencies:
  ```
  pip3 install tqdm flask flask-sqlalchemy gunicorn psycopg2-binary email-validator
  ```
5. Configure App with service
  ```
  cp /opt/Rclone-Manager/rclone-manager.service /etc/systemd/system/
  systemctl daemon-reexec
  systemctl daemon-reload
  systemctl enable rclone-manager
  systemctl start rclone-manager
  ```
  Controlla lo stato
  ```
  systemctl status rclone-manager
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

1. Customizing /root/.config/rclone/rclone.conf
2. Usig Configuration from web interface
3. Modifying config parameters in your own scripts

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[MIT LICENSE](https://github.com/axxx75/Rclone-Manager/edit/main/LICENSE)

