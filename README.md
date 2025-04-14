# RClone Manager

A robust Python wrapper for efficient bucket synchronization using rclone with enhanced features for:

- Checksum verification for data integrity
- Performance tuning for unstable networks
- Automatic retry mechanism with exponential backoff
- Comprehensive error handling
- Detailed logging and progress reporting

## Requirements

- Python 3.6+
- Rclone (1.50+ recommended)  [https://rclone.org/install/](Documentation)
  ```
  sudo -v ; curl https://rclone.org/install.sh | sudo bash
  ```
- Install necessary packages :
  ```
  apt install -y python3-dev libpq-dev gcc python3.12-venv
  ```
- Prepare enviroment
  ```
  python3 -m venv venv
  source venv/bin/activate
  ```
- Install Python dependencies:
  ```
  pip3 install tqdm flask flask-sqlalchemy gunicorn psycopg2-binary email-validator
  ```

## Installation and start application

1. Clone this repository
  ```
  git clone [https://github.com/axxx75/Rclone-Manager/rclone-manager.git](https://github.com/axxx75/Rclone-Manager.git)
  ```
2. Start Application
  ```
  cd Rclone-manager
  python3 main.py
  ```

## Usage


## Configuration

You can customize default settings by:

1. Customizing /root/.config/rclone/rclone.conf
3. Modifying config parameters in your own scripts

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License
