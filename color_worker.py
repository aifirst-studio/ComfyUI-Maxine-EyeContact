"""CPU iris colour matching in the isolated client environment."""
import argparse
from itertools import zip_longest
from pathlib import Path

import av
import cv2
import mediapipe as mp

from install_iris_model import MODEL_SHA256
from iris_color import match_iris_color
from progress import ProgressWriter


def run(source, corrected, output, model, progress):
    import hashlib
    if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError('Install the pinned Iris model with install_client.py first.')
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model), delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1, min_face_detection_confidence=0.65, min_face_presence_confidence=0.65,
        min_tracking_confidence=0.65, output_face_blendshapes=True)
    if output.exists():
        raise FileExistsError('The iris output already exists.')
    count, matched = 0, 0
    try:
        with av.open(str(source)) as a, av.open(str(corrected)) as b, av.open(str(output), 'w') as destination, \
                mp.tasks.vision.FaceLandmarker.create_from_options(options) as source_detector, \
                mp.tasks.vision.FaceLandmarker.create_from_options(options) as output_detector:
            sa, sb = a.streams.video[0], b.streams.video[0]
            if (sa.width, sa.height, sa.average_rate) != (sb.width, sb.height, sb.average_rate):
                raise RuntimeError('Iris colour matching requires matching resolution and frame rate.')
            stream = destination.add_stream('libx264', rate=sb.average_rate)
            stream.width, stream.height = sb.width, sb.height
            # Lossless x264 selects High 4:4:4 Predictive, which normal browser
            # players cannot decode. CRF 1 retains very high quality in High/420.
            stream.pix_fmt = 'yuv420p'
            stream.options = {'crf': '1', 'preset': 'slow', 'profile': 'high', 'threads': '4'}
            stream.codec_context.colorspace = sb.codec_context.colorspace
            stream.codec_context.color_range = sb.codec_context.color_range
            for frame_a, frame_b in zip_longest(a.decode(sa), b.decode(sb)):
                if frame_a is None or frame_b is None:
                    raise RuntimeError('Frame count mismatch in iris colour matching.')
                source_rgb = frame_a.to_ndarray(format='rgb24')
                corrected_rgb = frame_b.to_ndarray(format='rgb24')
                def detect(detector, rgb):
                    scale = min(1, 1024 / max(rgb.shape[:2]))
                    small = cv2.resize(rgb, (round(rgb.shape[1]*scale), round(rgb.shape[0]*scale))) if scale < 1 else rgb
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
                    return detector.detect_for_video(image, round(count * 1000 / float(sb.average_rate)))
                original_result = detect(source_detector, source_rgb)
                corrected_result = detect(output_detector, corrected_rgb)
                if original_result.face_landmarks and corrected_result.face_landmarks:
                    # Closed eyes: skip the entire frame when either detector
                    # reports a blink. Matching chroma during a blink is unsafe.
                    scores = [score.score for result in (original_result, corrected_result)
                              for face in result.face_blendshapes for score in face
                              if score.category_name in ('eyeBlinkLeft', 'eyeBlinkRight')]
                    if not scores or max(scores) < 0.5:
                        corrected_rgb, eyes = match_iris_color(source_rgb, corrected_rgb,
                            original_result.face_landmarks[0], corrected_result.face_landmarks[0])
                        matched += int(eyes > 0)
                frame = av.VideoFrame.from_ndarray(corrected_rgb, format='rgb24')
                frame.pts, frame.time_base = count, 1 / sb.average_rate
                for packet in stream.encode(frame):
                    destination.mux(packet)
                count += 1
                progress.update(phase='iris_color', frames=count, matched_frames=matched)
            for packet in stream.encode():
                destination.mux(packet)
        progress.update(force=True, phase='complete', frames=count, matched_frames=matched)
        print(f'Iris colour matched in {matched}/{count} frames; uncertain or closed eyes were skipped.')
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source')
    parser.add_argument('--corrected')
    parser.add_argument('--output')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--progress-file')
    args = parser.parse_args()
    if args.check:
        import hashlib
        model = Path(__file__).resolve().parent / 'models/face_landmarker.task'
        if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError('Run install_client.py to install the pinned iris landmark model first.')
        print('Isolated iris colour runtime and model are available.')
        return
    if not all((args.source, args.corrected, args.output)):
        parser.error('--source, --corrected and --output are required.')
    run(Path(args.source), Path(args.corrected), Path(args.output),
        Path(__file__).resolve().parent / 'models/face_landmarker.task', ProgressWriter(args.progress_file))


if __name__ == '__main__':
    main()
