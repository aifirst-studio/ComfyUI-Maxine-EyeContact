import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / "interfaces"))

import grpc
from google.protobuf.json_format import ParseDict
from grpc_health.v1 import health_pb2, health_pb2_grpc
from nvidia.maxine.eyecontact.v1 import eyecontact_pb2, eyecontact_pb2_grpc
from activity import service_activity
from frame_progress import MP4FrameCounter
from progress import ProgressWriter


def requests(input_path, settings, progress=None):
    config = ParseDict(settings, eyecontact_pb2.RedirectGazeConfig())
    yield eyecontact_pb2.RedirectGazeRequest(config=config)
    with Path(input_path).open("rb") as source:
        sent = 0
        while chunk := source.read(64 * 1024):
            yield eyecontact_pb2.RedirectGazeRequest(video_file_data=chunk)
            sent += len(chunk)
            if progress:
                progress.update(sent_bytes=sent)
        if progress:
            progress.update(force=True, sent_bytes=sent, upload_complete=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="127.0.0.1:18061")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--health-timeout", type=float, default=5)
    parser.add_argument('--wait-ready', action='store_true', help='Wait for real SERVING health after an automatic container start.')
    parser.add_argument('--ready-timeout', type=float, default=600)
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--settings")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--progress-file", help="Optional local status file; no video data or credentials.")
    args = parser.parse_args()
    if args.target.split(":", 1)[0] not in ("127.0.0.1", "localhost"):
        parser.error("Only a local Maxine endpoint is allowed.")
    if not 0 < args.health_timeout <= 10:
        parser.error("--health-timeout must be between 0 and 10 seconds.")
    if args.wait_ready and (not args.health or args.ready_timeout <= 0):
        parser.error('--wait-ready requires --health and a positive --ready-timeout.')
    if not args.health and not all((args.input, args.output, args.settings)):
        parser.error("--input, --output and --settings are required for inference.")
    if args.health:
        run_client(args)
    else:
        with service_activity():
            run_client(args)


def run_client(args):
    progress = ProgressWriter(args.progress_file)
    progress.update(force=True, phase="connecting")
    try:
        with grpc.insecure_channel(args.target) as channel:
            if args.wait_ready:
                wait_ready(channel, args.ready_timeout)
            grpc.channel_ready_future(channel).result(timeout=args.health_timeout if args.health else 10)
            health = health_pb2_grpc.HealthStub(channel).Check(health_pb2.HealthCheckRequest(), timeout=args.health_timeout)
            if health.status != health_pb2.HealthCheckResponse.SERVING:
                raise RuntimeError("The local Maxine service is not ready.")
            if args.health:
                print("Local Maxine service: SERVING")
                return
            settings = json.loads(Path(args.settings).read_text())
            stub = eyecontact_pb2_grpc.MaxineEyeContactServiceStub(channel)
            progress.update(force=True, phase="processing", total_bytes=Path(args.input).stat().st_size)
            response_stream = stub.RedirectGaze(requests(args.input, settings, progress), timeout=args.timeout)
            output = Path(args.output)
            destination = output.open("xb")
            counter = MP4FrameCounter()
            try:
                with destination:
                    for response in response_stream:
                        if response.WhichOneof("stream_output") == "video_file_data":
                            destination.write(response.video_file_data)
                            progress.update(received_bytes=counter.received + len(response.video_file_data),
                                            frames=counter.feed(response.video_file_data))
                if not output.stat().st_size:
                    raise RuntimeError("Maxine returned no video data.")
                progress.update(force=True, phase="complete", received_bytes=counter.received,
                                frames=counter.frames if counter.available else None)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    except grpc.FutureTimeoutError:
        raise RuntimeError("Local Maxine service is unavailable. Configure the NGC key and start the Eye Contact service first.") from None
    except grpc.RpcError as exc:
        raise RuntimeError(f"Maxine gRPC {exc.code().name}: {exc.details()}") from None


def wait_ready(channel, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = min(2, deadline - time.monotonic())
        try:
            health = health_pb2_grpc.HealthStub(channel).Check(health_pb2.HealthCheckRequest(), timeout=remaining)
            if health.status == health_pb2.HealthCheckResponse.SERVING:
                return
        except grpc.RpcError:
            pass  # NIM can accept connections before its models become ready.
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError('Maxine did not become ready before the startup timeout. Check docker logs maxine-eye-contact-nim.')


if __name__ == "__main__":
    main()
