import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import av
import folder_paths
import imageio_ffmpeg
import comfy.model_management
from comfy_api.latest import InputImpl
from comfy_api.latest._util import VideoContainer, VideoCodec
from .node_progress import NodeProgress

ROOT = Path(__file__).resolve().parent


def run_process(command, timeout, on_poll=None):
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                comfy.model_management.throw_exception_if_processing_interrupted()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Maxine Eye Contact processing timed out.")
                if on_poll:
                    on_poll()
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        log.seek(0, os.SEEK_END)
        log.seek(max(0, log.tell() - 4000))
        output = log.read().decode("utf-8", errors="replace")
        if process.returncode:
            raise RuntimeError(f"Maxine Eye Contact: {output.strip()}")
        if on_poll:
            on_poll()
        return output


def media_info(path, on_frame=None):
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("The video file contains no video stream.")
        video = container.streams.video[0]
        audio = container.streams.audio[0] if container.streams.audio else None
        rate = video.average_rate
        count = 0
        previous = None
        cfr = True
        for frame in container.decode(video):
            comfy.model_management.throw_exception_if_processing_interrupted()
            count += 1
            if on_frame:
                on_frame(count, video.frames)
            if frame.pts is None or not rate:
                cfr = False
                continue
            timestamp = frame.pts * frame.time_base
            if previous is not None and abs(float(timestamp - previous) - 1 / float(rate)) > max(float(frame.time_base), 0.05 / float(rate)):
                cfr = False
            previous = timestamp
        if not count:
            raise ValueError("The video file contains no decodable frames.")
        return {
            "width": video.width,
            "height": video.height,
            "fps": video.average_rate,
            "frames": count,
            "audio_codec": audio.codec_context.name if audio else None,
            "codec": video.codec_context.name,
            "pixel_format": video.codec_context.format.name,
            "profile": video.codec_context.profile,
            "cfr": cfr,
        }


