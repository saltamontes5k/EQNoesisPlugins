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
    """Mesh 0x36. Header to +96, then vertices (i16 x3 << scale, + centre),
    UVs (i16/256; floats in the newer format), normals (i8/128), colours,
    polygons {flags, v1, v2, v3}, vertex pieces {count, bone}, polygon
    material runs {count, material}. Source: Everquest_Model_Viewer wldMesh.
    """
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
        self.scale = r.read('<h')

        scale_factor = 1.0 / float(1 << self.scale)

        # Vertices are stored relative to the mesh centre; bake it in like
        # the 0x2C parser does so every builder sees world-ready positions.
        cx, cy, cz = self.center_offset
        self.vertices = []
        for _ in range(vertex_count):
            self.vertices.append((cx + r.read('<h') * scale_factor,
                                  cy + r.read('<h') * scale_factor,
                                  cz + r.read('<h') * scale_factor))

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

        # Mesh ops are rare; walk them with the 0x2C size rule so the stream
        # stays aligned when they do appear.
        self.mesh_ops = []
        for _ in range(mesh_op_count):
            op_type = r.read('<I')
            entry = {'type': op_type}
            if 1 <= op_type <= 4:
                entry['param'] = struct.unpack('<f', r.read_raw(4))[0]
            else:
                entry['param'] = 0.0
            entry['index1'] = r.read('<H')
            entry['index2'] = r.read('<H')
            self.mesh_ops.append(entry)


class WldDmSpriteDef(WldFragment):
    """The older mesh 0x2C (gequip's IT62 sword, IT1036), after quail: counts,
    palette 0x31 at +36, then float vertices from +68, UVs and normals,
    colours, 16-byte faces {flags, 4 x u16, v1, v2, v3}, mesh ops, vertex
    pieces {count, bone}; with 0x200 a u32 list; with 0x800 face material runs
    {count, material}. The centre is the three floats at +52 (+64 is a radius).
    Source: Everquest_Model_Viewer wldMesh2C.
    """
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_DM_SPRITE_DEF
        self.name_ref = -1
        self.flags = 0
        self.material_palette_ref = -1
        self.center_offset = (0.0, 0.0, 0.0)
        self.bounding_radius = 0.0
        self.vertices = []
        self.uvs = []
        self.normals = []
        self.colors = []
        self.faces = []
        self.skin_assignment_groups = []
        self.face_material_groups = []
        self.is_new_world = False

    def read(self, r, is_new_world):
        self.is_new_world = is_new_world
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        vertex_count = r.read('<I')
        triangle_count = r.read('<I')
        normal_count = r.read('<I')
        color_count = r.read('<I')
        poly_count = r.read('<I')
        mesh_op_count = r.read('<H')
        r.read('<H')  # padding
        piece_count = r.read('<I')
        self.material_palette_ref = r.read('<i')
        r.read('<i')  # unknown
        r.read('<i')  # unknown
        r.read('<i')  # unknown
        self.center_offset = (r.read('<f'), r.read('<f'), r.read('<f'))
        self.bounding_radius = r.read('<f')

        cx, cy, cz = self.center_offset
        self.vertices = []
        for _ in range(vertex_count):
            self.vertices.append((cx + r.read('<f'), cy + r.read('<f'), cz + r.read('<f')))

        self.uvs = []
        for _ in range(triangle_count):
            uv = (r.read('<f'), r.read('<f'))
            if len(self.uvs) < vertex_count:
                self.uvs.append(uv)

        self.normals = []
        for _ in range(normal_count):
            n = (r.read('<f'), r.read('<f'), r.read('<f'))
            if len(self.normals) < vertex_count:
                self.normals.append(n)

        self.colors = []
        for _ in range(color_count):
            b, g, re, a = r.read('<B'), r.read('<B'), r.read('<B'), r.read('<B')
            self.colors.append((re / 255.0, g / 255.0, b / 255.0, a / 255.0))

        self.faces = []
        for _ in range(poly_count):
            r.read('<H')  # flags
            r.read('<H')
            r.read('<H')
            r.read('<H')
            v1 = r.read('<H')
            v2 = r.read('<H')
            v3 = r.read('<H')
            self.faces.append({'flags': 0, 'indices': (v1, v2, v3)})

        for _ in range(mesh_op_count):
            op_type = r.read('<I')
            if 1 <= op_type <= 4:
                r.read_raw(4)
            r.read_raw(4)

        self.skin_assignment_groups = []
        for _ in range(piece_count):
            self.skin_assignment_groups.append((r.read('<H'), r.read('<H')))

        if self.flags & 0x200:
            list_count = r.read('<I')
            r.read_raw(list_count * 4)

        self.face_material_groups = []
        if self.flags & 0x800:
            run_count = r.read('<I')
            for _ in range(run_count):
                self.face_material_groups.append((r.read('<H'), r.read('<H')))
        else:
            self.face_material_groups.append((poly_count, 0))


class WldDmSprite(WldFragment):
    """Mesh instance 0x2D -> the mesh it draws (0x36 or 0x2C)."""
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_DM_SPRITE
        self.name_ref = -1
        self.flags = 0
        self.mesh_ref = -1

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.mesh_ref = r.read('<i')
        self.flags = r.read('<I')


