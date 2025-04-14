import os
import re
import json
import time
import logging
import subprocess
from datetime import datetime
from threading import Thread

logger = logging.getLogger(__name__)

class RCloneHandler:
    """Handler for interacting with rclone and the bash script"""

    def __init__(self, config_path, log_dir):
        """Initialize the RClone handler
        
        Args:
            config_path: Path to the rclone configuration file with scheduled jobs
            log_dir: Directory where logs are stored
        """
        self.config_path = config_path
        self.log_dir = log_dir
        self.active_jobs = {}
        self.main_config_path = "/root/.config/rclone/rclone.conf"
        
        # Create log directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)
    
    def get_configured_jobs(self):
        """Get list of jobs from configuration file"""
        jobs = []
        
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path}")
            return jobs
        
        try:
            with open(self.config_path, 'r') as f:
                lines = f.readlines()
                
            for i, line in enumerate(lines):
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 2:
                        source, target = parts
                        jobs.append({
                            'id': i,
                            'source': source,
                            'target': target
                        })
        except Exception as e:
            logger.error(f"Error reading config file: {str(e)}")
        
        return jobs
    
    def read_config_file(self):
        """Read the current configuration file content"""
        if not os.path.exists(self.config_path):
            return ""
        
        try:
            with open(self.config_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading config file: {str(e)}")
            return f"# Error reading file: {str(e)}"
    
    def save_config_file(self, content):
        """Save changes to the configuration file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            with open(self.config_path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Error saving config file: {str(e)}")
            raise
    
    def run_custom_job(self, source, target, dry_run=False):
        """Run a custom job with source and target"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        tag = f"{source.replace(':', '_').replace('/', '_')}__TO__{target.replace(':', '_').replace('/', '_')}"
        log_file = f"{self.log_dir}/sync_{timestamp}_{tag}.log"
        
        # Check if a job with the same source and target is already running
        lock_file = f"{self.log_dir}/sync_{tag}.lock"
        if os.path.exists(lock_file):
            raise Exception(f"A job with the same source and target is already running: {source} → {target}")
        
        # Prepare command
        cmd = ["/bin/bash", "-c", f"rclone sync '{source}' '{target}' --progress --stats=15s"]
        
        # Add dry-run flag if needed
        if dry_run:
            cmd[-1] += " --dry-run"
        
        # Add other common options
        cmd[-1] += " --log-level INFO"
        cmd[-1] += f" --log-file '{log_file}'"
        cmd[-1] += " --no-check-certificate"
        
        # Add checksum or size-only based on source/target
        src_remote = source.split(':', 1)[0] if ':' in source else ""
        tgt_remote = target.split(':', 1)[0] if ':' in target else ""
        
        if src_remote and tgt_remote:
            # Determine if we can use checksums
            src_hashes_cmd = f"rclone backend features {src_remote}: --json --no-check-certificate"
            tgt_hashes_cmd = f"rclone backend features {tgt_remote}: --json --no-check-certificate"
            
            # Log the hash capability check commands
            logger.info(f"Checking source hash capabilities: {src_hashes_cmd}")
            logger.info(f"Checking target hash capabilities: {tgt_hashes_cmd}")
            
            try:
                # Crea un ambiente senza variabili proxy
                my_env = os.environ.copy()
                for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
                    if proxy_var in my_env:
                        del my_env[proxy_var]
                        logger.info(f"Unset proxy variable for hash check: {proxy_var}")
                
                # Utilizzare Popen invece di run per maggiore compatibilità con versioni Python più vecchie
                src_process = subprocess.Popen(
                    src_hashes_cmd, 
                    shell=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    universal_newlines=True,
                    env=my_env
                )
                src_stdout, src_stderr = src_process.communicate()
                src_result_text = src_stdout
                src_returncode = src_process.returncode

                tgt_process = subprocess.Popen(
                    tgt_hashes_cmd, 
                    shell=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    universal_newlines=True,
                    env=my_env
                )
                tgt_stdout, tgt_stderr = tgt_process.communicate()
                tgt_result_text = tgt_stdout
                tgt_returncode = tgt_process.returncode
                
                src_hashes = []
                tgt_hashes = []
                
                if src_returncode == 0:
                    src_json = json.loads(src_result_text)
                    src_hashes = src_json.get('Hashes', [])
                
                if tgt_returncode == 0:
                    tgt_json = json.loads(tgt_result_text)
                    tgt_hashes = tgt_json.get('Hashes', [])
                
                common_hashes = set(src_hashes) & set(tgt_hashes)
                
                if common_hashes:
                    cmd[-1] += " --checksum"
                else:
                    cmd[-1] += " --size-only"
            except Exception as e:
                logger.warning(f"Error determining hash capability: {str(e)}. Using --size-only")
                cmd[-1] += " --size-only"
        else:
            # Default to size-only if we can't determine
            cmd[-1] += " --size-only"
        
        # Add other common options
        cmd[-1] += " --transfers=4 --checkers=8 --retries=10"
        
        # Add user-requested default flags
        cmd[-1] += " --metadata --use-server-modtime --gcs-bucket-policy-only"
        
        # Log the complete command being executed
        logger.info(f"Executing command: {cmd[-1]}")
        
        # Crea un ambiente senza variabili proxy
        my_env = os.environ.copy()
        for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
            if proxy_var in my_env:
                del my_env[proxy_var]
                logger.info(f"Unset proxy variable: {proxy_var}")
        
        # Start process with clean environment
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            universal_newlines=True,  # Equivalente a text=True nelle versioni più recenti
            env=my_env
        )
        
        # Create lock file
        with open(lock_file, 'w') as f:
            f.write(str(process.pid))
        
        # Store job info
        job_info = {
            'source': source,
            'target': target,
            'dry_run': dry_run,
            'process': process,
            'log_file': log_file,
            'lock_file': lock_file,
            'start_time': datetime.now()
        }
        
        job_key = f"{source}|{target}"
        self.active_jobs[job_key] = job_info
        
        # Start a thread to monitor the job
        Thread(target=self._monitor_job, args=(job_key,), daemon=True).start()
        
        return job_info
    
    def run_configured_job(self, job_id, dry_run=False):
        """Run a configured job from the config file"""
        jobs = self.get_configured_jobs()
        job_id = int(job_id)
        
        if job_id < 0 or job_id >= len(jobs):
            raise Exception(f"Invalid job ID: {job_id}")
        
        job = jobs[job_id]
        return self.run_custom_job(job['source'], job['target'], dry_run)
    
    def _monitor_job(self, job_key):
        """Monitor a running job and clean up when done"""
        if job_key not in self.active_jobs:
            return
        
        job = self.active_jobs[job_key]
        process = job['process']
        
        # Wait for process to finish
        process.wait()
        
        # Remove lock file
        if os.path.exists(job['lock_file']):
            os.remove(job['lock_file'])
        
        # Update job info with end time and status
        job['end_time'] = datetime.now()
        job['exit_code'] = process.returncode
        
        # Log completion
        status = "completed successfully" if process.returncode == 0 else f"failed with exit code {process.returncode}"
        logger.info(f"Job {job['source']} → {job['target']} {status}")
        
        # Remove from active jobs after a delay
        time.sleep(60)  # Keep in active jobs list for 1 minute after completion
        if job_key in self.active_jobs:
            del self.active_jobs[job_key]
    
    def get_active_jobs(self):
        """Get list of currently active jobs"""
        # Clean up any dead jobs
        job_keys = list(self.active_jobs.keys())
        for job_key in job_keys:
            job = self.active_jobs[job_key]
            if job['process'].poll() is not None:
                # Process has finished
                if not os.path.exists(job['lock_file']):
                    del self.active_jobs[job_key]
        
        # Return active jobs
        active_jobs = []
        for job_key, job in self.active_jobs.items():
            active_jobs.append({
                'source': job['source'],
                'target': job['target'],
                'dry_run': job['dry_run'],
                'log_file': job['log_file'],
                'start_time': job['start_time'],
                'duration': (datetime.now() - job['start_time']).total_seconds()
            })
        
        return active_jobs
    
    def is_job_running(self, source, target):
        """Check if a job with the given source and target is running"""
        job_key = f"{source}|{target}"
        
        if job_key in self.active_jobs:
            job = self.active_jobs[job_key]
            if job['process'].poll() is None:
                # Process is still running
                return True
        
        # Also check for lock file
        tag = f"{source.replace(':', '_').replace('/', '_')}__TO__{target.replace(':', '_').replace('/', '_')}"
        lock_file = f"{self.log_dir}/sync_{tag}.lock"
        return os.path.exists(lock_file)
    
    def get_recent_logs(self, limit=10):
        """Get recent log files"""
        logs = []
        
        if not os.path.exists(self.log_dir):
            return logs
        
        try:
            # Get all log files
            files = os.listdir(self.log_dir)
            log_files = [f for f in files if f.startswith("sync_") and f.endswith(".log")]
            
            # Sort by modification time (newest first)
            log_files.sort(key=lambda x: os.path.getmtime(os.path.join(self.log_dir, x)), reverse=True)
            
            # Get limited number of logs
            for log_file in log_files[:limit]:
                file_path = os.path.join(self.log_dir, log_file)
                
                # Parse source and target from filename
                match = re.search(r'sync_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+?)__TO__(.+?)\.log$', log_file)
                source = match.group(1).replace('_', ':').replace('-', '/') if match else "Unknown"
                target = match.group(2).replace('_', ':').replace('-', '/') if match else "Unknown"
                
                # Get file stats
                stats = os.stat(file_path)
                
                logs.append({
                    'file': log_file,
                    'path': file_path,
                    'source': source,
                    'target': target,
                    'size': stats.st_size,
                    'modified': datetime.fromtimestamp(stats.st_mtime)
                })
        except Exception as e:
            logger.error(f"Error reading log directory: {str(e)}")
        
        return logs
        
    def read_main_config_file(self):
        """Read the main rclone config file content"""
        try:
            # Check if file exists
            if not os.path.exists(self.main_config_path):
                logger.warning(f"Main config file not found: {self.main_config_path}")
                return "# Config file not found"
            
            # Read file content
            with open(self.main_config_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading main config file: {str(e)}")
            return f"# Error reading file: {str(e)}"
    
    def save_main_config_file(self, content):
        """Save changes to the main rclone config file"""
        try:
            # Create parent directory if needed
            os.makedirs(os.path.dirname(self.main_config_path), exist_ok=True)
            
            # Backup the original file before overwrite
            if os.path.exists(self.main_config_path):
                backup_path = f"{self.main_config_path}.bak"
                with open(self.main_config_path, 'r') as src:
                    with open(backup_path, 'w') as dst:
                        dst.write(src.read())
                logger.info(f"Backup created: {backup_path}")
            
            # Write the new content
            with open(self.main_config_path, 'w') as f:
                f.write(content)
            
            logger.info(f"Main config file updated: {self.main_config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving main config file: {str(e)}")
            raise

