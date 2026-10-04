"""Download a pinned CPU landmark model during setup, never during rendering."""
import hashlib
from pathlib import Path
import urllib.request

MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
MODEL_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'


def install():
    destination = Path(__file__).resolve().parent / 'models/face_landmarker.task'
    destination.parent.mkdir(exist_ok=True)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == MODEL_SHA256:
        return destination
    temporary = destination.with_suffix('.download')
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response, temporary.open('wb') as output:
            while chunk := response.read(65536):
                output.write(chunk)
                if output.tell() > 8 * 1024 * 1024:
                    raise RuntimeError('Unexpectedly large landmark model.')
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError('Landmark model checksum mismatch.')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    print(install())
