"""Coordinate local video requests with service control.

POSIX uses shared request/exclusive control locks (NAS controller compatible).
Windows uses one exclusive byte lock for both operations, serializing requests.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import time

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

LOCK_PATH = Path(__file__).resolve().parent / 'service/activity.lock'


@contextmanager
def service_activity(exclusive=False, timeout=0, on_wait=None):
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open('a+') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    if lock.tell() == 0:
                        lock.write('0')
                        lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Maxine is processing video or its service is being controlled. Try again when it is idle.') from exc
                if on_wait:
                    on_wait()
                time.sleep(0.25)
        try:
            yield lock
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
