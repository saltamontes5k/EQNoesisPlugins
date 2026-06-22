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
    points = []
    stream = io.BytesIO(data)
    magic = stream.read(4)
    if magic != b'EQGP':
        return points

    header_size = struct.unpack('<I', stream.read(4))[0]
    version = struct.unpack('<I', stream.read(4))[0]
    count = struct.unpack('<I', stream.read(4))[0]

    for _ in range(count):
        name_len = struct.unpack('<I', stream.read(4))[0]
        name = stream.read(name_len).rstrip(b'\x00').decode('latin-1', errors='replace')
        bone_name_len = struct.unpack('<I', stream.read(4))[0]
        bone_name = stream.read(bone_name_len).rstrip(b'\x00').decode('latin-1', errors='replace')
        translation = (struct.unpack('<f', stream.read(4))[0],
                      struct.unpack('<f', stream.read(4))[0],
                      struct.unpack('<f', stream.read(4))[0])
        rotation = (struct.unpack('<f', stream.read(4))[0],
                   struct.unpack('<f', stream.read(4))[0],
                   struct.unpack('<f', stream.read(4))[0],
                   struct.unpack('<f', stream.read(4))[0])
        scale = (struct.unpack('<f', stream.read(4))[0],
                struct.unpack('<f', stream.read(4))[0],
                struct.unpack('<f', stream.read(4))[0])
        points.append({
            'name': name,
            'bone_name': bone_name,
            'translation': translation,
            'rotation': rotation,
            'scale': scale,
        })
    return points


def parse_prt(data):
    renders = []
    stream = io.BytesIO(data)
    magic = stream.read(4)
    if magic != b'EQGR':
        return renders

    header_size = struct.unpack('<I', stream.read(4))[0]
    version = struct.unpack('<I', stream.read(4))[0]
    count = struct.unpack('<I', stream.read(4))[0]

    for _ in range(count):
        entry = {
            'id': struct.unpack('<I', stream.read(4))[0],
            'id2': struct.unpack('<I', stream.read(4))[0],
        }
        particle_point_len = struct.unpack('<I', stream.read(4))[0]
        entry['particle_point'] = stream.read(particle_point_len).rstrip(b'\x00').decode('latin-1', errors='replace')
        particle_suffix_len = struct.unpack('<I', stream.read(4))[0]
        entry['particle_suffix'] = stream.read(particle_suffix_len).rstrip(b'\x00').decode('latin-1', errors='replace')

        if version >= 2:
            unknown_count = struct.unpack('<I', stream.read(4))[0]
            entry['unknowns'] = []
            for _ in range(unknown_count):
                unk_len = struct.unpack('<I', stream.read(4))[0]
                entry['unknowns'].append(stream.read(unk_len).rstrip(b'\x00').decode('latin-1', errors='replace'))

        entry['duration'] = struct.unpack('<I', stream.read(4))[0]
        renders.append(entry)
    return renders


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
