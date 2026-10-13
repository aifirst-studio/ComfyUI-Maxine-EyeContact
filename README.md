# ComfyUI Maxine Eye Contact

Local eye-contact correction for recorded video using **NVIDIA Maxine Eye Contact NIM**.

**Early beta (0.1.2).** The tested configurations and remaining verification limits are listed below.

**Load Video → NVIDIA Maxine Eye Contact (Local) → Save Video**

- Native ComfyUI `VIDEO` input/output, original resolution and frame rate, source audio.
- Maximum-quality defaults: lossless NIM output, CRF 1 when conversion is necessary, temporal filtering and closed-eye detection enabled.
- ComfyUI progress bar, stage status, elapsed time, received-frame count where MP4 metadata supports it, and English/German parameter help inside the node.
- Experimental CPU iris-colour matching to reduce colour changes introduced by gaze redirection; on by default, with conservative skip conditions.
- Isolated gRPC environment: no protobuf/gRPC changes in ComfyUI's Python environment.

This is an independent MIT-licensed integration, not an NVIDIA product. No model weights are included. NVIDIA NGC access and NVIDIA's NIM/model terms apply separately.

## Requirements

The node targets recent ComfyUI with native `VIDEO` and the `comfy_api.latest` video exporter; integration was checked against ComfyUI 0.37.0. Legacy VHS `IMAGE` batches are not a direct input: create a native `VIDEO` first.

The isolated client requires Python **3.11 or 3.12**. ComfyUI can use a different Python. The client works on Linux and Windows; the bundled NIM service helpers run on **Linux** with Docker Compose, NVIDIA Container Toolkit, a supported GPU with NVENC/NVDEC and an NGC Personal API Key with NGC Catalog access. See NVIDIA's [support matrix](https://docs.nvidia.com/nim/maxine/eye-contact/1.5.0/support-matrix.html).

NIM **1.5.0** is the default service version. The downloaded image is pinned by digest. An explicit update command can select the currently published `latest` image. First model loading/warm-up can take longer than subsequent requests.

## Install

