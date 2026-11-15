import struct
import io


class EqgNameTable(object):
    def __init__(self):
        self._names = {}
        self._offset_list = []

    def parse(self, name_data):
        self._names = {}
        self._offset_list = []
        chunk = bytearray()
        last_offset = 0
        for i, b in enumerate(name_data):
            if b == 0:
                self._names[last_offset] = bytes(chunk).decode('latin-1', errors='replace')
                self._offset_list.append((last_offset, bytes(chunk).decode('latin-1', errors='replace')))
                chunk = bytearray()
                last_offset = i + 1
            else:
                chunk.append(b)

    def by_offset(self, offset):
        if offset < 0:
            offset = -offset
        return self._names.get(offset, '')


class EqgModBone(object):
    __slots__ = ('name', 'next_index', 'children_count', 'child_index',
                 'pivot', 'rotation', 'scale')

    def __init__(self):
        self.name = ''
        self.next_index = -1
        self.children_count = 0
        self.child_index = -1
        self.pivot = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0, 1.0)
        self.scale = (1.0, 1.0, 1.0)


class EqgModVertex(object):
    __slots__ = ('position', 'normal', 'tint', 'uv', 'uv2', 'bone_indices', 'bone_weights')

    def __init__(self):
        self.position = (0.0, 0.0, 0.0)
        self.normal = (0.0, 0.0, 1.0)
        self.tint = (128, 128, 128, 255)
        self.uv = (0.0, 0.0)
        self.uv2 = (0.0, 0.0)
        self.bone_indices = [0, 0, 0, 0]
        self.bone_weights = [1.0, 0.0, 0.0, 0.0]


class EqgModFace(object):
    __slots__ = ('indices', 'material_index', 'material_name', 'flags')

    def __init__(self):
        self.indices = (0, 0, 0)
        self.material_index = -1
        self.material_name = ''
        self.flags = 0


class EqgMaterial(object):
    __slots__ = ('id', 'name', 'shader', 'properties', 'animation_sleep', 'animation_textures')

    def __init__(self):
        self.id = 0
        self.name = ''
        self.shader = ''
        self.properties = []
        self.animation_sleep = 0
        self.animation_textures = []


def _read_material(stream, name_table):
    """Read one EQGM/EQGS material.

    Layout (per Everquest_Model_Viewer readMOD/readMDS): {index u32, nameOff
    i32, shaderOff i32, propCount u32} then props {nameOff i32, type u32,
    value 4}. All three offsets are always present - reading them
    conditionally desyncs the stream.
    """
    mat = EqgMaterial()
    mat.id = struct.unpack('<i', stream.read(4))[0]
    mat.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
    mat.shader = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
    param_count = struct.unpack('<I', stream.read(4))[0]
    for _ in range(param_count):
        prop_name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
        prop_type = struct.unpack('<I', stream.read(4))[0]
        if prop_type == 0:
            prop_value = '%.8f' % struct.unpack('<f', stream.read(4))[0]
        else:
            val = struct.unpack('<i', stream.read(4))[0]
            if prop_type == 2:
                prop_value = name_table.by_offset(val)
            else:
                prop_value = str(val)
        mat.properties.append((prop_name, prop_type, prop_value))
    return mat


def _read_mod_vertex(stream, version):
    """One .mod vertex.

    v1/v2: pos3 nrm3 uv2 = 32 bytes; v3: pos3 nrm3 rgba uv2 uv2 = 44 bytes.
    Source: Everquest_Model_Viewer readMOD.
    """
    vtx = EqgModVertex()
    vtx.position = struct.unpack('<3f', stream.read(12))
    vtx.normal = struct.unpack('<3f', stream.read(12))
    if version >= 3:
        vtx.tint = struct.unpack('<4B', stream.read(4))
    vtx.uv = struct.unpack('<2f', stream.read(8))
    if version >= 3:
        vtx.uv2 = struct.unpack('<2f', stream.read(8))
    return vtx


def _read_bones(stream, name_table, bone_count):
    """56-byte bones {nameOff, sibling, childCount, firstChild, pos3, quat4, scale3}."""
    bones = []
    for _ in range(bone_count):
        bone = EqgModBone()
        bone.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
        bone.next_index = struct.unpack('<i', stream.read(4))[0]
        bone.children_count = struct.unpack('<I', stream.read(4))[0]
        bone.child_index = struct.unpack('<i', stream.read(4))[0]
        bone.pivot = struct.unpack('<3f', stream.read(12))
        bone.rotation = struct.unpack('<4f', stream.read(16))
        bone.scale = struct.unpack('<3f', stream.read(12))
        bones.append(bone)
    return bones


def _read_weights(stream, vertices, count):
    """Per-vertex weight records {u32 count, 4 x (i32 bone, f32 weight)} = 36 bytes."""
    for vi in range(min(count, len(vertices))):
        vtx = vertices[vi]
        n = struct.unpack('<i', stream.read(4))[0]
        n = min(4, max(0, n))
        for j in range(4):
            bi = struct.unpack('<i', stream.read(4))[0]
            bw = struct.unpack('<f', stream.read(4))[0]
            if j < n:
                vtx.bone_indices[j] = bi
                vtx.bone_weights[j] = bw


