import math
import struct

def mat43_identity():
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
    )

def mat43_from_quat_translation(quat, translation):
    x, y, z, w = quat
    tx, ty, tz = translation
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return (
        1.0 - 2.0 * (yy + zz),      2.0 * (xy - wz),            2.0 * (xz + wy),            tx,
        2.0 * (xy + wz),            1.0 - 2.0 * (xx + zz),      2.0 * (yz - wx),            ty,
        2.0 * (xz - wy),            2.0 * (yz + wx),            1.0 - 2.0 * (xx + yy),      tz,
    )

def mat43_multiply(a, b):
    return (
        a[0]*b[0] + a[1]*b[4] + a[2]*b[8],           a[0]*b[1] + a[1]*b[5] + a[2]*b[9],   a[0]*b[2] + a[1]*b[6] + a[2]*b[10],   a[0]*b[3] + a[1]*b[7] + a[2]*b[11] + a[3],
        a[4]*b[0] + a[5]*b[4] + a[6]*b[8],           a[4]*b[1] + a[5]*b[5] + a[6]*b[9],   a[4]*b[2] + a[5]*b[6] + a[6]*b[10],   a[4]*b[3] + a[5]*b[7] + a[6]*b[11] + a[7],
        a[8]*b[0] + a[9]*b[4] + a[10]*b[8],          a[8]*b[1] + a[9]*b[5] + a[10]*b[9],  a[8]*b[2] + a[9]*b[6] + a[10]*b[10],  a[8]*b[3] + a[9]*b[7] + a[10]*b[11] + a[11],
    )

def mat43_to_noemat43(m):
    from inc_noesis import NoeMat43
    return NoeMat43((
        NoeVec3((m[0], m[1], m[2])),
        NoeVec3((m[4], m[5], m[6])),
        NoeVec3((m[8], m[9], m[10])),
        NoeVec3((m[3], m[7], m[11])),
    ))

def vec3_transform(v, m):
    x, y, z = v
    return (
        x * m[0] + y * m[1] + z * m[2] + m[3],
        x * m[4] + y * m[5] + z * m[6] + m[7],
        x * m[8] + y * m[9] + z * m[10] + m[11],
    )

def quat_from_axis_angle(axis, angle):
    half_angle = angle * 0.5
    s = math.sin(half_angle)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half_angle))

def quat_multiply(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
        aw*bw - ax*bx - ay*by - az*bz,
    )

def quat_conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])

def vec3_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def vec3_scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)

# Vemdas dual-path coordinate system (SwapYandZ + per-type negation)
#
# Zones:   SwapYandZ + NegateX  => (-x, z, y)
# Non-zone: SwapYandZ + NegateZ  => (x, z, -y)
# UVs: NegateY (V flip)
#
# Bone quat (non-zone): (qx, qz, -qy, qw)
# Bone quat (zone): (-qx, qz, qy, qw) — matches EQSage
#
# EQG MOD/MDS: (-x, -y, z) for positions, (-nx, -ny, nz) for normals
# EQG quat: (-qx, -qy, qz, qw)

# --- WLD zone path ---
def wld_zone_pos(pos):
    return (-pos[0], pos[2], pos[1])

def wld_zone_nrm(nrm):
    return (-nrm[0], nrm[2], nrm[1])

# --- WLD non-zone (characters, equipment) path ---
def wld_nonzone_pos(pos):
    return (pos[0], pos[2], -pos[1])

def wld_nonzone_nrm(nrm):
    return (nrm[0], nrm[2], -nrm[1])

def wld_nonzone_trans(t):
    return (t[0], t[2], -t[1])

def wld_nonzone_quat(q):
    return (q[0], q[2], -q[1], q[3])

# --- EQG path ---
def eqg_to_yup_pos(pos):
    return (-pos[0], -pos[1], pos[2])

def eqg_to_yup_normal(nrm):
    return (-nrm[0], -nrm[1], nrm[2])

def eqg_quat(q):
    return (-q[0], -q[1], q[2], q[3])

# --- UV V flip (all paths) ---
def flip_v(uv):
    return (uv[0], -uv[1])
