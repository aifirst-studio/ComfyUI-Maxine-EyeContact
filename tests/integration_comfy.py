from fractions import Fraction
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

parser = argparse.ArgumentParser(description='CPU media integration against an actual ComfyUI checkout; no NVIDIA model.')
parser.add_argument('--comfy-root', required=True)
parser.add_argument('--report')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
COMFY = Path(args.comfy_root).resolve()
sys.path.insert(0, str(COMFY))
import comfy.cli_args
comfy.cli_args.args.cpu = True
import folder_paths
from comfy_api.latest import InputImpl
from comfy_api.latest._util import VideoContainer, VideoCodec
spec = importlib.util.spec_from_file_location('maxine_eye_contact_test', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
nodes = sys.modules[spec.name + '.nodes']
node = module.NODE_CLASS_MAPPINGS['MaxineEyeContact']()
config_path = ROOT / 'config.json'
original_config = config_path.read_text()
config = json.loads(original_config)
worker_python = config['client_python']
ffmpeg = nodes.imageio_ffmpeg.get_ffmpeg_exe()


def command(args):
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *args], check=True)


def audio_hash(path):
    with nodes.av.open(str(path)) as container:
        stream = container.streams.audio[0]
        return hashlib.sha256(b''.join(bytes(packet) for packet in container.demux(stream) if packet.size)).hexdigest()


mock_code = '''
from concurrent import futures
import sys
sys.path.insert(0, sys.argv[1])
import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from nvidia.maxine.eyecontact.v1 import eyecontact_pb2 as pb, eyecontact_pb2_grpc as rpc
class Echo(rpc.MaxineEyeContactServiceServicer):
 def RedirectGaze(self, requests, context):
  first=next(requests)
  yield pb.RedirectGazeResponse(config=first.config)
  for request in requests:
   yield pb.RedirectGazeResponse(video_file_data=request.video_file_data)
server=grpc.server(futures.ThreadPoolExecutor(max_workers=2))
rpc.add_MaxineEyeContactServiceServicer_to_server(Echo(),server)
h=health.HealthServicer(); h.set('',health_pb2.HealthCheckResponse.SERVING)
health_pb2_grpc.add_HealthServicer_to_server(h,server)
port=server.add_insecure_port('127.0.0.1:0'); server.start()
print(port,flush=True); server.wait_for_termination()
'''
mock = subprocess.Popen([worker_python, '-u', '-c', mock_code, str(ROOT / 'interfaces')], stdout=subprocess.PIPE, text=True)
port = int(mock.stdout.readline().strip())
config['target'] = f'127.0.0.1:{port}'
config_path.write_text(json.dumps(config))
report = {'model_inference': False, 'backend': 'local mock gRPC echo', 'checks': {}}
results = []
progress_values = []
import comfy.utils
original_hook = comfy.utils.PROGRESS_BAR_HOOK
def progress_hook(value, total, preview, node_id=None):
    if node_id == 'maxine-test':
        progress_values.append(value)
comfy.utils.PROGRESS_BAR_HOOK = progress_hook
def correct(*args, **kwargs):
    progress_values.clear()
    preserve_iris_color = kwargs.pop('preserve_iris_color', False)
    result = node.correct(*args, **kwargs, unique_id='maxine-test', preserve_iris_color=preserve_iris_color)
    assert progress_values and progress_values[-1] == 1000, progress_values
    assert progress_values == sorted(progress_values), 'Progress moved backwards'
    return result
