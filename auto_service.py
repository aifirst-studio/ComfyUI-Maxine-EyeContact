"""Opt-in lifecycle for this node's dedicated, same-host Linux NIM container."""
from contextlib import contextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

if sys.platform == 'linux':
    import fcntl

if __package__:
    from .activity import service_activity
    from .service import start_service
else:
    from activity import service_activity
    from service import start_service

ROOT = Path(__file__).resolve().parent
SERVICE = ROOT / 'service'
STATE = SERVICE / 'auto-state.json'
CONTAINER = 'maxine-eye-contact-nim'


def settings(config):
    options = config.get('auto_service', {})
    if not isinstance(options, dict) or not isinstance(options.get('enabled', False), bool):
        raise ValueError('auto_service must contain a boolean enabled setting.')
    if not options.get('enabled', False):
        return None
    if sys.platform != 'linux':
        raise RuntimeError('Automatic Maxine service control requires ComfyUI and Docker on the same Linux host. Disable auto_service for Windows or SSH tunnels.')
    queue_url = urlsplit(config.get('comfy_url', 'http://127.0.0.1:8188'))
    if queue_url.scheme != 'http' or queue_url.hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('Automatic service control requires a local ComfyUI queue URL.')
    idle = int(options.get('idle_timeout_seconds', 600))
    startup = int(options.get('startup_timeout_seconds', 600))
    if idle <= 0 or startup <= 0:
        raise ValueError('Automatic service timeouts must be positive seconds.')
    return {'idle_timeout_seconds': idle, 'startup_timeout_seconds': startup}


def save_state(state):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=SERVICE, delete=False) as stream:
        path = Path(stream.name)
        json.dump(state, stream)
    try:
        path.chmod(0o600)
        os.replace(path, STATE)
    finally:
        path.unlink(missing_ok=True)


def container_info():
    # Inspect only identity/state/Compose labels; never read Docker's NGC environment.
    template = '{"id":{{json .Id}},"started_at":{{json .State.StartedAt}},"status":{{json .State.Status}},"labels":{{json .Config.Labels}}}'
    result = subprocess.run(['docker', 'inspect', '--format', template, CONTAINER],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        # Distinguish an absent container from an inaccessible Docker daemon.
        subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return None
    info = json.loads(result.stdout)
    labels = info['labels'] or {}
    if (labels.get('com.docker.compose.project') != 'maxine-eye-contact'
            or labels.get('com.docker.compose.service') != 'eye-contact'
            or Path(labels.get('com.docker.compose.project.working_dir', '')).resolve() != SERVICE.resolve()):
        raise RuntimeError('The Maxine container belongs to another installation. Automatic control refused.')
    return info


def instance(info):
    return {'id': info['id'], 'started_at': info['started_at']}


def process_start(pid):
    # Linux start ticks distinguish a live client from a reused PID.
    try:
        return Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()[19]
    except FileNotFoundError:
        return None


def require_job(prompt_id):
    queue = start_service.comfy_queue()
    running = queue['queue_running']
    if len(running) == 1 and prompt_id and running[0][1] == prompt_id:
        return  # Only this ComfyUI execution may start NIM with a nonempty queue.
    if running or queue['queue_pending']:
        raise RuntimeError('Another ComfyUI job is active or queued. Automatic Maxine start refused.')


def require_local_docker():
    host = os.environ.get('DOCKER_HOST')
    if not host or os.environ.get('DOCKER_CONTEXT'):
        host = json.loads(subprocess.check_output(
            ['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}'], text=True, timeout=15))
    if not host.startswith('unix://'):
        raise RuntimeError('Automatic Maxine control requires a local Linux Docker socket, not a remote Docker context.')


def start_monitor():
    # One monitor wins its file lock. It survives a cancelled worker or ComfyUI exit.
    subprocess.Popen([sys.executable, str(ROOT / 'auto_service.py'), '--watch'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


@contextmanager
def managed_service(config, prompt_id=None, before_start=None, on_wait=None):
    if not settings(config):
        yield
        return
    require_local_docker()
    with service_activity(exclusive=True, timeout=120, on_wait=on_wait) as lock:
        require_job(prompt_id)
        info = container_info()
        if not info or info['status'] in ('created', 'exited'):
            if not (SERVICE / 'image.json').is_file() or not any(p.is_file() for p in (SERVICE / 'cache').rglob('*')):
                raise RuntimeError('Initialize Maxine once with service/start_service.py before enabling auto_service. Its pinned image and model cache are required.')
            if before_start:
                before_start()
            start_service.start_locked(cached_only=True, queue_check=lambda: require_job(prompt_id))
            info = container_info()
        if not info or info['status'] != 'running':
            raise RuntimeError('The Maxine container is not running. Check its Docker status.')
        owned = instance(info)
        client = {'pid': os.getpid(), 'start': process_start(os.getpid())}
        save_state({'instance': owned, 'client': client, 'last_activity': time.time()})
        start_monitor()
        # Downgrade without releasing the shared NAS GPU-handoff lock.
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            yield
        finally:
            save_state({'instance': owned, 'client': client, 'last_activity': time.time()})


class IdleMonitor:
    def __init__(self):
        self.last_busy = time.time()

    def tick(self, config):
        options = settings(config)
        if not options:
            return False
        now = time.time()
        try:
            with service_activity(exclusive=True):
                if not STATE.exists():
                    return True
                state = json.loads(STATE.read_text(encoding='utf-8'))
                info = container_info()
                if not info or info['status'] != 'running' or instance(info) != state['instance']:
                    STATE.unlink(missing_ok=True)
                    return True  # Manual restart/stop cancels ownership of the old instance.
                try:
                    queue = start_service.comfy_queue()
                except OSError:
                    client = state.get('client')
                    if not client or process_start(client['pid']) == client['start']:
                        raise
                    queue = {'queue_running': [], 'queue_pending': []}
                if queue['queue_running'] or queue['queue_pending']:
                    self.last_busy = now
                    return True
                if now - max(state['last_activity'], self.last_busy) < options['idle_timeout_seconds']:
                    return True
                subprocess.run(['docker', 'stop', '--time', '45', state['instance']['id']],
                               check=True, stdout=subprocess.DEVNULL, timeout=65)
                STATE.unlink(missing_ok=True)
                logging.info('Maxine stopped after its idle timeout.')
        except RuntimeError:
            self.last_busy = now
            raise
        return True


def watch():
    with (SERVICE / 'auto-watch.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        handler = RotatingFileHandler(SERVICE / 'auto-service.log', maxBytes=131072, backupCount=1)
        logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
        monitor = IdleMonitor()
        while True:
            try:
                config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
                if not monitor.tick(config):
                    return
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                # Queue/API errors fail closed; a later poll retries without stopping work.
                monitor.last_busy = time.time()
                logging.debug('Idle check deferred: %s', type(exc).__name__)
            time.sleep(5)


if __name__ == '__main__' and sys.argv[1:] == ['--watch']:
    watch()
