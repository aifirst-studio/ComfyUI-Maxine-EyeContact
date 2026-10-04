from concurrent import futures
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from activity import service_activity
sys.path.insert(0, str(ROOT / 'interfaces'))
import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from nvidia.maxine.eyecontact.v1 import eyecontact_pb2 as pb, eyecontact_pb2_grpc as rpc


class EchoService(rpc.MaxineEyeContactServiceServicer):
    mode = 'echo'
    config = None

    def RedirectGaze(self, request_iterator, context):
        iterator = iter(request_iterator)
        first = next(iterator)
        assert first.WhichOneof('stream_input') == 'config'
        self.config = first.config
        yield pb.RedirectGazeResponse(config=first.config)
        yield pb.RedirectGazeResponse(keepalive={})
        if self.mode == 'error':
            context.abort(grpc.StatusCode.INTERNAL, 'test server failure')
        if self.mode == 'empty':
            list(iterator)
            return
        for request in iterator:
            assert request.WhichOneof('stream_input') == 'video_file_data'
            yield pb.RedirectGazeResponse(video_file_data=request.video_file_data)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        self.service = EchoService()
        rpc.add_MaxineEyeContactServiceServicer_to_server(self.service, self.server)
        status = health.HealthServicer()
        status.set('', health_pb2.HealthCheckResponse.SERVING)
        health_pb2_grpc.add_HealthServicer_to_server(status, self.server)
        port = self.server.add_insecure_port('127.0.0.1:0')
        self.target = f'127.0.0.1:{port}'
        self.server.start()
        self.temp = tempfile.TemporaryDirectory()
        self.job = Path(self.temp.name)
        self.source = self.job / 'input.mp4'
        self.source.write_bytes(bytes(range(256)) * 1000)
        self.output = self.job / 'output.mp4'
        self.settings = self.job / 'settings.json'
        self.settings.write_text(json.dumps({'detect_closure': 1, 'enable_lookaway': 1,
            'lookaway_interval_min': 90, 'output_video_encoding': {'lossless': True}}))

    def tearDown(self):
        self.server.stop(0).wait()
        self.temp.cleanup()

    def run_worker(self, extra=None):
        return subprocess.run([sys.executable, str(ROOT / 'worker.py'), '--target', self.target,
            '--input', str(self.source), '--output', str(self.output), '--settings', str(self.settings),
            '--timeout', '5', '--progress-file', str(self.job / 'progress.json'), *(extra or [])], capture_output=True, text=True, timeout=15)

    def test_protocol_chunking_and_configuration(self):
        result = self.run_worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source.read_bytes(), self.output.read_bytes())
        self.assertEqual(self.service.config.detect_closure, 1)
        self.assertEqual(self.service.config.lookaway_interval_min, 90)
        self.assertTrue(self.service.config.output_video_encoding.lossless)
        progress = json.loads((self.job / 'progress.json').read_text())
        self.assertEqual(progress['phase'], 'complete')
        self.assertEqual(progress['received_bytes'], self.source.stat().st_size)
        self.assertEqual(progress['sent_bytes'], self.source.stat().st_size)
        self.assertIsNone(progress['frames'], 'Arbitrary bytes must not be interpreted as video frames')

    def test_server_error_removes_partial_output(self):
        self.service.mode = 'error'
        result = self.run_worker()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertIn('test server failure', result.stderr)

    def test_empty_output_fails(self):
        self.service.mode = 'empty'
        result = self.run_worker()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertIn('no video data', result.stderr)

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'existing-output')
        result = self.run_worker()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_bytes(), b'existing-output')

    def test_remote_target_rejected(self):
        result = self.run_worker(['--target', 'example.com:8001'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Only a local', result.stderr)

    def test_service_control_lock_blocks_request(self):
        lock_path = ROOT / 'service/activity.lock'
        lock_path.parent.mkdir(exist_ok=True)
        with service_activity(exclusive=True):
            result = self.run_worker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('service is being controlled', result.stderr)
        self.assertIsNone(self.service.config)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
