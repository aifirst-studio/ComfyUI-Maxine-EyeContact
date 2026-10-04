import json
import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--skip-iris-color', action='store_true', help='Install the gRPC client only; disable preserve_iris_color in the node.')
args = parser.parse_args()
if not (3, 11) <= sys.version_info[:2] <= (3, 12):
    raise SystemExit('Use Python 3.11 or 3.12 for this isolated client installer. ComfyUI can use a different Python.')
runtime = ROOT / "runtime"
if not runtime.exists():
    venv.EnvBuilder(with_pip=True).create(runtime)
python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements-client.txt")], check=True)
if not args.skip_iris_color:
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(ROOT / 'requirements-color.txt')], check=True)
    from install_iris_model import install
    install()
interfaces = ROOT / "interfaces"
interfaces.mkdir(exist_ok=True)
include = subprocess.check_output([str(python), "-c", "import grpc_tools,pathlib; print(pathlib.Path(grpc_tools.__file__).parent / '_proto')"], text=True).strip()
proto_root = ROOT / "protos"
subprocess.run([str(python), "-m", "grpc_tools.protoc", "-I" + str(proto_root), "-I" + include,
                "--python_out=" + str(interfaces), "--grpc_python_out=" + str(interfaces),
                *[str(p) for p in sorted(proto_root.rglob("*.proto"))]], check=True)
config_path = ROOT / "config.json"
config = json.loads(config_path.read_text()) if config_path.exists() else {"target": "127.0.0.1:18061", "timeout_seconds": 1800}
config["client_python"] = str(python)
config_path.write_text(json.dumps(config, indent=2) + "\n")
activity_lock = ROOT / "service/activity.lock"
activity_lock.touch(exist_ok=True)
activity_lock.chmod(0o600)
print("Isolated Maxine client installed. ComfyUI dependencies were not modified.")
