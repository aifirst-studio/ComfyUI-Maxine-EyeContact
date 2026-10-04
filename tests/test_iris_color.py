from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import cv2
    import numpy as np
    from iris_color import EYES, match_iris_color
except ImportError:
    cv2 = None


@unittest.skipIf(cv2 is None, 'Optional isolated iris runtime is not installed.')
class IrisTests(unittest.TestCase):
    def image(self, colour, offset=0, closed=False):
        image = np.full((200, 360, 3), (180, 140, 110), dtype=np.uint8)
        landmarks = [SimpleNamespace(x=0, y=0) for _ in range(478)]
        for number, (center, rim, lid) in enumerate(EYES):
            x, y = 100 + number * 160 + offset, 90
            cv2.ellipse(image, (x, y), (40, 15), 0, 0, 360, (230,230,230), -1)
            cv2.circle(image, (x,y), 10, colour, -1)
            cv2.circle(image, (x,y), 3, (8,8,8), -1)
            cv2.circle(image, (x+4,y-4), 1, (255,255,255), -1)
            landmarks[center] = SimpleNamespace(x=x/360, y=y/200)
            for index, (dx,dy) in zip(rim, ((10,0),(0,-10),(-10,0),(0,10))):
                landmarks[index] = SimpleNamespace(x=(x+dx)/360, y=(y+dy)/200)
            for index, angle in zip(lid, np.linspace(0, 2*np.pi, len(lid), endpoint=False)):
                landmarks[index] = SimpleNamespace(x=(x+40*np.cos(angle))/360,
                    y=(y+(2 if closed else 15)*np.sin(angle))/200)
        return image, landmarks

    def test_matches_colour_without_moving_pupil_or_changing_skin(self):
        original, a = self.image((65,105,140))
        corrected, b = self.image((135,80,50), offset=4)
        result, changed = match_iris_color(original, corrected, a, b)
        self.assertEqual(changed, 2)
        reference = cv2.cvtColor(np.uint8([[[65,105,140]]]), cv2.COLOR_RGB2LAB)[0,0].astype(float)
        before = cv2.cvtColor(corrected, cv2.COLOR_RGB2LAB)[90,111].astype(float)
        after = cv2.cvtColor(result, cv2.COLOR_RGB2LAB)[90,111].astype(float)
        self.assertLess(np.linalg.norm(after[1:]-reference[1:]), np.linalg.norm(before[1:]-reference[1:]))
        np.testing.assert_array_equal(result[90,104], corrected[90,104])  # Redirected pupil stays put.
        np.testing.assert_array_equal(result[86,108], corrected[86,108])  # Highlight stays white.
        np.testing.assert_array_equal(result[:60], corrected[:60])
        np.testing.assert_array_equal(result[120:], corrected[120:])

    def test_closed_eyes_are_skipped(self):
        source, a = self.image((65,105,140), closed=True)
        corrected, b = self.image((135,80,50), closed=True)
        result, changed = match_iris_color(source, corrected, a, b)
        self.assertEqual(changed, 0)
        np.testing.assert_array_equal(result, corrected)

    def test_missing_iris_landmarks_are_skipped(self):
        source, a = self.image((65,105,140))
        corrected, b = self.image((135,80,50))
        result, changed = match_iris_color(source, corrected, a[:468], b[:468])
        self.assertEqual(changed, 0)
        np.testing.assert_array_equal(result, corrected)


if __name__ == '__main__':
    unittest.main()