class MaxineEyeContact:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO", {"tooltip": "Original input resolution is preserved, including 4K. No resize limit is applied by this node. Upstream resizing cannot be undone. SDR only; the service/GPU must support the source size."}),
            "natural_lookaway": ("BOOLEAN", {"default": False, "tooltip": "Occasionally adds small eye movements away from the camera (up to 5 degrees) to soften a fixed stare. Off keeps continuous correction within NVIDIA's head/gaze range."}),
            "detect_closed_eyes": ("BOOLEAN", {"default": True, "tooltip": "Detects blinking, closed eyes and occlusion so correction can respect them. Recommended on for gaze redirection. Does not force closed eyes open."}),
            "eye_size_sensitivity": ("INT", {"default": 3, "min": 2, "max": 6, "tooltip": "Controls the eye-region area used to blend corrected eyes into the face. 2 = smaller area, 6 = larger area; start with 3. This is NOT eye enlargement or correction strength. Compare a short clip for blend edges/artifacts."}),
            "lossless_output": ("BOOLEAN", {"default": True, "tooltip": "Lossless H.264 encoding of Maxine's corrected frames; larger files. Off uses the bitrate below. Does not restore input compression, HDR or 10-bit detail. Resolution is unchanged in either mode."}),
        }, "optional": {
            "temporal_filtering": ("BOOLEAN", {"default": True, "tooltip": "Temporally filters eye-contact landmarks across consecutive frames to reduce jitter/flicker. On sends NVIDIA's default 0xffffffff; off sends 0. Usually leave on for recorded video."}),
            "input_quality": (["Maximum (CRF 1)", "High (CRF 14)"], {"default": "Maximum (CRF 1)", "tooltip": "Used only when input conversion is necessary. Maximum minimizes additional compression at the original resolution. Compatible H.264 is copied directly. Neither conversion mode is mathematically lossless."}),
            "lossy_bitrate_mbps": ("INT", {"default": 40, "min": 1, "max": 200, "tooltip": "Target output bitrate in Mbit/s, only when lossless_output is off. Higher values can retain more detail in large or moving images and produce larger files."}),
            "preserve_iris_color": ("BOOLEAN", {"default": True, "tooltip": "Experimental CPU postprocess: match detected iris colour to the source while retaining redirected gaze. Closed, tiny or uncertain eyes are skipped. Adds processing time and lossless RGB/YUV444 encoding. Cannot guarantee identity or exact colour in every frame."}),
        }, "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "correct"
    CATEGORY = "video/Maxine"
    DESCRIPTION = "Local NVIDIA Maxine Eye Contact: native VIDEO in/out, original resolution, frame rate and source audio. No downscaling. Hover over controls or open Parameter help for explanations. SDR/8-bit H.264 processing; NVIDIA NIM is installed separately."

    def correct(self, video, natural_lookaway=False, detect_closed_eyes=True,
                eye_size_sensitivity=3, lossless_output=True, input_quality="Maximum (CRF 1)",
                lossy_bitrate_mbps=40, temporal_filtering=True, preserve_iris_color=True, unique_id=None):
        progress = NodeProgress(unique_id)
        try:
            return self._correct(video, natural_lookaway, detect_closed_eyes,
                                 eye_size_sensitivity, lossless_output, input_quality,
                                 lossy_bitrate_mbps, temporal_filtering, preserve_iris_color, progress)
        except BaseException:
            progress.update(phase="error")
            raise

    def _correct(self, video, natural_lookaway, detect_closed_eyes,
                 eye_size_sensitivity, lossless_output, input_quality, lossy_bitrate_mbps, temporal_filtering, preserve_iris_color, progress):
        progress.update(0, "checking", indeterminate=True)
        config_path = ROOT / "config.json"
        if not config_path.is_file():
            raise RuntimeError("Run install_client.py with Python 3.11 or 3.12 to create the isolated Maxine client first.")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not 2 <= int(eye_size_sensitivity) <= 6:
            raise ValueError("eye_size_sensitivity must be between 2 and 6.")
        if input_quality not in ("Maximum (CRF 1)", "High (CRF 14)") or not 1 <= int(lossy_bitrate_mbps) <= 200:
            raise ValueError("Invalid encoding quality or bitrate.")
        worker_python = Path(config["client_python"])
        if not worker_python.is_file():
            raise RuntimeError("Install the isolated Maxine client with install_client.py first.")
        if video.get_color_space() in ("HDR", "HDR PQ"):
            raise ValueError("Maxine requires SDR video. Convert this HDR clip to SDR with tone mapping first.")
        fps = video.get_frame_rate()
        if fps <= 0:
            raise ValueError("The input video has no valid frame rate.")
        target = config.get("target", "127.0.0.1:18061")
        if target.split(":", 1)[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("This node only sends video to a local Maxine endpoint (localhost). Use an SSH tunnel for another host.")
        timeout = int(config.get("timeout_seconds", 1800))
        worker = [str(worker_python), str(ROOT / "worker.py"), "--target", target]
        run_process(worker + ["--health"], 20)
        if preserve_iris_color:
            run_process([str(worker_python), str(ROOT / "color_worker.py"), "--check"], 30)
        progress.update(20, "exporting", indeterminate=True)
        ffmpeg = config.get("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n"]
        temp_root = Path(folder_paths.get_temp_directory()) / "maxine-eye-contact"
        temp_root.mkdir(parents=True, exist_ok=True)
        result_path = temp_root / f"{uuid.uuid4().hex}.mp4"
        try:
            with tempfile.TemporaryDirectory(prefix="job-", dir=temp_root) as job:
                job = Path(job)
                source = job / "source.mkv"
                prepared = job / "input.mp4"
                redirected = job / "redirected.mp4"
                # Respect native VIDEO trims and crops rather than reopening the raw source.
                direct_source = None
                if isinstance(video, InputImpl.VideoFromFile):
                    raw_source = video.get_stream_source()
                    start, duration = video.get_active_trim_window()
                    if isinstance(raw_source, str) and not start and not duration:
                        if video.get_dimensions() == InputImpl.VideoFromFile(raw_source).get_dimensions():
                            direct_source = Path(raw_source)
                if direct_source is not None:
                    source = direct_source
                else:
                    video.save_to(str(source), format=VideoContainer.AUTO, codec=VideoCodec.H264,
                                  crf=1 if input_quality == "Maximum (CRF 1)" else 14,
                                  bit_depth=8, preset="slow")
                progress.update(50, "reading", indeterminate=True)
                original = media_info(source, progress.scan(50, 100, "reading"))
                width, height = video.get_dimensions()
                progress.update(100, "preparing", width=width, height=height,
                                total_frames=original["frames"], fps=float(fps))
                can_copy = original["codec"] == "h264" and original["pixel_format"] == "yuv420p" and original["cfr"] and original["profile"] in ("High", "Main", "Baseline", "Constrained Baseline") and not (width % 2 or height % 2) and (width, height) == (original["width"], original["height"])
                if can_copy:
                    preparation = ["-c:v", "copy"]
                else:
                    preparation = ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-r", str(fps),
                        "-fps_mode", "cfr", "-frames:v", str(original["frames"]), "-c:v", "libx264",
                        "-preset", "fast", "-crf", "1" if input_quality == "Maximum (CRF 1)" else "14", "-profile:v", "high", "-pix_fmt", "yuv420p", "-threads", "4"]
                prep_progress = job / "prepare.progress"
                run_process(ffmpeg_base + ["-progress", str(prep_progress), "-i", str(source), "-map", "0:v:0", "-an",
                            *preparation, "-movflags", "+faststart", str(prepared)], timeout,
                            progress.ffmpeg(prep_progress, original["frames"], 100, 190, "preparing"))
                prepared_info = media_info(prepared)
                settings = {
                    "temporal": 0xFFFFFFFF if temporal_filtering else 0,
                    "detect_closure": int(detect_closed_eyes),
                    "eye_size_sensitivity": int(eye_size_sensitivity),
                    "enable_lookaway": int(natural_lookaway),
                    "lookaway_max_offset": 5,
                    "lookaway_interval_min": min(600, max(1, round(float(fps) * 3))),
                    "lookaway_interval_range": min(600, max(1, round(float(fps) * 8))),
                    "gaze_pitch_threshold_low": 20.0, "gaze_pitch_threshold_high": 30.0,
                    "gaze_yaw_threshold_low": 20.0, "gaze_yaw_threshold_high": 30.0,
                    "head_pitch_threshold_low": 15.0, "head_pitch_threshold_high": 25.0,
                    "head_yaw_threshold_low": 25.0, "head_yaw_threshold_high": 30.0,
                    "enable_multi_person": 0,
                    "output_video_encoding": {"lossless": True} if lossless_output else {"lossy": {"bitrate": int(lossy_bitrate_mbps) * 1000000, "idr_interval": 8}},
                }
                settings_path = job / "settings.json"
                settings_path.write_text(json.dumps(settings))
                inference_progress = job / "inference.progress"
                progress.update(200, "processing", fraction=None, indeterminate=True)
                run_process(worker + ["--input", str(prepared), "--output", str(redirected),
                            "--settings", str(settings_path), "--timeout", str(timeout),
                            "--progress-file", str(inference_progress)], timeout + 15,
                            progress.inference(inference_progress, prepared_info["frames"]))
                progress.update(800, "validating")
                corrected_info = media_info(redirected, progress.scan(800, 880, "validating", prepared_info["frames"]))
                if any(corrected_info[key] != prepared_info[key] for key in ("width", "height", "frames")):
                    raise RuntimeError("Maxine changed the resolution or frame count; output was not accepted.")
                if abs(float(corrected_info["fps"]) - float(prepared_info["fps"])) > 0.001:
                    raise RuntimeError("Maxine changed the frame rate; output was not accepted.")
                mux_start, mux_end = 880, 940
                if preserve_iris_color:
                    colour_path = job / "iris-matched.mp4"
                    colour_progress = job / "iris.progress"
                    progress.update(880, "iris_color", fraction=0)
                    run_process([str(worker_python), str(ROOT / "color_worker.py"),
                                "--source", str(prepared), "--corrected", str(redirected),
                                "--output", str(colour_path), "--progress-file", str(colour_progress)], timeout,
                                progress.stream_frames(colour_progress, prepared_info["frames"], 880, 930, "iris_color"))
                    redirected = colour_path
                    mux_start, mux_end = 930, 960
                video_args = ["-c:v", "copy"]
                if width % 2 or height % 2:
                    video_args = ["-vf", f"crop={width}:{height}:0:0:exact=1", "-c:v", "libx264",
                                  "-crf", "0", "-preset", "fast", "-pix_fmt", "yuv444p", "-threads", "4"]
                audio_args = ["-c:a", "copy"] if original["audio_codec"] in (None, "aac", "mp3", "ac3", "alac") else ["-c:a", "aac", "-b:a", "256k"]
                mux_progress = job / "mux.progress"
                progress.update(mux_start, "audio")
                run_process(ffmpeg_base + ["-progress", str(mux_progress), "-i", str(redirected), "-i", str(source),
                            "-map", "0:v:0", "-map", "1:a:0?", *video_args, *audio_args,
                            "-map_metadata", "-1", "-movflags", "+faststart", str(result_path)], timeout,
                            progress.ffmpeg(mux_progress, prepared_info["frames"], mux_start, mux_end, "audio"))
                final_info = media_info(result_path, progress.scan(mux_end, 999, "final_check", prepared_info["frames"]))
                if (final_info["width"], final_info["height"]) != (width, height):
                    raise RuntimeError("The final output dimensions do not match the source.")
                if original["audio_codec"] and not final_info["audio_codec"]:
                    raise RuntimeError("The final output is missing source audio.")
                if final_info["frames"] != prepared_info["frames"]:
                    raise RuntimeError("The final output frame count does not match the processed clip.")
        except BaseException:
            result_path.unlink(missing_ok=True)
            raise
        progress.update(1000, "complete", fraction=1, frames=final_info["frames"], indeterminate=False)
        return (InputImpl.VideoFromFile(str(result_path)),)
