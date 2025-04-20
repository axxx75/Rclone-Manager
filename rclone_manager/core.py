
import subprocess
import logging
from rclone_manager.config import RCLONE_BIN

logger = logging.getLogger(__name__)

def run_rclone_command(args: list[str]) -> tuple[bool, str]:
    cmd = [RCLONE_BIN] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Errore rclone: {e.stderr}")
        return False, e.stderr
