import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
try:
    import av
    import numpy as np
except ImportError:
    av = None


@unittest.skipUnless(av is not None and (ROOT / 'models/face_landmarker.task').is_file(), 'Full isolated iris setup is required.')
class ColorWorkerTests(unittest.TestCase):
    def test_no_face_clip_preserves_frames_rate_resolution_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'source.mp4', root / 'output.mp4'
            with av.open(str(source), 'w') as container:
                stream = container.add_stream('libx264', rate=25)
                stream.width, stream.height, stream.pix_fmt = 320, 240, 'yuv420p'
                stream.options = {'crf': '1'}
                for _ in range(5):
                    frame = av.VideoFrame.from_ndarray(np.full((240,320,3), (90,130,170), dtype=np.uint8), format='rgb24')
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            args = [sys.executable, str(ROOT / 'color_worker.py'), '--source', str(source),
                    '--corrected', str(source), '--output', str(output), '--progress-file', str(root / 'progress.json')]
            completed = subprocess.run(args, capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with av.open(str(output)) as container:
                stream = container.streams.video[0]
                self.assertEqual((stream.width,stream.height,stream.average_rate), (320,240,25))
                self.assertEqual(len(list(container.decode(stream))), 5)
            status = json.loads((root / 'progress.json').read_text())
            self.assertEqual(status['frames'], 5)
            self.assertEqual(status['matched_frames'], 0)
            before = output.read_bytes()
            completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
