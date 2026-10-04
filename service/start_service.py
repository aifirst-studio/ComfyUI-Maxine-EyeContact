import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from activity import service_activity


def require_idle_comfy():
    config_path = ROOT.parent / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    url = config.get('comfy_url', 'http://127.0.0.1:8188').rstrip('/')
    with urllib.request.urlopen(url + '/queue', timeout=10) as response:
        queue = json.load(response)
    if queue['queue_running'] or queue['queue_pending']:
        raise RuntimeError('ComfyUI has queued or running jobs. Start Maxine when these are finished.')


def require_host_gpu():
    result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                            capture_output=True, text=True, timeout=15)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError('The NVIDIA GPU is not available on Linux. Check host GPU ownership and drivers before starting Maxine.')


def start(cached_only=False, update_image=False):
    if sys.platform != 'linux':
        raise RuntimeError('Run the NIM service helper on its Linux host. The ComfyUI client can also run on Windows.')
    if not (ROOT / '.env').is_file():
        raise RuntimeError('Run configure_ngc.py first. No NGC key is configured.')
    with service_activity(exclusive=True):
        require_idle_comfy()
        require_host_gpu()
        environment = os.environ.copy()
        environment['DOCKER_CONFIG'] = str(ROOT / '.docker')
        (ROOT / 'cache').mkdir(exist_ok=True)
        (ROOT / 'cache').chmod(0o777)
        image_record = ROOT / 'image.json'
        if image_record.exists() and not update_image:
            environment['MAXINE_IMAGE'] = json.loads(image_record.read_text())['digest']
        image = 'nvcr.io/nim/nvidia/maxine-eye-contact:latest' if update_image else environment.get('MAXINE_IMAGE', 'nvcr.io/nim/nvidia/maxine-eye-contact:1.5.0')
        environment['MAXINE_IMAGE'] = image
        command = ['docker', 'compose', '--project-name', 'maxine-eye-contact', '--env-file', str(ROOT / '.env'),
                   '-f', str(ROOT / 'compose.yaml')]
        subprocess.run(command + ['config', '--quiet'], env=environment, check=True)
        cached = subprocess.run(['docker', 'image', 'inspect', image], env=environment,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not cached or update_image:
            if cached_only:
                raise RuntimeError('The pinned NVIDIA image is missing. Run start_service.py manually to download it first.')
            subprocess.run(command + ['pull', 'eye-contact'], env=environment, check=True)
        digests = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{json .RepoDigests}}', image],
                                                    env=environment, text=True))
        digest = next(value for value in digests if value.startswith('nvcr.io/nim/nvidia/maxine-eye-contact@'))
        image_record.write_text(json.dumps({'digest': digest}, indent=2) + '\n')
        environment['MAXINE_IMAGE'] = digest
        require_idle_comfy()
        require_host_gpu()
        subprocess.run(command + ['up', '-d', '--pull', 'never', '--no-build', 'eye-contact'], env=environment, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-wait', action='store_true', help='Return after container start; check readiness separately.')
    parser.add_argument('--cached-only', action='store_true', help='Refuse a missing image instead of downloading it during a console action.')
    parser.add_argument('--update-image', action='store_true', help='Explicitly pull latest and replace the pinned image when the queue is idle.')
    args = parser.parse_args()
    if args.cached_only and args.update_image:
        parser.error('--cached-only and --update-image cannot be combined.')
    start(args.cached_only, args.update_image)
    if args.no_wait:
        print('Maxine started. Models may still be loading. ComfyUI was not restarted.')
        return
    config = json.loads((ROOT.parent / 'config.json').read_text())
    client_python = config['client_python']
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        health = subprocess.run([client_python, str(ROOT.parent / 'worker.py'), '--target', config.get('target', '127.0.0.1:18061'), '--health', '--health-timeout', '2'],
                                capture_output=True, text=True, timeout=6)
        if health.returncode == 0:
            print('Maxine is ready. ComfyUI was not restarted.')
            return
        time.sleep(5)
    raise RuntimeError('Maxine started but is not ready after 10 minutes. Check docker logs maxine-eye-contact-nim.')


if __name__ == '__main__':
    main()
