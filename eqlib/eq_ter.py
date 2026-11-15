"""EQG terrain (.ter).

Modern (Luclin and later) zones carry no .wld: the ground is this file and
everything standing on it is a .mod placed by the zone's .zon.

Layout from quail (github.com/dariusuknuis/quail raw/ter_read.go):

    'EQGT', version u32, nameLen u32, materialCount u32, vertexCount u32,
    faceCount u32, name block (nameLen bytes),
    materials  {id i32, nameOff i32, shaderOff i32, paramCount u32,
                params {nameOff i32, type u32, value}}   - same as .mod
    vertices   version <= 2: pos3 nrm3 uv2               (32 bytes)
               version >  2: pos3 nrm3 tint4 uv2 uv2     (44 bytes)
    faces      {i0 i1 i2 u32, material i32, flags u32}
    version <  2.5?  a second uv2 array, vertexCount * 8 bytes
    excess     u32, must be 0

Verified against D:/EverQuest/*.eqg: eqter files consume to the excess word
with no leftover bytes.
"""
import struct
import io

from eqlib.eq_mod import EqgNameTable, _read_material


class TerVertex(object):
    __slots__ = ('position', 'normal', 'tint', 'uv', 'uv2')

    def __init__(self):
        self.position = (0.0, 0.0, 0.0)
        self.normal = (0.0, 0.0, 1.0)
        self.tint = (128, 128, 128, 255)
        self.uv = (0.0, 0.0)
        self.uv2 = (0.0, 0.0)


class TerFace(object):
    __slots__ = ('indices', 'material_index', 'material_name', 'flags')

    def __init__(self):
        self.indices = (0, 0, 0)
        self.material_index = -1
        self.material_name = ''
        self.flags = 0


class EqgTerFile(object):
    def __init__(self, data):
        self.version = 0
        self.materials = []
        self.vertices = []
        self.faces = []
        self.excess = 0
        self.trailing_bytes = 0
        self._parse(data)

    def _parse(self, data):
        stream = io.BytesIO(data)
        if stream.read(4) != b'EQGT':
            return
        self.version = struct.unpack('<I', stream.read(4))[0]
        name_length = struct.unpack('<I', stream.read(4))[0]
        material_count = struct.unpack('<I', stream.read(4))[0]
        vertex_count = struct.unpack('<I', stream.read(4))[0]
        face_count = struct.unpack('<I', stream.read(4))[0]

        name_data = stream.read(name_length)
        name_table = EqgNameTable()
        name_table.parse(name_data)

        for _ in range(material_count):
            self.materials.append(_read_material(stream, name_table))

        has_tint = self.version > 2
        for _ in range(vertex_count):
            v = TerVertex()
            v.position = struct.unpack('<3f', stream.read(12))
            v.normal = struct.unpack('<3f', stream.read(12))
            if has_tint:
                v.tint = struct.unpack('<4B', stream.read(4))
            v.uv = struct.unpack('<2f', stream.read(8))
            if self.version >= 3:
                v.uv2 = struct.unpack('<2f', stream.read(8))
            self.vertices.append(v)

        for _ in range(face_count):
            f = TerFace()
            f.indices = struct.unpack('<3I', stream.read(12))
            f.material_index = struct.unpack('<i', stream.read(4))[0]
            if 0 <= f.material_index < len(self.materials):
                f.material_name = self.materials[f.material_index].name
            f.flags = struct.unpack('<I', stream.read(4))[0]
            self.faces.append(f)

        if self.version < 3:
            for i in range(min(vertex_count, len(self.vertices))):
                self.vertices[i].uv2 = struct.unpack('<2f', stream.read(8))

        if len(data) - stream.tell() >= 4:
            self.excess = struct.unpack('<I', stream.read(4))[0]
        self.trailing_bytes = len(data) - stream.tell()
