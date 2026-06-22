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
            mat = EqgMaterial()
            mat.id = struct.unpack('<i', stream.read(4))[0]
            mat.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            if not mat.name:
                mat.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            else:
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
            self.materials.append(mat)

        for _ in range(vertex_count):
            vtx = EqgModVertex()
            vtx.position = (struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0])
            vtx.normal = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
            if self.version >= 3:
                vtx.tint = (struct.unpack('<B', stream.read(1))[0],
                           struct.unpack('<B', stream.read(1))[0],
                           struct.unpack('<B', stream.read(1))[0],
                           struct.unpack('<B', stream.read(1))[0])
            vtx.uv = (struct.unpack('<f', stream.read(4))[0],
                     struct.unpack('<f', stream.read(4))[0])
            if self.version >= 3:
                vtx.uv2 = (struct.unpack('<f', stream.read(4))[0],
                          struct.unpack('<f', stream.read(4))[0])
            self.vertices.append(vtx)

        for _ in range(face_count):
            face = EqgModFace()
            face.indices = (struct.unpack('<I', stream.read(4))[0],
                           struct.unpack('<I', stream.read(4))[0],
                           struct.unpack('<I', stream.read(4))[0])
            mat_id = struct.unpack('<i', stream.read(4))[0]
            face.material_index = mat_id
            if 0 <= mat_id < len(self.materials):
                face.material_name = self.materials[mat_id].name
            face.flags = struct.unpack('<I', stream.read(4))[0]
            self.faces.append(face)

        for _ in range(bone_count):
            bone = EqgModBone()
            bone.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            bone.next_index = struct.unpack('<i', stream.read(4))[0]
            bone.children_count = struct.unpack('<I', stream.read(4))[0]
            bone.child_index = struct.unpack('<i', stream.read(4))[0]
            bone.pivot = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
            bone.rotation = (struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0])
            bone.scale = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
            self.bones.append(bone)

        if bone_count > 0:
            for vi in range(vertex_count):
                count = struct.unpack('<i', stream.read(4))[0]
                for j in range(4):
                    bi = struct.unpack('<i', stream.read(4))[0]
                    bw = struct.unpack('<f', stream.read(4))[0]
                    if j < count:
                        self.vertices[vi].bone_indices[j] = bi
                        self.vertices[vi].bone_weights[j] = bw


class EqgMdsModel(object):
    __slots__ = ('name', 'main_piece', 'vertices', 'faces', 'bone_count')

    def __init__(self):
        self.name = ''
        self.main_piece = 0
        self.vertices = []
        self.faces = []
        self.bone_count = 0


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
            mat = EqgMaterial()
            mat.id = struct.unpack('<i', stream.read(4))[0]
            mat.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            if not mat.name:
                mat.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            else:
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
            self.materials.append(mat)

        for _ in range(bone_count):
            bone = EqgModBone()
            bone.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            bone.next_index = struct.unpack('<i', stream.read(4))[0]
            bone.children_count = struct.unpack('<I', stream.read(4))[0]
            bone.child_index = struct.unpack('<i', stream.read(4))[0]
            bone.pivot = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
            bone.rotation = (struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0],
                           struct.unpack('<f', stream.read(4))[0])
            bone.scale = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
            self.bones.append(bone)

        for _ in range(model_count):
            model = EqgMdsModel()
            model.main_piece = struct.unpack('<I', stream.read(4))[0]
            model.name = name_table.by_offset(struct.unpack('<i', stream.read(4))[0])
            m_vertex_count = struct.unpack('<I', stream.read(4))[0]
            m_face_count = struct.unpack('<I', stream.read(4))[0]
            model.bone_count = struct.unpack('<I', stream.read(4))[0]

            for _ in range(m_vertex_count):
                vtx = EqgModVertex()
                vtx.position = (struct.unpack('<f', stream.read(4))[0],
                               struct.unpack('<f', stream.read(4))[0],
                               struct.unpack('<f', stream.read(4))[0])
                vtx.normal = (struct.unpack('<f', stream.read(4))[0],
                             struct.unpack('<f', stream.read(4))[0],
                             struct.unpack('<f', stream.read(4))[0])
                if self.version >= 3:
                    vtx.tint = (struct.unpack('<B', stream.read(1))[0],
                               struct.unpack('<B', stream.read(1))[0],
                               struct.unpack('<B', stream.read(1))[0],
                               struct.unpack('<B', stream.read(1))[0])
                vtx.uv = (struct.unpack('<f', stream.read(4))[0],
                         struct.unpack('<f', stream.read(4))[0])
                if self.version >= 3:
                    vtx.uv2 = (struct.unpack('<f', stream.read(4))[0],
                              struct.unpack('<f', stream.read(4))[0])
                model.vertices.append(vtx)

            for _ in range(m_face_count):
                face = EqgModFace()
                face.indices = (struct.unpack('<I', stream.read(4))[0],
                               struct.unpack('<I', stream.read(4))[0],
                               struct.unpack('<I', stream.read(4))[0])
                mat_id = struct.unpack('<i', stream.read(4))[0]
                face.material_index = mat_id
                if 0 <= mat_id < len(self.materials):
                    face.material_name = self.materials[mat_id].name
                face.flags = struct.unpack('<I', stream.read(4))[0]
                model.faces.append(face)

            if bone_count > 0:
                for _ in range(m_vertex_count):
                    count = struct.unpack('<i', stream.read(4))[0]
                    vtx = model.vertices[len(model.vertices) - m_vertex_count + _]
                    for j in range(4):
                        bi = struct.unpack('<i', stream.read(4))[0]
                        bw = struct.unpack('<f', stream.read(4))[0]
                        if j < count:
                            vtx.bone_indices[j] = bi
                            vtx.bone_weights[j] = bw

            self.models.append(model)


def build_bone_tree(bones):
    children = {i: [] for i in range(len(bones))}
    is_child = {i: False for i in range(len(bones))}

    for i, bone in enumerate(bones):
        if bone.children_count > 0 and bone.child_index >= 0:
            idx = bone.child_index
            for _ in range(bone.children_count):
                if 0 <= idx < len(bones):
                    children[i].append(idx)
                    is_child[idx] = True
                    idx += 1

    roots = [i for i in range(len(bones)) if not is_child[i]]
    if not roots and len(bones) > 0:
        roots = [0]

    return children, roots
