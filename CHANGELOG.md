# Changelog

## 0.1.2

- Add Comfy Registry metadata, package exclusions and a manual publishing workflow.
- Document Manager installation, the catalogue submission and the separate client/NVIDIA setup steps.

## 0.1.1

- Fix iris-colour exports that browsers/Windows players could not play: H.264 High/YUV420, CRF 1, original resolution and frame rate.
- Explain that the compatible colour-corrected export is very high quality rather than mathematically lossless.
- Document beta verification limits and the player-compatibility limitation for exact odd dimensions.
- Install MediaPipe's Linux EGL/GLES shared libraries in CI and document them for headless Debian/Ubuntu clients.

## 0.1.0

- Native VIDEO eye-contact correction using local NVIDIA NIM 1.5.0.
- Original-resolution processing and maximum-quality defaults.
- Standard ComfyUI progress plus streaming MP4 frame counts and honest waiting states.
- English/German in-node parameter help, including temporal filtering and eye blending sensitivity.
- Experimental CPU iris-colour matching with conservative blink/visibility checks.
- Isolated Linux/Windows client, guarded Linux service helpers, portable CPU tests and example workflow.