class WldActorDef(WldFragment):
    """Actor 0x14 -> the meshes it draws (directly, or through a skeleton).
    Source: Everquest_Model_Viewer wldActorParts.
    """
    __slots__ = ('frag_index', 'frag_code', 'name', 'data', 'name_ref', 'flags',
                 'action_count', 'reference_count', 'references', 'raw_data')

    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_ACTOR_DEF
        self.name_ref = -1
        self.flags = 0
        self.action_count = 0
        self.reference_count = 0
        self.references = []
        self.raw_data = b''

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        r.read('<I')  # unknown
        self.action_count = r.read('<I')
        self.reference_count = r.read('<I')
        if self.flags & 0x1:
            r.read('<i')
        if self.flags & 0x2:
            r.read_raw(28)
        for _ in range(self.action_count):
            if r.eof():
                break
            n = r.read('<I')
            r.read_raw(4 + n * 4)
        self.references = []
        for _ in range(min(self.reference_count, 64)):
            if r.eof():
                break
            self.references.append(r.read('<i'))


class WldHierarchicalSprite(WldFragment):
    """Skeleton instance 0x11 -> the 0x10 skeleton definition it uses."""
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_HIERARCHICAL_SPRITE
        self.name_ref = -1
        self.flags = 0
        self.skeleton_ref = -1
        self.skeleton_ref_alt = -1

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        # EQMV reads the skeleton ref at +4; some writers put it after flags.
        self.skeleton_ref = r.read('<i')
        self.flags = r.read('<I')
        self.skeleton_ref_alt = r.read('<i')


class WldHierarchicalSpriteDef(WldFragment):
    """Skeleton 0x10: bones {name, flags, track -> 0x13, mesh -> 0x2D,
    children}; with flag 0x200 a list of skinned meshes follows. Rest pose =
    each bone's first key frame. Source: Everquest_Model_Viewer wldSkeleton.
    """
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
    """Track 0x12 (keyframes). Old WLDs: eight i16 per frame (w, x, y, z
    rotation; x, y, z shift over 256; scale over 256), whatever the track
    flags say. The newer format uses floats. Source: Everquest_Model_Viewer
    wldSkeleton/decodeTrack.
    """
    def __init__(self):
        super().__init__()
        self.frag_code = FRAG_TRACK_DEF
        self.flags = 0
        self.frame_transforms = []

    def read(self, r, is_new_world):
        self.name_ref = r.read('<i')
        self.flags = r.read('<I')
        frame_count = r.read('<I')

        for _ in range(frame_count):
            ft = {}
            if is_new_world:
                rot_w = r.read('<f')
                rot_x = r.read('<f')
                rot_y = r.read('<f')
                rot_z = r.read('<f')
                ft['rotation'] = (rot_x, rot_y, rot_z, rot_w)
                ft['shift'] = (r.read('<f'), r.read('<f'), r.read('<f'))
                ft['scale'] = 0
            else:
                rot_w = r.read('<h')
                rot_x = r.read('<h')
                rot_y = r.read('<h')
                rot_z = r.read('<h')
                ft['rotation'] = (rot_x, rot_y, rot_z, rot_w)
                ft['shift'] = (r.read('<h'), r.read('<h'), r.read('<h'))
                ft['scale'] = r.read('<h')
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
        self.texture_names = []
        self.layer_name = ''

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
        # A bitmap 0x03 can list more than one file: Luclin bodies list the
        # skin page and then the armor page drawn over it
        # ("humch0201.dds_layer"). Source: Everquest_Model_Viewer wldMaterial.
        name_total = min(texture_count + 1, 8) if texture_count >= 0 else 1
        for _ in range(name_total):
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
            self._pos = self._len
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
            # Fragment name references are negative offsets into the string
            # hash. Source: Everquest_Model_Viewer readWLD.
            frag.name = self.string_hash.get(-name_ref, '') if name_ref < 0 else ''

            if not isinstance(frag, WldGeneric):
                try:
                    fr = BinReader(frag_data)
                    frag.read(fr, self.is_new_world)
                except Exception:
                    pass
                if isinstance(frag, WldActorDef):
                    frag.raw_data = frag_data
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
        """Map material fragments to their texture names (+ overlay layer)."""
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
                            mat.texture_names = list(bm_infos[bm_ref].texture_names)
                            mat.texture_name = mat.texture_names[0] if mat.texture_names else ''
                            # The second name ending in _layer is the armor
                            # page drawn over the skin page.
                            mat.layer_name = ''
                            for extra in mat.texture_names[1:]:
                                if extra.lower().endswith('_layer'):
                                    mat.layer_name = extra[:-len('_layer')]
                                    break
            textures[mat.frag_index + 1] = mat.texture_name
        return textures


def _create_fragment(frag_code, is_new_world):
    if frag_code == FRAG_DM_SPRITE_DEF2:
        return WldDmSpriteDef2()
    elif frag_code == FRAG_DM_SPRITE_DEF:
        return WldDmSpriteDef()
    elif frag_code == FRAG_DM_SPRITE:
        return WldDmSprite()
    elif frag_code == FRAG_ACTOR_DEF:
        return WldActorDef()
    elif frag_code == FRAG_HIERARCHICAL_SPRITE:
        return WldHierarchicalSprite()
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
