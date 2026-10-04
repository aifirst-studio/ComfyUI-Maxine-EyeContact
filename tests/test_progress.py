from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frame_progress import MP4FrameCounter, MAX_METADATA


def box(name, data):
    return struct.pack('>I4s', len(data) + 8, name) + data


def integer(value):
    return struct.pack('>I', value)


def moov(sizes=None, offset=0):
    sizes = sizes or []
    stsz = b'\0' * 4 + integer(0) + integer(len(sizes)) + b''.join(map(integer, sizes))
    stco = b'\0' * 4 + integer(1) + integer(offset)
    stsc = b'\0' * 4 + integer(1) + integer(1) + integer(len(sizes)) + integer(1)
    stbl = box(b'stbl', box(b'stsz', stsz) + box(b'stco', stco) + box(b'stsc', stsc))
    mdia = box(b'mdia', box(b'hdlr', b'\0' * 8 + b'vide') + box(b'minf', stbl))
    return box(b'moov', box(b'trak', box(b'tkhd', b'\0' * 12 + integer(1)) + mdia))


class ProgressTests(unittest.TestCase):
    def test_classic_mp4_counts_only_received_complete_samples(self):
        metadata = moov([3, 5, 2])
        metadata = moov([3, 5, 2], len(metadata) + 8)
        counter = MP4FrameCounter()
        for byte in metadata:
            counter.feed(bytes([byte]))  # Arbitrary gRPC chunk boundaries.
        self.assertEqual(counter.frames, 0)
        counter.feed(struct.pack('>I4s', 18, b'mdat') + b'aa')
        self.assertEqual(counter.frames, 0)
        self.assertEqual(counter.feed(b'a'), 1)
        self.assertEqual(counter.feed(b'bbbbb'), 2)
        self.assertEqual(counter.feed(b'cc'), 3)

    def test_fragmented_mp4(self):
        metadata = moov()
        tfhd = box(b'tfhd', integer(0x020000) + integer(1))
        def fragment(offset):
            trun = box(b'trun', integer(0x201) + integer(2) + integer(offset) + integer(3) + integer(4))
            return box(b'moof', box(b'traf', tfhd + trun))
        data = fragment(0)
        data = fragment(len(data) + 8)
        counter = MP4FrameCounter()
        counter.feed(metadata + data + struct.pack('>I4s', 15, b'mdat'))
        self.assertEqual(counter.feed(b'aa'), 0)
        self.assertEqual(counter.feed(b'a'), 1)
        self.assertEqual(counter.feed(b'bbbb'), 2)

    def test_invalid_metadata_falls_back(self):
        counter = MP4FrameCounter()
        self.assertIsNone(counter.feed(struct.pack('>I4s', 4, b'moov')))
        self.assertTrue(counter.disabled)
        self.assertIsNone(counter.feed(b'video payload'))

    def test_unbounded_metadata_not_buffered(self):
        counter = MP4FrameCounter()
        self.assertIsNone(counter.feed(struct.pack('>I4s', MAX_METADATA + 1, b'moov')))
        self.assertEqual(len(counter.payload), 0)

    def test_non_mp4_data_is_not_reported_as_inference_progress(self):
        self.assertIsNone(MP4FrameCounter().feed(b'not an MP4 response'))


if __name__ == '__main__':
    unittest.main()
