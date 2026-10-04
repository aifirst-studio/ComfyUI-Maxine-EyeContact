import getpass
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
os.umask(0o077)
key = getpass.getpass("NGC Personal API Key (hidden): ").strip()
if not key or "\n" in key or "\r" in key:
    raise SystemExit("No valid key entered.")
config = ROOT / ".docker"
config.mkdir(mode=0o700, exist_ok=True)
result = subprocess.run(["docker", "--config", str(config), "login", "nvcr.io", "--username", "$oauthtoken", "--password-stdin"],
                        input=key, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if result.returncode:
    raise SystemExit("NGC login failed. Check the key, NGC Catalog access and NVIDIA download conditions.")
env_file = ROOT / ".env"
fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as file:
    file.write("NGC_API_KEY=" + key + "\n")
env_file.chmod(0o600)
print("NGC access configured. Key stored privately; no service was started.")
