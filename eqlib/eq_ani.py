import struct
import io
import math
from eqlib.eq_const import *
from eqlib.eq_mod import EqgNameTable


class EqgBoneFrame(object):
    __slots__ = ('milliseconds', 'translation', 'rotation', 'scale')

    def __init__(self):
        self.milliseconds = 0
        self.translation = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0, 1.0)
        self.scale = (1.0, 1.0, 1.0)


class EqgBoneAnim(object):
    __slots__ = ('name', 'frames')

    def __init__(self):
        self.name = ''
        self.frames = []


class EqgAniFile(object):
    def __init__(self, data):
        self.version = 0
        self.is_strict = False
        self.bone_anims = []
        self.duration_ms = 0
        self._parse(data)

    def _parse(self, data):
        stream = io.BytesIO(data)

        magic = stream.read(4)
        if magic != b'EQGA':
            return

        # "EQGA", version, string-table length, bone count, a flag (v2), the
        # bone names, then per bone {frame count, name offset} and 44-byte
        # keys {u32 ms, pos3, quat xyzw, scale3}. Source: Everquest_Model_Viewer.
        self.version = struct.unpack('<I', stream.read(4))[0]
        name_length = struct.unpack('<I', stream.read(4))[0]
        bone_count = struct.unpack('<I', stream.read(4))[0]

        if self.version > 1:
            self.is_strict = struct.unpack('<I', stream.read(4))[0] != 0

        name_data = stream.read(name_length)
        name_table = EqgNameTable()
        name_table.parse(name_data)

        for _ in range(bone_count):
            ba = EqgBoneAnim()
            frame_count = struct.unpack('<I', stream.read(4))[0]
            ba.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])

            for _ in range(frame_count):
                frame = EqgBoneFrame()
                # Key timestamps are absolute milliseconds, not deltas.
                frame.milliseconds = struct.unpack('<I', stream.read(4))[0]
                frame.translation = struct.unpack('<3f', stream.read(12))
                frame.rotation = struct.unpack('<4f', stream.read(16))
                frame.scale = struct.unpack('<3f', stream.read(12))
                ba.frames.append(frame)
                if frame.milliseconds > self.duration_ms:
                    self.duration_ms = frame.milliseconds

            self.bone_anims.append(ba)

    def get_frames_for_bone(self, bone_name):
        lower_name = bone_name.lower()
        for ba in self.bone_anims:
            if ba.name.lower() == lower_name:
                return ba.frames
        return []


def parse_track_name(name):
    cleaned = name.lower().replace('_track', '').strip()
    if len(cleaned) < 6:
        return cleaned, '', ''
    if len(cleaned) >= 6 and cleaned[:3] == cleaned[3:6]:
        return cleaned[:3], (cleaned[7:] if len(cleaned) > 7 else cleaned[:3]), 'root'
    anim_name = cleaned[:3]
    model_name = cleaned[3:6]
    piece_name = cleaned[6:]
    return anim_name, model_name, piece_name


def decompress_track_transform(ft, use_int16=True):
    """Decode one WLD track frame.

    Old WLDs store eight i16 per frame (w, x, y, z rotation over 32767-ish
    normalization; x, y, z shift over 256; scale over 256). The last value is
    a bone scale, not a shift denominator - a gnome's R_POINT carries 163
    (0.64x weapons), the Luclin human seat bone 6 (verts stored ~40x too big),
    human/barbarian/gnome/Iksar eyes 244 (seats them in the sockets).
    Source: Everquest_Model_Viewer decodeTrack.
    """
    rot_x = float(ft['rotation'][0])
    rot_y = float(ft['rotation'][1])
    rot_z = float(ft['rotation'][2])
    rot_w = float(ft['rotation'][3])

    length = math.sqrt(rot_x*rot_x + rot_y*rot_y + rot_z*rot_z + rot_w*rot_w)
    if length > 0.0001:
        rot_x /= length
        rot_y /= length
        rot_z /= length
        rot_w /= length
    else:
        rot_x, rot_y, rot_z, rot_w = 0.0, 0.0, 0.0, 1.0

    shift_x = float(ft['shift'][0]) / 256.0
    shift_y = float(ft['shift'][1]) / 256.0
    shift_z = float(ft['shift'][2]) / 256.0

    raw_scale = ft.get('scale', 0)
    scale = raw_scale / 256.0 if raw_scale > 0 else 1.0

    # Raw WLD axes; callers map positions/rotations with the wld_* helpers.
    return {
        'translation': (shift_x, shift_y, shift_z),
        'rotation': (rot_x, rot_y, rot_z, rot_w),
        'scale': scale,
    }
