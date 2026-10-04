"""Stop only this local NIM, with queue and activity guards."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from activity import service_activity
from start_service import require_idle_comfy


def main():
    with service_activity(exclusive=True):
        require_idle_comfy()
        environment = os.environ.copy()
        environment['DOCKER_CONFIG'] = str(ROOT / '.docker')
        subprocess.run(['docker', 'compose', '--project-name', 'maxine-eye-contact',
                        '--env-file', str(ROOT / '.env'), '-f', str(ROOT / 'compose.yaml'),
                        'stop', 'eye-contact'], env=environment, check=True)


if __name__ == '__main__':
    main()