In ComfyUI-Manager, search for **Maxine Eye Contact (Local)** or the Registry ID `maxine-eye-contact`. Published Registry versions appear on the [Registry listing](https://registry.comfy.org/nodes/maxine-eye-contact). The legacy Manager catalogue submission is [PR #3374](https://github.com/Comfy-Org/ComfyUI-Manager/pull/3374); availability in that list depends on its acceptance. If the package is not listed yet, use Manager's **Install via Git URL** with `https://github.com/aifirst-studio/ComfyUI-Maxine-EyeContact`, or install this repository manually.

**Manager installs the node and its small ComfyUI dependency only.** It does not configure the isolated client, NVIDIA NIM, Docker/GPU access, NGC credentials or Linux system libraries. Complete steps 3–5 below after a Manager install. There is no runtime pip installation, automatic service startup or automatic NVIDIA model download in the node.

1. Put this project in `ComfyUI/custom_nodes/ComfyUI-Maxine-EyeContact`. Registry installs may instead use `custom_nodes/maxine-eye-contact`; run the remaining setup commands from the actual installed directory.
2. In **ComfyUI's Python**, install the small FFmpeg helper:

   ```sh
   python -m pip install -r requirements.txt
   ```

3. On Debian/Ubuntu, the CPU iris-colour step also needs MediaPipe's EGL/GLES shared libraries, including on headless hosts:

   ```sh
   sudo apt-get update
   sudo apt-get install -y --no-install-recommends libegl1 libgles2
   ```

   Windows does not need this system-package step. From the project directory, create the isolated client:

   ```sh
   # Linux, using Python 3.11 or 3.12
   python3 install_client.py
   # Windows: select an installed Python 3.12
   py -3.12 install_client.py
   ```

   This creates `runtime/`, generates `interfaces/` from the vendored NVIDIA protocol, installs the isolated CPU iris-colour dependencies and downloads a checksum-pinned 3.8 MB MediaPipe landmark model. It writes `config.json` and preserves existing settings. No models are downloaded during rendering. Do not copy `config.example.json` over the installer-generated file: its Python path is a placeholder. For gRPC only, use `--skip-iris-color` and turn `preserve_iris_color` off in the node.

4. Restart ComfyUI when its queue is empty. Load `workflows/Maxine Eye Contact.json` and choose a video in Load Video.
5. Start the NIM service before running the workflow. Set **Save Video: format auto / codec auto** to retain the returned stream.

### Start the Linux NIM service

Create an NGC key via [NGC API keys](https://org.ngc.nvidia.com/setup/api-keys) and follow NVIDIA's [Eye Contact deployment instructions](https://build.nvidia.com/nvidia/eyecontact/deploy). Keep the key out of widgets, workflow files and Git history.

With ComfyUI running and its queue empty:

```sh
python3 service/configure_ngc.py
python3 service/start_service.py
# Later, stop only this service:
python3 service/stop_service.py
```

The first command prompts privately, uses a separate Docker login directory, and writes `service/.env` with mode 600. Startup checks the queue and GPU, pulls the image if needed, records its digest, starts only this Compose project, and waits for readiness. It never restarts ComfyUI. Container restart policy is `no`.

Defaults: GPU 0, concurrency 1, HTTP `127.0.0.1:18060`, gRPC `127.0.0.1:18061`. Compose supports `MAXINE_GPU_ID`, `MAXINE_HTTP_PORT`, and `MAXINE_GRPC_PORT`; after changing the gRPC port, change `config.json.target` accordingly. Optional `config.json.comfy_url` changes the queue-check URL. The service cache is writable by the container's model-loading user and contains downloaded models, not the key.

Explicitly update to NVIDIA's latest image only when the queue is empty:

```sh
python3 service/start_service.py --update-image
```

This can recreate a running idle NIM container. Normal starts retain the pinned version. `--cached-only --no-wait` is available for existing service consoles. The Linux `service/activity.lock` uses shared request/exclusive control locking; preserve its inode while installing updates. Service actions are refused while a local request is active.

### Windows client / another Linux host

The Windows node uses the same isolated client and connects to localhost. Run NIM separately on a supported Linux Docker host. For a different machine, keep its ports bound to localhost and forward the gRPC port with an SSH tunnel:

```sh
ssh -N -L 18061:127.0.0.1:18061 user@linux-host
```

The node intentionally accepts only localhost endpoints. This avoids sending video to a network/cloud endpoint by accident. Windows byte locks serialize client requests; Linux locks on a separate service host cannot coordinate a Windows client's activity. Manage that host's service only while all clients are idle. WSL/Docker Desktop GPU deployment is not verified by this project; this integration does not bundle the native Windows AR SDK.

## Parameters

| Control | Default | Meaning |
| --- | --- | --- |
| `eye_size_sensitivity` | 3 | 2–6 adjusts the eye-region blending area: lower is smaller, higher larger. It does **not** enlarge eyes or change correction strength. |
| `detect_closed_eyes` | On | Enables NVIDIA `detect_closure` for blinks, closed eyes and occlusion. Recommended for gaze redirection; does not open closed eyes. |
| `temporal_filtering` | On | NVIDIA `temporal=0xffffffff`; optimizes landmarks over consecutive frames to reduce jitter. Off sends 0. |
| `natural_lookaway` | Off | Occasional small gaze changes up to 5°, rather than continuous camera gaze within the supported head/gaze range. |
| `lossless_output` | On | Lossless H.264 encoding of corrected NIM frames. Larger files. |
| `input_quality` | Maximum (CRF 1) | Conversion quality when necessary. High (CRF 14) uses smaller intermediate files. Compatible H.264 sources are copied directly. |
| `lossy_bitrate_mbps` | 40 | Target bitrate only when lossless output is off. |
| `preserve_iris_color` | On | Experimental iris-only colour matching from the source, retaining redirected gaze and texture. Skips uncertain, tiny or closed eyes. Adds CPU time. |

Hover tooltips and expand **Parameter help** in the node. Explanations follow NVIDIA's [feature parameter documentation](https://docs.nvidia.com/nim/maxine/eye-contact/1.5.0/advanced-usage.html).

## Resolution and quality

There is **no resolution cap or downscaling** in this node. It sends the original input dimensions to NIM and rejects outputs that unexpectedly change dimensions, frame count or frame rate. Odd dimensions are padded to even sizes for H.264 and restored afterward. A preceding resize node changes the input resolution; this node cannot recover lost detail.

Restoring an odd width or height requires a separate H.264 High 4:4:4 Predictive/YUV444 encode to retain the exact dimensions. That output has limited browser/Windows-player compatibility, including when iris-colour matching is on. Use even dimensions for the compatible High/YUV420 colour export.

3840×2160 media handling is covered by a CPU test with a mock NIM. This is **not** evidence that NVIDIA inference succeeds at 4K on every GPU. Resolution limits, memory and NVENC/NVDEC support belong to the service/GPU; failures are reported rather than silently downscaled.

NIM needs constant-frame-rate **8-bit SDR H.264**. Compatible YUV420 H.264 is copied. Other inputs are converted at the original resolution; VFR is normalized to the declared frame rate. Native VIDEO crops/trims/components are exported at the selected high quality. HDR is rejected until explicitly tone-mapped upstream. 10-bit SDR is converted to 8-bit. CRF 1 is very high quality, **not mathematically lossless**; lossless output does not undo these input limitations.

The first source audio track is restored separately. AAC/MP3/AC3/ALAC packets are copied where possible; other codecs become AAC at 256 kbit/s. Native transformed VIDEO may already have re-encoded its audio during export. Metadata is not copied into the final media. Errors do not fall back to an uncorrected clip.

### Iris-colour changes

NIM can change iris appearance when synthesizing redirected eyes. Its gRPC configuration has no iris-colour preservation control. `eye_size_sensitivity` changes blending area, not colour. This project adds a separate, **experimental** postprocess that detects source/output irises with MediaPipe on the CPU, matches their Lab colour statistics inside a feathered iris ring, and keeps the redirected pupil location. Pupil centres, white reflections and surrounding skin are excluded from the colour blend as far as the masks permit.

This does not restore exact source texture, guarantee identity, or reliably handle every blink, reflection, tiny face or occlusion. Frames with uncertain detection are left with NIM's corrected appearance; the status reports the number matched. Compare a short clip before processing important footage. The step exports H.264 High/YUV420 at CRF 1 with a slow encoder preset, retaining original resolution and frame rate. This is very high quality, **not mathematically lossless**, even with lossless NIM output selected. Lossless x264 uses High 4:4:4 Predictive, which breaks playback in common browser/Windows players; the colour step intentionally uses a compatible profile. RGB/YUV conversion and chroma subsampling also involve rounding. Disable colour matching to receive the standard NIM stream without this additional encode.

## Progress

ComfyUI's native bar reports ordered processing stages. The in-node bar shows progress within the current stage. FFmpeg conversion/muxing and validation use actual frame counts. During NIM streaming, the client counts complete encoded video samples whose data have actually arrived, using normal or fragmented MP4 metadata. It does not equate upload bytes with model inference completion.

If output metadata is unsupported or not yet present, the in-node bar remains indeterminate and shows elapsed time, upload progress and received bytes. NVIDIA's gRPC protocol provides no independent per-frame inference percentage. The stage weights are not a time estimate. Cancellation terminates only the node's own worker process; it leaves the service available.

## Tests and verification limits

```sh
# Linux
runtime/bin/python -m unittest discover -s tests -v
# Windows
runtime/Scripts/python.exe -m unittest discover -s tests -v
node tests/test_ui.mjs
```

These tests cover streaming/protocol errors, partial-output cleanup, existing-file preservation, localhost enforcement, service/request locks, startup guards, MP4 progress parsing and frontend status/help behavior. They need no GPU or NGC key.
With the full client installed, they also test iris matching, skipped blinks/missing landmarks, unchanged pupil positions/skin regions, and the actual CPU colour-worker encoding path. A gRPC-only installation skips colour tests.

All 22 CPU tests and the frontend tests passed on Linux and Windows. Real NIM output and the corrected colour export were checked at 1440×2560, 30 fps on a Linux host with an RTX 3090. The Windows client has CPU test coverage; a Windows-to-Linux NIM workflow has not been verified end to end. Real 4K inference and other GPU configurations remain unverified.

CPU media integration against an actual ComfyUI checkout:

```sh
/path/to/comfy/python tests/integration_comfy.py --comfy-root /path/to/ComfyUI --report /tmp/maxine-media-test.json
```

Run this in a **staging copy** with an installed client. It temporarily points that copy's configuration at a local mock server and restores it afterward. It covers original 4K dimensions, 29.97 fps, audio packet identity, native trims/crops/components, odd dimensions, cancellation and real MP4 metadata counting. It does not load NVIDIA's model. Real NIM gaze quality, GPU memory and first-use behavior still require testing with actual footage.

## Registry publishing (maintainers)

Create the `aifirst-studio` publisher in [Comfy Registry](https://registry.comfy.org/nodes), then create its publishing API key and store it as the GitHub Actions repository secret `REGISTRY_ACCESS_TOKEN`. Follow Comfy's [publishing guide](https://docs.comfy.org/registry/publishing). Keep this key out of source files, logs and chat.

The **Publish to Comfy Registry** workflow is manual (`workflow_dispatch`). Run it for a reviewed, tested commit after incrementing the three-part version in `pyproject.toml`; Registry versions cannot be overwritten. `.comfyignore` excludes development files and private/generated state from the Registry archive while retaining the manual client/service setup tools, protocols, example workflow and licence notices. The Registry key is separate from the NVIDIA NGC key.

## Attribution

Vendored `.proto` files are unchanged from [NVIDIA-Maxine/nim-clients](https://github.com/NVIDIA-Maxine/nim-clients), commit `d02b7d57541b8598ac4c057947b10b2e42ccb1ee`, under MIT. See `UPSTREAM.json` and `LICENSE-NVIDIA.md`. Proprietary NVIDIA containers/models are obtained separately from NGC and are not redistributed here.

MediaPipe is an Apache-2.0-licensed Google project; see its [repository](https://github.com/google-ai-edge/mediapipe) and [Face Landmarker documentation](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python). The model is downloaded separately from Google's official model storage, with the URL and SHA-256 in `install_iris_model.py`; its weights are not included in Git or releases.
