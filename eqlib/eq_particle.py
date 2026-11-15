import struct
import io
import math

from inc_noesis import *
import noesis


def build_particle_placeholder_geometry(particle, position=(0.0, 0.0, 0.0)):
    spawn_type = particle.spawn_type if hasattr(particle, 'spawn_type') else 0
    grav = particle.gravity if hasattr(particle, 'gravity') else 0.0
    radius = particle.spawn_radius if hasattr(particle, 'spawn_radius') else 0.5
    normal = particle.spawn_normal if hasattr(particle, 'spawn_normal') else (0.0, 0.0, 1.0)
    tint = particle.tint if hasattr(particle, 'tint') else (255, 255, 255, 255)
    lifespan = particle.lifespan if hasattr(particle, 'lifespan') else 1000
    spawn_rate = particle.spawn_rate if hasattr(particle, 'spawn_rate') else 1

    points = [(0.0, 0.0, 0.0)]
    faces = []

    if spawn_type == 1:
        segments = 12
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            px = position[0] + math.cos(angle) * radius
            py = position[1]
            pz = position[2] + math.sin(angle) * radius
            points.append((px, py, pz))
        for i in range(segments):
            a = i + 1
            b = (i + 1) % segments + 1
            faces.append((0, a, b))
            faces.append((0, b, a))

    elif spawn_type == 3:
        vel = particle.spawn_velocity if hasattr(particle, 'spawn_velocity') else (0.0, 0.0, 1.0)
        length = math.sqrt(vel[0]**2 + vel[1]**2 + vel[2]**2)
        if length > 0.001:
            vel = (vel[0]/length, vel[1]/length, vel[2]/length)
        tip = (position[0] + vel[0]*radius*2, position[1] + vel[1]*radius*2, position[2] + vel[2]*radius*2)
        points = [
            (position[0] - vel[0]*0.2, position[1] - vel[1]*0.2, position[2] - vel[2]*0.2),
            tip,
        ]
        faces = [(0, 1, 1)]

    else:
        w = radius
        points = [
            (position[0]-w, position[1]-w, position[2]),
            (position[0]+w, position[1]-w, position[2]),
            (position[0]+w, position[1]+w, position[2]),
            (position[0]-w, position[1]+w, position[2]),
        ]
        faces = [(0, 1, 2), (0, 2, 3)]

    pos_list = [NoeVec3(p) for p in points]
    tri_list = []
    for f in faces:
        tri_list.extend(f)

    if not tri_list:
        tri_list = [0, 0, 0]

    mesh = NoeMesh(tri_list, pos_list, 'particle_emitter', 'particle_mat')
    return mesh


def parse_pts(data):
    """EQPT attachment points: u32 count at +4, then 164-byte records
    {name[64], bone[64], pos3, rot3 (euler), scale3}.
    Source: Everquest_Model_Viewer readPTS.
    """
    points = []
    if len(data) < 12 or data[:4] != b'EQPT':
        return points
    count = struct.unpack_from('<I', data, 4)[0]
    for i in range(count):
        o = 12 + i * 164
        if o + 164 > len(data):
            break
        name = data[o:o + 64].split(b'\x00', 1)[0].decode('latin-1', errors='replace')
        bone = data[o + 64:o + 128].split(b'\x00', 1)[0].decode('latin-1', errors='replace')
        pos = struct.unpack_from('<3f', data, o + 128)
        rot = struct.unpack_from('<3f', data, o + 140)
        scale = struct.unpack_from('<3f', data, o + 152)
        points.append({
            'name': name,
            'bone_name': bone,
            'translation': pos,
            'rotation': rot,
            'scale': scale,
        })
    return points


