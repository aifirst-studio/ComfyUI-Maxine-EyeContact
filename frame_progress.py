"""Count complete video samples received in MP4, without decoding or estimating.

Unsupported or malformed metadata disables counting; inference still proceeds.
The limit bounds metadata memory for an untrusted service response.
"""
import heapq
import struct

MAX_METADATA = 8 * 1024 * 1024
MAX_SAMPLES = 1_000_000


def boxes(data):
    offset = 0
    while offset < len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data):
            raise ValueError("Invalid MP4 box")
        yield kind, data[offset + header:offset + size]
        offset += size


def child(data, name):
    return next((payload for kind, payload in boxes(data) if kind == name), b"")


def u32(data, offset=0):
    return struct.unpack_from(">I", data, offset)[0]


class MP4FrameCounter:
    def __init__(self):
        self.received = 0
        self.frames = 0
        self.available = False
        self.disabled = False
        self.track = None
        self.default_size = 0
        self.ends = []
        self.header = bytearray()
        self.payload = bytearray()
        self.remaining = 0
        self.kind = None
        self.position = 0
        self.box_start = 0

    def feed(self, data):
        self.received += len(data)
        if not self.disabled:
            try:
                self._feed(memoryview(data))
                while self.ends and self.ends[0] <= self.received:
                    heapq.heappop(self.ends)
                    self.frames += 1
            except (ValueError, IndexError, StopIteration, struct.error):
                self.disabled = True
                self.available = False
                self.ends.clear()
                self.payload.clear()
        return self.frames if self.available else None

    def _feed(self, data):
        while data:
            if self.kind is None:
                needed = 8 if len(self.header) < 8 else 16
                amount = min(needed - len(self.header), len(data))
                self.header.extend(data[:amount])
                self.position += amount
                data = data[amount:]
                if len(self.header) < 8:
                    continue
                size, kind = struct.unpack_from(">I4s", self.header)
                if size == 1 and len(self.header) < 16:
                    continue
                header_size = len(self.header)
                if size == 1:
                    size = struct.unpack_from(">Q", self.header, 8)[0]
                if size and size < header_size:
                    raise ValueError("Invalid MP4 box size")
                self.kind = kind
                self.box_start = self.position - header_size
                self.remaining = size - header_size if size else None
                self.header.clear()
                if kind in (b"moov", b"moof") and (not size or size > MAX_METADATA):
                    raise ValueError("MP4 metadata exceeds progress limit")
            amount = len(data) if self.remaining is None else min(self.remaining, len(data))
            if self.kind in (b"moov", b"moof"):
                self.payload.extend(data[:amount])
            self.position += amount
            data = data[amount:]
            if self.remaining is not None:
                self.remaining -= amount
                if self.remaining == 0:
                    if self.kind == b"moov":
                        self._moov(bytes(self.payload))
                    elif self.kind == b"moof":
                        self._moof(bytes(self.payload))
                    self.payload.clear()
                    self.kind = None

    def _add_ends(self, ends):
        if self.frames + len(self.ends) + len(ends) > MAX_SAMPLES:
            raise ValueError("Too many video samples for progress")
        for end in ends:
            heapq.heappush(self.ends, end)
        self.available = True

    def _moov(self, data):
        for kind, trak in boxes(data):
            if kind != b"trak":
                continue
            mdia = child(trak, b"mdia")
            if child(mdia, b"hdlr")[8:12] != b"vide":
                continue
            tkhd = child(trak, b"tkhd")
            self.track = u32(tkhd, 20 if tkhd[0] == 1 else 12)
            stbl = child(child(mdia, b"minf"), b"stbl")
            stsz = child(stbl, b"stsz")
            size, count = u32(stsz, 4), u32(stsz, 8)
            if count > MAX_SAMPLES:
                raise ValueError("Too many video samples")
            if not count:
                continue  # Fragmented MP4: sample sizes arrive in moof boxes.
            sizes = [size] * count if size else [u32(stsz, 12 + i * 4) for i in range(count)]
            offsets = child(stbl, b"stco")
            wide = False
            if not offsets:
                offsets = child(stbl, b"co64")
                wide = True
            chunks = u32(offsets, 4)
            if chunks > MAX_SAMPLES:
                raise ValueError("Too many MP4 chunks")
            stsc = child(stbl, b"stsc")
            entries = u32(stsc, 4)
            if entries > MAX_SAMPLES:
                raise ValueError("Too many sample-to-chunk entries")
            rows = [(u32(stsc, 8 + i * 12), u32(stsc, 12 + i * 12)) for i in range(entries)]
            if not rows or rows[0][0] != 1 or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
                raise ValueError("Invalid sample-to-chunk table")
            ends, sample, row = [], 0, 0
            for chunk in range(chunks):
                while row + 1 < len(rows) and rows[row + 1][0] <= chunk + 1:
                    row += 1
                offset = struct.unpack_from(">Q" if wide else ">I", offsets, 8 + chunk * (8 if wide else 4))[0]
                if sample + rows[row][1] > count:
                    raise ValueError("Invalid chunk sample count")
                for _ in range(rows[row][1]):
                    offset += sizes[sample]
                    sample += 1
                    ends.append(offset)
            if sample != count:
                raise ValueError("Incomplete sample table")
            self._add_ends(ends)
            break
        for kind, trex in boxes(child(data, b"mvex")):
            if kind == b"trex" and u32(trex, 4) == self.track:
                self.default_size = u32(trex, 16)

    def _moof(self, data):
        for kind, traf in boxes(data):
            if kind != b"traf":
                continue
            tfhd = child(traf, b"tfhd")
            if u32(tfhd, 4) != self.track:
                continue
            flags = u32(tfhd) & 0xFFFFFF
            cursor = 8
            if flags & 1:
                base = struct.unpack_from(">Q", tfhd, cursor)[0]
                cursor += 8
            elif flags & 0x020000:
                base = self.box_start
            else:
                continue  # Implicit bases with multiple tracks are ambiguous.
            cursor += 4 if flags & 2 else 0
            cursor += 4 if flags & 8 else 0
            size = u32(tfhd, cursor) if flags & 16 else self.default_size
            last_end = None
            for tag, trun in boxes(traf):
                if tag != b"trun":
                    continue
                run_flags = u32(trun) & 0xFFFFFF
                count = u32(trun, 4)
                if count > MAX_SAMPLES:
                    raise ValueError("Too many fragment samples")
                cursor = 8
                if run_flags & 1:
                    offset = base + struct.unpack_from(">i", trun, cursor)[0]
                    cursor += 4
                elif last_end is not None:
                    offset = last_end
                else:
                    continue
                cursor += 4 if run_flags & 4 else 0
                ends = []
                for _ in range(count):
                    cursor += 4 if run_flags & 0x100 else 0
                    sample_size = u32(trun, cursor) if run_flags & 0x200 else size
                    cursor += 4 if run_flags & 0x200 else 0
                    cursor += 4 if run_flags & 0x400 else 0
                    cursor += 4 if run_flags & 0x800 else 0
                    if not sample_size:
                        raise ValueError("No fragment sample size")
                    offset += sample_size
                    ends.append(offset)
                last_end = offset
                self._add_ends(ends)
