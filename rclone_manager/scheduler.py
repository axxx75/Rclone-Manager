
import threading
from rclone_manager.core import run_rclone_command

class Scheduler:
    def __init__(self):
        self.jobs = []

    def schedule_task(self, src: str, dst: str, options: list[str]) -> None:
        thread = threading.Thread(target=self._sync_task, args=(src, dst, options))
        thread.start()
        self.jobs.append(thread)

    def _sync_task(self, src: str, dst: str, options: list[str]):
        run_rclone_command(["sync", src, dst] + options)