def parse_prt(data):
    """PTCL particle triggers: u32 count at +4, u32 version at +8, then
    104-byte (v4) or 108-byte (v5) records {id, name[64], 9 x u32}.
    Source: Everquest_Model_Viewer readPRT.
    """
    renders = []
    if len(data) < 12 or data[:4] != b'PTCL':
        return renders
    count = struct.unpack_from('<I', data, 4)[0]
    version = struct.unpack_from('<I', data, 8)[0]
    size = 108 if version >= 5 else 104
    for i in range(count):
        o = 12 + i * size
        if o + size > len(data):
            break
        entry_id = struct.unpack_from('<I', data, o)[0]
        name_at = o + 4
        if version >= 5 and not _printable(data, o + 4) and _printable(data, o + 8):
            name_at = o + 8  # some custom v5 files put the extra u32 first
        point = data[name_at:name_at + 64].split(b'\x00', 1)[0].decode('latin-1', errors='replace')
        fields_at = name_at + 64
        trigger = struct.unpack_from('<I', data, fields_at)[0] if fields_at + 4 <= len(data) else 0
        anim = struct.unpack_from('<I', data, fields_at + 4)[0] if fields_at + 8 <= len(data) else 0
        duration = struct.unpack_from('<I', data, fields_at + 20)[0] if fields_at + 24 <= len(data) else 0
        renders.append({
            'id': entry_id,
            'particle_point': point,
            'triggered': trigger == 1,
            'anim': anim,
            'duration': duration,
        })
    return renders


def _printable(data, at):
    if at + 1 >= len(data):
        return False
    return (0x21 <= data[at] < 0x7F) and (0x20 <= data[at + 1] < 0x7F)


def parse_eff(data):
    stream = io.BytesIO(data)
    if len(data) < 8:
        return None

    header = struct.unpack('<I', stream.read(4))[0]
    header2 = struct.unpack('<I', stream.read(4))[0]

    blocks = []
    for _ in range(3):
        block = _parse_eff_block(stream)
        blocks.append(block)

    return {'header': (header, header2), 'blocks': blocks}


def _parse_eff_block(stream):
    label_len = struct.unpack('<I', stream.read(4))[0]
    label = stream.read(label_len).rstrip(b'\x00').decode('latin-1', errors='replace')
    effect_mode = struct.unpack('<i', stream.read(4))[0]
    sound_ref = struct.unpack('<i', stream.read(4))[0]

    subs = []
    for _ in range(3):
        sub = {}
        sprite_len = struct.unpack('<I', stream.read(4))[0]
        sub['sprite'] = stream.read(sprite_len).rstrip(b'\x00').decode('latin-1', errors='replace')
        sub['dag_index'] = struct.unpack('<i', stream.read(4))[0]
        sub['effect_type'] = struct.unpack('<i', stream.read(4))[0]
        sub['color'] = (struct.unpack('<B', stream.read(1))[0],
                       struct.unpack('<B', stream.read(1))[0],
                       struct.unpack('<B', stream.read(1))[0],
                       struct.unpack('<B', stream.read(1))[0])
        sub['gravity'] = struct.unpack('<f', stream.read(4))[0]
        sub['spawn_normal'] = (struct.unpack('<f', stream.read(4))[0],
                              struct.unpack('<f', stream.read(4))[0],
                              struct.unpack('<f', stream.read(4))[0])
        sub['spawn_radius'] = struct.unpack('<f', stream.read(4))[0]
        sub['spawn_angle'] = struct.unpack('<f', stream.read(4))[0]
        sub['lifespan'] = struct.unpack('<I', stream.read(4))[0]
        sub['spawn_velocity'] = struct.unpack('<f', stream.read(4))[0]
        sub['spawn_rate'] = struct.unpack('<I', stream.read(4))[0]
        sub['spawn_scale'] = struct.unpack('<f', stream.read(4))[0]
        subs.append(sub)

    extras = []
    for _ in range(12):
        ext = {}
        sprite_len = struct.unpack('<I', stream.read(4))[0]
        ext['sprite'] = stream.read(sprite_len).rstrip(b'\x00').decode('latin-1', errors='replace')
        ext['color'] = (struct.unpack('<B', stream.read(1))[0],
                       struct.unpack('<B', stream.read(1))[0],
                       struct.unpack('<B', stream.read(1))[0])
        ext['anim_speed'] = struct.unpack('<f', stream.read(4))[0]
        ext['angle_range_a'] = struct.unpack('<h', stream.read(2))[0]
        ext['angle_range_b'] = struct.unpack('<h', stream.read(2))[0]
        ext['radius'] = struct.unpack('<f', stream.read(4))[0]
        ext['effect_type'] = struct.unpack('<h', stream.read(2))[0]
        ext['scale'] = struct.unpack('<f', stream.read(4))[0]
        extras.append(ext)

    return {'label': label, 'mode': effect_mode, 'sound_ref': sound_ref,
            'subs': subs, 'extras': extras}