try:
    with tempfile.TemporaryDirectory(prefix='maxine-media-test-') as directory:
        job = Path(directory)
        video_file = job / 'source.mp4'
        command(['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=30000/1001:d=2', '-f', 'lavfi',
                 '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-c:v', 'libx264',
                 '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video_file)])
        output, = correct(InputImpl.VideoFromFile(str(video_file)))
        results.append(Path(output.get_stream_source()))
        before, after = nodes.media_info(video_file), nodes.media_info(results[-1])
        assert (before['width'],before['height'],before['frames'],before['fps']) == (after['width'],after['height'],after['frames'],after['fps']), (before,after)
        assert audio_hash(video_file) == audio_hash(results[-1]), 'AAC source packets were modified'
        report['checks']['29.97fps_resolution_frame_count_AAC_packet_identity'] = True
        trimmed = InputImpl.VideoFromFile(str(video_file), start_time=0.3, duration=0.7)
        output, = correct(trimmed, natural_lookaway=True, lossless_output=False)
        results.append(Path(output.get_stream_source()))
        after = nodes.media_info(results[-1])
        assert after['frames'] in (20,21,22), after
        assert after['audio_codec'], 'Trimmed output has no audio'
        report['checks']['native_trim_and_audio'] = True
        cropped = InputImpl.VideoFromFile(str(video_file)).as_cropped(x=16, y=8, width=160, height=120)
        output, = correct(cropped)
        results.append(Path(output.get_stream_source()))
        after = nodes.media_info(results[-1])
        assert (after['width'],after['height']) == (160,120), after
        report['checks']['native_crop'] = True
        components = InputImpl.VideoFromFile(str(video_file),duration=0.25).get_components()
        output, = correct(InputImpl.VideoFromComponents(components))
        results.append(Path(output.get_stream_source()))
        assert nodes.media_info(results[-1])['audio_codec']
        report['checks']['native_VIDEO_from_components'] = True
        odd = job / 'odd.mkv'
        command(['-f', 'lavfi', '-i', 'testsrc=s=321x241:r=25:d=0.5', '-c:v', 'ffv1', str(odd)])
        output, = correct(InputImpl.VideoFromFile(str(odd)))
        results.append(Path(output.get_stream_source()))
        after = nodes.media_info(results[-1])
        assert (after['width'],after['height']) == (321,241), after
        assert after['audio_codec'] is None
        report['checks']['odd_dimensions_and_no_audio'] = True
        pcm = job / 'pcm.mkv'
        command(['-i',str(video_file),'-c:v','copy','-c:a','pcm_s16le',str(pcm)])
        output, = correct(InputImpl.VideoFromFile(str(pcm)))
        results.append(Path(output.get_stream_source()))
        assert nodes.media_info(results[-1])['audio_codec'] == 'aac'
        report['checks']['PCM_to_AAC_audio'] = True
        large = job / '4k.mp4'
        command(['-f','lavfi','-i','testsrc2=s=3840x2160:r=25:d=0.24',
                 '-c:v','libx264','-preset','ultrafast','-crf','18','-profile:v','high',
                 '-pix_fmt','yuv420p','-threads','4','-movflags','+faststart',str(large)])
        output, = correct(InputImpl.VideoFromFile(str(large)))
        results.append(Path(output.get_stream_source()))
        after = nodes.media_info(results[-1])
        assert (after['width'],after['height'],after['frames']) == (3840,2160,6), after
        report['checks']['4K_original_resolution_no_downscale'] = True
        report['checks']['native_progress_monotonic_and_finishes'] = True
        counter_spec = importlib.util.spec_from_file_location('mp4_counter', ROOT / 'frame_progress.py')
        counter_module = importlib.util.module_from_spec(counter_spec)
        counter_spec.loader.exec_module(counter_module)
        for fragmented in (False, True):
            clip = job / ('fragmented.mp4' if fragmented else 'faststart.mp4')
            command(['-i', str(video_file), '-c:v','copy','-an','-movflags',
                     '+frag_keyframe+empty_moov+default_base_moof' if fragmented else '+faststart', str(clip)])
            counter = counter_module.MP4FrameCounter()
            with clip.open('rb') as stream:
                while chunk := stream.read(113):
                    counter.feed(chunk)
            assert counter.available and counter.frames == before['frames'], (fragmented, counter.frames)
        report['checks']['real_MP4_metadata_frame_progress'] = True
        types = node.INPUT_TYPES()
        assert types['optional']['input_quality'][1]['default'] == 'Maximum (CRF 1)'
        assert types['optional']['temporal_filtering'][1]['default'] is True
        assert types['required']['lossless_output'][1]['default'] is True
        report['checks']['maximum_quality_defaults'] = True
        if (ROOT / 'models/face_landmarker.task').is_file():
            output, = correct(InputImpl.VideoFromFile(str(video_file)), preserve_iris_color=True)
            results.append(Path(output.get_stream_source()))
            after = nodes.media_info(results[-1])
            assert (after['width'],after['height'],after['frames'],after['fps']) == (before['width'],before['height'],before['frames'],before['fps'])
            assert audio_hash(video_file) == audio_hash(results[-1])
            report['checks']['node_with_iris_color_pipeline_and_AAC_packet_identity'] = True
        config['target']='example.com:8001'; config_path.write_text(json.dumps(config))
        try:
            node.correct(InputImpl.VideoFromFile(str(video_file)))
        except ValueError as error:
            assert 'localhost' in str(error)
        else:
            raise AssertionError('Nonlocal video upload was accepted')
        report['checks']['localhost_only'] = True
        original_interrupt = nodes.comfy.model_management.throw_exception_if_processing_interrupted
        def interrupt():
            raise RuntimeError('test interrupt')
        nodes.comfy.model_management.throw_exception_if_processing_interrupted = interrupt
        started = time.monotonic()
        try:
            nodes.run_process([sys.executable,'-c','import time;time.sleep(20)'],30)
        except RuntimeError as error:
            assert 'test interrupt' in str(error)
        else:
            raise AssertionError('Cancellation ignored')
        finally:
            nodes.comfy.model_management.throw_exception_if_processing_interrupted = original_interrupt
        assert time.monotonic() - started < 6
        report['checks']['cancellation_stops_only_child_process'] = True
        print(json.dumps(report, indent=2))
        if args.report:
            Path(args.report).write_text(json.dumps(report, indent=2))
finally:
    comfy.utils.PROGRESS_BAR_HOOK = original_hook
    config_path.write_text(original_config)
    mock.terminate()
    mock.wait(timeout=5)
    for path in results:
        path.unlink(missing_ok=True)
