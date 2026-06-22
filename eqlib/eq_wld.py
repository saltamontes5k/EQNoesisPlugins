import struct
import io
from eqlib.eq_const import *


class WldFragment(object):
    __slots__ = ('frag_index', 'frag_code', 'name', 'data')

    def __init__(self):
        self.frag_index = -1
        self.frag_code = 0
        self.name = ''
        self.data = {}


class WldDmSpriteDef2(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_DM_SPRITE_DEF2
        self.name_ref = -1
        self.flags = 0
        self.material_palette_ref = -1
        self.dm_track_ref = -1
        self.fragment3_ref = -1
        self.fragment4_ref = -1
        self.center_offset = (0.0, 0.0, 0.0)
        self.params2 = (0.0, 0.0, 0.0)
        self.bounding_radius = 0.0
        self.bounding_box_min = (0.0, 0.0, 0.0)
        self.bounding_box_max = (0.0, 0.0, 0.0)
        self.scale = 0
        self.vertices = []
        self.uvs = []
        self.normals = []
        self.colors = []
        self.faces = []
        self.skin_assignment_groups = []
        self.face_material_groups = []
        self.vertex_material_groups = []
        self.mesh_ops = []
        self.material_palette = None
        self.is_new_world = False

    def read(self, r, is_new_world):
        self.is_new_world = is_new_world
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        self.material_palette_ref = r.read('<i')
        self.dm_track_ref = r.read('<i')
        self.fragment3_ref = r.read('<i')
        self.fragment4_ref = r.read('<i')

        self.center_offset = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.params2 = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.bounding_radius = r.read('<f')
        self.bounding_box_min = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.bounding_box_max = (r.read('<f'), r.read('<f'), r.read('<f'))

        vertex_count = r.read('<H')
        uv_count = r.read('<H')
        normal_count = r.read('<H')
        color_count = r.read('<H')
        triangle_count = r.read('<H')
        vertex_piece_count = r.read('<H')
        triangle_material_count = r.read('<H')
        vertex_material_count = r.read('<H')
        mesh_op_count = r.read('<H')
        self.scale = r.read('<H')

        scale_factor = 1.0 / float(1 << self.scale)

        self.vertices = []
        for _ in range(vertex_count):
            self.vertices.append((r.read('<h') * scale_factor, r.read('<h') * scale_factor, r.read('<h') * scale_factor))

        self.uvs = []
        for _ in range(uv_count):
            if is_new_world:
                self.uvs.append((r.read('<f'), r.read('<f')))
            else:
                self.uvs.append((float(r.read('<h')) / 256.0, float(r.read('<h')) / 256.0))

        self.normals = []
        for _ in range(normal_count):
            self.normals.append((r.read('<b') / 127.0, r.read('<b') / 127.0, r.read('<b') / 127.0))

        self.colors = []
        for _ in range(color_count):
            b, g, re, a = r.read('<B'), r.read('<B'), r.read('<B'), r.read('<B')
            self.colors.append((re / 255.0, g / 255.0, b / 255.0, a / 255.0))

        self.faces = []
        for _ in range(triangle_count):
            flags = r.read('<H')
            v1, v2, v3 = r.read('<H'), r.read('<H'), r.read('<H')
            self.faces.append({'flags': flags, 'indices': (v1, v2, v3)})

        self.skin_assignment_groups = []
        for _ in range(vertex_piece_count):
            self.skin_assignment_groups.append((r.read('<h'), r.read('<h')))

        self.face_material_groups = []
        for _ in range(triangle_material_count):
            self.face_material_groups.append((r.read('<H'), r.read('<H')))

        self.vertex_material_groups = []
        for _ in range(vertex_material_count):
            self.vertex_material_groups.append((r.read('<h'), r.read('<h')))

        self.mesh_ops = []
        for _ in range(mesh_op_count):
            val = r.read_raw(4)
            param1 = r.read('<B')
            type_field = r.read('<B')
            entry = {'param1': param1, 'type_field': type_field}
            if type_field != 4:
                entry['index1'] = struct.unpack_from('<H', val, 0)[0]
                entry['index2'] = struct.unpack_from('<H', val, 2)[0]
                entry['offset'] = 0.0
            else:
                entry['offset'] = struct.unpack_from('<f', val, 0)[0]
                entry['index1'] = 0
                entry['index2'] = 0
            self.mesh_ops.append(entry)


class WldHierarchicalSpriteDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_HIERARCHICAL_SPRITE_DEF
        self.flags = 0
        self.collision_volume_ref = -1
        self.center_offset = (0.0, 0.0, 0.0)
        self.bounding_radius = 0.0
        self.dags = []
        self.dm_sprites = []
        self.link_skin_updates = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        num_dags = r.read('<I')
        self.collision_volume_ref = r.read('<i')
        if self.flags & 0x1:
            self.center_offset = (r.read('<f'), r.read('<f'), r.read('<f'))
        if self.flags & 0x2:
            self.bounding_radius = r.read('<f')

        for _ in range(num_dags):
            dag = {
                'name_ref': r.read('<i'),
                'flags': r.read('<I'),
                'track_ref': r.read('<i'),
                'mesh_ref': r.read('<i'),
                'sub_dags': [],
            }
            sub_count = r.read('<I')
            for _ in range(sub_count):
                dag['sub_dags'].append(r.read('<I'))
            self.dags.append(dag)

        if self.flags & 0x200:
            skin_count = r.read('<I')
            for _ in range(skin_count):
                self.dm_sprites.append(r.read('<i'))
            for _ in range(skin_count):
                self.link_skin_updates.append(r.read('<I'))


class WldTrackDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_TRACK_DEF
        self.flags = 0
        self.frame_transforms = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        frame_count = r.read('<I')

        use_int16 = bool(self.flags & 0x08)
        for _ in range(frame_count):
            ft = {}
            if use_int16:
                rot_w = r.read('<h')
                rot_x = r.read('<h')
                rot_y = r.read('<h')
                rot_z = r.read('<h')
                ft['rotation'] = (rot_x, rot_y, rot_z, rot_w)
                ft['shift'] = (r.read('<h'), r.read('<h'), r.read('<h'))
                ft['scale'] = r.read('<h')
            else:
                scale_val = r.read('<b')
                sx = r.read('<b'); sy = r.read('<b'); sz = r.read('<b')
                ft['shift'] = (sx, sy, sz)
                ft['scale'] = scale_val
                rot_w = r.read('<b'); rot_x = r.read('<b'); rot_y = r.read('<b'); rot_z = r.read('<b')
                ft['rotation'] = (rot_x, rot_y, rot_z, rot_w)
            self.frame_transforms.append(ft)


class WldTrack(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_TRACK
        self.track_def_ref = -1
        self.flags = 0
        self.frame_ms = 0

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.track_def_ref = r.read('<i')
        self.flags = r.read('<I')
        if self.flags & 0x1:
            self.frame_ms = r.read('<i')


class WldMaterialDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_MATERIAL_DEF
        self.flags = 0
        self.render_method = 0
        self.rgb_pen = (0, 0, 0, 0)
        self.brightness = 0.0
        self.scaled_ambient = 0.0
        self.simple_sprite_ref = -1
        self.u_shift = 0.0
        self.v_shift = 0.0
        self.texture_name = ''

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        self.render_method = r.read('<I')
        self.rgb_pen = (r.read('<B'), r.read('<B'), r.read('<B'), r.read('<B'))
        self.brightness = r.read('<f')
        self.scaled_ambient = r.read('<f')
        self.simple_sprite_ref = r.read('<i')
        if self.flags & 0x2:
            self.u_shift = r.read('<f')
            self.v_shift = r.read('<f')


class WldMaterialPalette(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_MATERIAL_PALETTE
        self.flags = 0
        self.material_refs = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        material_count = r.read('<I')
        for _ in range(material_count):
            self.material_refs.append(r.read('<i'))


class WldSimpleSpriteDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_SIMPLE_SPRITE_DEF
        self.flags = 0
        self.current_frame = 0
        self.sleep = 0
        self.bitmap_refs = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        texture_ref_count = r.read('<I')
        if self.flags & 0x04:
            self.current_frame = r.read('<i')
        if self.flags & 0x08:
            self.sleep = r.read('<I')
        for _ in range(texture_ref_count):
            self.bitmap_refs.append(r.read('<i'))


class WldSimpleSprite(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_SIMPLE_SPRITE
        self.sprite_ref = -1
        self.flags = 0

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.sprite_ref = r.read('<i')
        self.flags = r.read('<I')


class WldBMInfo(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_BM_INFO
        self.texture_names = []
        self.bitmap_name = ''

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        texture_count = r.read('<i')
        for _ in range(texture_count + 1):
            name_len = r.read('<H')
            raw = r.read_raw(name_len)
            decoded = bytearray(len(raw))
            for j, b in enumerate(raw):
                decoded[j] = (b ^ _XOR_TABLE[j % 8]) & 0xFF
            name = bytes(decoded).rstrip(b'\x00').decode('latin-1', errors='replace')
            self.texture_names.append(name)
        if self.texture_names:
            self.bitmap_name = self.texture_names[0]


class WldParticleCloudDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_PARTICLE_CLOUD_DEF
        self.flags = 0
        self.particle_type = 0
        self.spawn_type = 0
        self.pcloud_flags = 0
        self.size = 0
        self.gravity = 0.0
        self.spawn_normal = (0.0, 0.0, 0.0)
        self.duration = 0
        self.spawn_radius = 0.0
        self.spawn_angle = 0.0
        self.lifespan = 0
        self.spawn_velocity_multiplier = 0.0
        self.spawn_velocity = (0.0, 0.0, 0.0)
        self.spawn_rate = 0
        self.spawn_scale = 0.0
        self.tint = (0, 0, 0, 0)
        self.spawn_box_min = (0.0, 0.0, 0.0)
        self.spawn_box_max = (0.0, 0.0, 0.0)
        self.box_min = (0.0, 0.0, 0.0)
        self.box_max = (0.0, 0.0, 0.0)
        self.blit_sprite_ref = -1

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        self.particle_type = r.read('<I')
        self.spawn_type = r.read('<I')
        self.pcloud_flags = r.read('<I')
        self.size = r.read('<I')
        self.gravity = r.read('<f')
        self.spawn_normal = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.duration = r.read('<I')
        self.spawn_radius = r.read('<f')
        self.spawn_angle = r.read('<f')
        self.lifespan = r.read('<I')
        self.spawn_velocity_multiplier = r.read('<f')
        self.spawn_velocity = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.spawn_rate = r.read('<I')
        self.spawn_scale = r.read('<f')
        self.tint = (r.read('<B'), r.read('<B'), r.read('<B'), r.read('<B'))
        if self.flags & 0x01:
            self.spawn_box_min = (r.read('<f'), r.read('<f'), r.read('<f'))
            self.spawn_box_max = (r.read('<f'), r.read('<f'), r.read('<f'))
        if self.flags & 0x02:
            self.box_min = (r.read('<f'), r.read('<f'), r.read('<f'))
            self.box_max = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.blit_sprite_ref = r.read('<i')


class WldPolyhedronDef(WldFragment):
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_POLYHEDRON_DEF
        self.flags = 0
        self.vertex_count = 0
        self.face_count = 0
        self.bounding_radius = 0.0
        self.scale_factor = 1.0
        self.vertices = []
        self.faces = []
        self.face_normals = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        self.vertex_count = r.read('<i')
        self.face_count = r.read('<i')
        self.bounding_radius = r.read('<f')
        if self.flags & 0x01:
            self.scale_factor = r.read('<f')
        for _ in range(self.vertex_count):
            self.vertices.append((r.read('<f'), r.read('<f'), r.read('<f')))
        for _ in range(self.face_count):
            v_count = r.read('<i')
            indices = tuple(r.read('<i') for _ in range(v_count))
            normal = None
            if self.flags & 0x02:
                normal = (r.read('<f'), r.read('<f'), r.read('<f'), r.read('<f'))
            self.faces.append(indices)
            self.face_normals.append(normal)


class WldGeneric(WldFragment):
    def __init__(self):
        super().__init__()
        self.raw_data = b''

    def read(self, r, is_new_world):
        self.raw_data = r.read_raw(r.size())


class BinReader(object):
    def __init__(self, data):
        self._data = data
        self._pos = 0
        self._len = len(data)

    def pos(self):
        return self._pos

    def size(self):
        return self._len - self._pos

    def eof(self):
        return self._pos >= self._len

    def read(self, fmt):
        size = struct.calcsize(fmt)
        if self._pos + size > self._len:
            return 0 if fmt[-1] in 'bBhHiIqQfd' else None
        val = struct.unpack_from(fmt, self._data, self._pos)
        self._pos += size
        return val[0]

    def read_raw(self, count):
        if self._pos + count > self._len:
            count = self._len - self._pos
        data = self._data[self._pos:self._pos + count]
        self._pos += count
        return data


class WldFile(object):
    def __init__(self, data):
        self.fragments = []
        self.string_hash = {}
        self.is_new_world = False
        self.zone_name = ''
        self._parse(data)

    def _decode_string(self, data):
        decoded = bytearray(len(data))
        for i, b in enumerate(data):
            decoded[i] = (b ^ _XOR_TABLE[i % 8]) & 0xFF
        return bytes(decoded)

    def _parse(self, data):
        r = BinReader(data)

        identifier = r.read('<i')
        if identifier != WLD_FILE_IDENTIFIER:
            return

        version = r.read('<i')
        if version == WLD_FORMAT_OLD:
            self.is_new_world = False
        elif version == WLD_FORMAT_NEW:
            self.is_new_world = True
        else:
            return

        fragment_count = r.read('<I')
        _bsp_region_count = r.read('<I')
        _unknown = r.read('<i')
        string_hash_size = r.read('<I')
        _unknown2 = r.read('<i')

        string_hash_bytes = r.read_raw(string_hash_size)
        decoded_hash = self._decode_string(string_hash_bytes)
        self.string_hash = self._parse_string_hash(decoded_hash)

        self.fragments = []
        for i in range(fragment_count):
            frag_size = r.read('<I')
            frag_id = r.read('<i')
            frag_data = r.read_raw(frag_size)

            frag = _create_fragment(frag_id, self.is_new_world)
            frag.frag_index = i
            frag.frag_code = frag_id

            name_ref = struct.unpack_from('<i', frag_data, 0)[0] if len(frag_data) >= 4 else -1
            frag.name = self.string_hash.get(name_ref, '')

            if not isinstance(frag, WldGeneric):
                try:
                    fr = BinReader(frag_data)
                    frag.read(fr, self.is_new_world)
                except Exception:
                    pass
            else:
                frag.raw_data = frag_data

            self.fragments.append(frag)

    def _parse_string_hash(self, decoded_hash):
        result = {}
        index = 0
        parts = decoded_hash.split(b'\x00')
        for part in parts:
            s = part.decode('latin-1', errors='replace')
            result[index] = s
            index += len(part) + 1
        return result

    def get_fragments_of_type(self, frag_code):
        return [f for f in self.fragments if f.frag_code == frag_code]

    def get_fragment_by_ref(self, ref):
        idx = ref - 1
        if 0 <= idx < len(self.fragments):
            return self.fragments[idx]
        return None

    def get_fragment_by_name(self, name):
        for f in self.fragments:
            if f.name.lower() == name.lower():
                return f
        return None

    def resolve_material_textures(self):
        textures = {}
        materials = self.get_fragments_of_type(FRAG_MATERIAL_DEF)
        bm_infos = {}
        for bm in self.get_fragments_of_type(FRAG_BM_INFO):
            if isinstance(bm, WldBMInfo):
                bm_infos[bm.frag_index + 1] = bm

        for mat in materials:
            if not isinstance(mat, WldMaterialDef):
                continue
            if mat.simple_sprite_ref > 0 and mat.simple_sprite_ref <= len(self.fragments):
                ss_inst = self.fragments[mat.simple_sprite_ref - 1]
                if isinstance(ss_inst, WldSimpleSprite) and ss_inst.sprite_ref > 0 and ss_inst.sprite_ref <= len(self.fragments):
                    ss_def = self.fragments[ss_inst.sprite_ref - 1]
                    if isinstance(ss_def, WldSimpleSpriteDef) and ss_def.bitmap_refs:
                        bm_ref = ss_def.bitmap_refs[0]
                        if bm_ref in bm_infos:
                            mat.texture_name = bm_infos[bm_ref].bitmap_name
            textures[mat.frag_index + 1] = mat.texture_name
        return textures


def _create_fragment(frag_code, is_new_world):
    if frag_code == FRAG_DM_SPRITE_DEF2:
        return WldDmSpriteDef2()
    elif frag_code == FRAG_HIERARCHICAL_SPRITE_DEF:
        return WldHierarchicalSpriteDef()
    elif frag_code == FRAG_TRACK_DEF:
        return WldTrackDef()
    elif frag_code == FRAG_TRACK:
        return WldTrack()
    elif frag_code == FRAG_MATERIAL_DEF:
        return WldMaterialDef()
    elif frag_code == FRAG_MATERIAL_PALETTE:
        return WldMaterialPalette()
    elif frag_code == FRAG_SIMPLE_SPRITE_DEF:
        return WldSimpleSpriteDef()
    elif frag_code == FRAG_SIMPLE_SPRITE:
        return WldSimpleSprite()
    elif frag_code == FRAG_BM_INFO:
        return WldBMInfo()
    elif frag_code == FRAG_PARTICLE_CLOUD_DEF:
        return WldParticleCloudDef()
    elif frag_code == FRAG_POLYHEDRON_DEF:
        return WldPolyhedronDef()
    return WldGeneric()


_XOR_TABLE = bytes([0x95, 0x3A, 0xC5, 0x2A, 0x95, 0x7A, 0x95, 0x6A])