class EqgModFile(object):
    def __init__(self, data):
        self.version = 0
        self.name = ''
        self.materials = []
        self.bones = []
        self.vertices = []
        self.faces = []
        self._parse(data)

    def _parse(self, data):
        stream = io.BytesIO(data)

        magic = stream.read(4)
        if magic != b'EQGM':
            return

        self.version = struct.unpack('<I', stream.read(4))[0]
        name_length = struct.unpack('<I', stream.read(4))[0]
        material_count = struct.unpack('<I', stream.read(4))[0]
        vertex_count = struct.unpack('<I', stream.read(4))[0]
        face_count = struct.unpack('<I', stream.read(4))[0]
        bone_count = struct.unpack('<I', stream.read(4))[0]

        name_data = stream.read(name_length)
        name_table = EqgNameTable()
        name_table.parse(name_data)

        for _ in range(material_count):
            self.materials.append(_read_material(stream, name_table))

        # Vertex size: whatever makes the sections add up to the file size
        # (seen: 32 in v1/v2, 44 in v3); the version's usual size if nothing
        # fits. Source: Everquest_Model_Viewer readMOD.
        vsize = 44 if self.version >= 3 else 32
        if vertex_count:
            pos = stream.tell()
            rest = len(data) - pos - face_count * 20 - bone_count * 56 - (vertex_count * 36 if bone_count else 0)
            if rest > 0 and rest % vertex_count == 0 and 32 <= rest // vertex_count <= 64:
                vsize = rest // vertex_count
        if vsize == 32:
            has_tint = False
        elif vsize == 44:
            has_tint = True
        else:
            # unusual size: fall back to the version's usual layout
            has_tint = self.version >= 3
            vsize = 44 if has_tint else 32

        for _ in range(vertex_count):
            self.vertices.append(_read_mod_vertex(stream, 3 if has_tint else 1))

        for _ in range(face_count):
            face = EqgModFace()
            face.indices = struct.unpack('<3I', stream.read(12))
            face.material_index = struct.unpack('<i', stream.read(4))[0]
            if 0 <= face.material_index < len(self.materials):
                face.material_name = self.materials[face.material_index].name
            face.flags = struct.unpack('<I', stream.read(4))[0]
            self.faces.append(face)

        if bone_count > 0:
            self.bones = _read_bones(stream, name_table, bone_count)
            _read_weights(stream, self.vertices, vertex_count)


class EqgMdsModel(object):
    __slots__ = ('name', 'main_piece', 'vertices', 'faces', 'weight_count')

    def __init__(self):
        self.name = ''
        self.main_piece = 0
        self.vertices = []
        self.faces = []
        self.weight_count = 0


class EqgMdsFile(object):
    def __init__(self, data):
        self.version = 0
        self.name = ''
        self.materials = []
        self.bones = []
        self.models = []
        self._parse(data)

    def _parse(self, data):
        stream = io.BytesIO(data)

        magic = stream.read(4)
        if magic != b'EQGS':
            return

        self.version = struct.unpack('<I', stream.read(4))[0]
        name_length = struct.unpack('<I', stream.read(4))[0]
        material_count = struct.unpack('<I', stream.read(4))[0]
        bone_count = struct.unpack('<I', stream.read(4))[0]
        model_count = struct.unpack('<I', stream.read(4))[0]

        name_data = stream.read(name_length)
        name_table = EqgNameTable()
        name_table.parse(name_data)

        for _ in range(material_count):
            self.materials.append(_read_material(stream, name_table))

        self.bones = _read_bones(stream, name_table, bone_count)

        for _ in range(model_count):
            model = EqgMdsModel()
            model.main_piece = struct.unpack('<I', stream.read(4))[0]
            model.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            m_vertex_count = struct.unpack('<I', stream.read(4))[0]
            m_face_count = struct.unpack('<I', stream.read(4))[0]
            model.weight_count = struct.unpack('<I', stream.read(4))[0]

            # .mds vertices are always 32 bytes (pos3 nrm3 uv2), whatever the
            # version. Source: Everquest_Model_Viewer readMDS.
            for _ in range(m_vertex_count):
                model.vertices.append(_read_mod_vertex(stream, 1))

            for _ in range(m_face_count):
                face = EqgModFace()
                face.indices = struct.unpack('<3I', stream.read(12))
                face.material_index = struct.unpack('<i', stream.read(4))[0]
                if 0 <= face.material_index < len(self.materials):
                    face.material_name = self.materials[face.material_index].name
                face.flags = struct.unpack('<I', stream.read(4))[0]
                model.faces.append(face)

            _read_weights(stream, model.vertices, model.weight_count)
            self.models.append(model)


def build_bone_tree(bones):
    """Derive the parent/child structure from firstChild + sibling chains.

    Children are NOT always consecutive in the bone table (ahf.mds scatters
    them), so walk each bone's child_index then follow the children's
    next_index (sibling) links - the same traversal Everquest_Model_Viewer
    uses. Assuming consecutiveness orphans ~30 bones of the Akhevan female
    and detaches her legs/spine.
    """
    children = {i: [] for i in range(len(bones))}
    is_child = {i: False for i in range(len(bones))}

    for i, bone in enumerate(bones):
        c = bone.child_index
        guard = 0
        while 0 <= c < len(bones) and guard <= len(bones):
            children[i].append(c)
            is_child[c] = True
            c = bones[c].next_index
            guard += 1

    roots = [i for i in range(len(bones)) if not is_child[i]]
    if not roots and len(bones) > 0:
        roots = [0]

    return children, roots
