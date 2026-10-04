"""Conservative iris-only colour matching; no gaze/texture replacement.

Landmarks are normalized MediaPipe 478-point face landmarks. Uncertain/closed
eyes are skipped. The caller supplies original and redirected frames in RGB.
"""
import cv2
import numpy as np

EYES = (
    (468, (469, 470, 471, 472), (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246)),
    (473, (474, 475, 476, 477), (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398)),
)


def eye_region(image, landmarks, definition):
    height, width = image.shape[:2]
    center, rim, lid = definition
    def points(indices):
        return np.array([(landmarks[i].x * width, landmarks[i].y * height) for i in indices], dtype=np.float32)
    xy = points((center,))[0]
    radius = np.max(np.abs(points(rim) - xy), axis=0)
    polygon = points(lid)
    # Refuse tiny irises, closed eyes and landmarks outside the frame.
    if (np.min(radius) < 2 or np.ptp(polygon[:, 1]) < radius[1] * 0.65
            or np.ptp(polygon[:, 1]) / max(1, np.ptp(polygon[:, 0])) < 0.12):
        return None
    x0, y0 = np.floor(xy - radius * 1.2).astype(int)
    x1, y1 = np.ceil(xy + radius * 1.2 + 1).astype(int)
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        return None
    patch = image[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.sqrt(((xx - xy[0]) / radius[0]) ** 2 + ((yy - xy[1]) / radius[1]) ** 2)
    aperture = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillPoly(aperture, [np.round(polygon - (x0, y0)).astype(np.int32)], 1)
    # Sample the iris ring, excluding pupil, edge/skin and specular glints.
    sample = (distance > 0.35) & (distance < 0.85) & (aperture > 0)
    if np.count_nonzero(sample) < 12:
        return None
    lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    light = lab[:, :, 0]
    low, high = np.percentile(light[sample], (15, 90))
    sample &= (light >= low) & (light <= high) & (light < 240)
    if np.count_nonzero(sample) < 10:
        return None
    colour = np.median(lab[sample], axis=0)
    alpha = np.clip((1.0 - distance) / 0.18, 0, 1) * np.clip((distance - 0.22) / 0.16, 0, 1)
    alpha *= aperture
    alpha *= np.clip((245 - light) / 25, 0, 1)  # Retain white highlights.
    return (x0, y0, x1, y1), patch, lab, colour, alpha


def match_iris_color(original, corrected, source_landmarks, output_landmarks):
    if len(source_landmarks) < 478 or len(output_landmarks) < 478:
        return corrected, 0
    result = corrected.copy()
    changed = 0
    for definition in EYES:
        source = eye_region(original, source_landmarks, definition)
        target = eye_region(corrected, output_landmarks, definition)
        if source is None or target is None:
            continue
        bounds, patch, lab, colour, alpha = target
        delta = source[3] - colour
        # Large luminance shifts often indicate a bad iris detection. Keep
        # luminance changes conservative while correcting chroma separately.
        delta[0] = np.clip(delta[0], -24, 24)
        recoloured = cv2.cvtColor(np.clip(lab + delta, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
        blended = np.round(patch * (1 - alpha[:, :, None]) + recoloured * alpha[:, :, None]).astype(np.uint8)
        x0, y0, x1, y1 = bounds
        result[y0:y1, x0:x1] = blended
        changed += 1
    return result, changed
