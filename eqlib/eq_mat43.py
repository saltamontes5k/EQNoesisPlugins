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

def mat43_from_quat_translation_scale(quat, translation, scale):
    """T * R * S with an (sx, sy, sz) scale on the rotation columns."""
    m = mat43_from_quat_translation(quat, translation)
    sx, sy, sz = scale
    return (
        m[0] * sx, m[1] * sy, m[2] * sz, m[3],
        m[4] * sx, m[5] * sy, m[6] * sz, m[7],
        m[8] * sx, m[9] * sy, m[10] * sz, m[11],
    )

def mat43_multiply(a, b):
    return (
        a[0]*b[0] + a[1]*b[4] + a[2]*b[8],           a[0]*b[1] + a[1]*b[5] + a[2]*b[9],   a[0]*b[2] + a[1]*b[6] + a[2]*b[10],   a[0]*b[3] + a[1]*b[7] + a[2]*b[11] + a[3],
        a[4]*b[0] + a[5]*b[4] + a[6]*b[8],           a[4]*b[1] + a[5]*b[5] + a[6]*b[9],   a[4]*b[2] + a[5]*b[6] + a[6]*b[10],   a[4]*b[3] + a[5]*b[7] + a[6]*b[11] + a[7],
        a[8]*b[0] + a[9]*b[4] + a[10]*b[8],          a[8]*b[1] + a[9]*b[5] + a[10]*b[9],  a[8]*b[2] + a[9]*b[6] + a[10]*b[10],  a[8]*b[3] + a[9]*b[7] + a[10]*b[11] + a[11],
    )

def mat43_get_translation(m):
    return (m[3], m[7], m[11])

def mat43_inverse(m):
    """General 3x4 inverse (linear part + translation), or None when singular."""
    a00, a01, a02, tx, a10, a11, a12, ty, a20, a21, a22, tz = m
    det = a00*(a11*a22 - a12*a21) - a01*(a10*a22 - a12*a20) + a02*(a10*a21 - a11*a20)
    if abs(det) < 1e-12:
        return None
    i00 = (a11*a22 - a12*a21) / det
    i01 = (a02*a21 - a01*a22) / det
    i02 = (a01*a12 - a02*a11) / det
    i10 = (a12*a20 - a10*a22) / det
    i11 = (a00*a22 - a02*a20) / det
    i12 = (a02*a10 - a00*a12) / det
    i20 = (a10*a21 - a11*a20) / det
    i21 = (a01*a20 - a00*a21) / det
    i22 = (a00*a11 - a01*a10) / det
    ix = -(i00*tx + i01*ty + i02*tz)
    iy = -(i10*tx + i11*ty + i12*tz)
    iz = -(i20*tx + i21*ty + i22*tz)
    return (i00, i01, i02, ix, i10, i11, i12, iy, i20, i21, i22, iz)

def quat_normalize(q):
    x, y, z, w = q
    n = math.sqrt(x*x + y*y + z*z + w*w)
    if n < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    return (x/n, y/n, z/n, w/n)

def mat43_to_noemat43(m):
    """Pack a row-major 3x4 tuple into a NoeMat43.

    Probed in-host: NoeMat43's first three vec3s are the matrix ROWS
    (transformPoint computes the row dot-products), so rows pack straight
    through with the translation as the fourth vec3.
    """
    from inc_noesis import NoeMat43, NoeVec3
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

# Vemdas dual-path coordinate system (per-type negation, no Y/Z swap)
#
# Zones:    NegateX  => (-x, -y, z)
# Non-zone: NegateZ... was the original Vemdas rule; with Z-up output the
#           non-zone path collapses to identity (x, y, z), which is what these
#           helpers return now. See the block below for why.
# UVs: EQG negates V (D3D -> Noesis); WLD uses V negated as well.
#
# Bone quat (non-zone): identity
# Bone quat (zone): (-qx, -qy, qz, qw)
#
# EQG MOD/MDS: (-x, -y, z) for positions, (-nx, -ny, nz) for normals
# (The eqg_to_yup_* names are historical: they do not convert Z-up to Y-up,
# they are the EQG axis map. Noesis previews Z-up.)
# EQG quat: (qx, qy, -qz, qw) - see eqg_quat below (this line said
# (-qx, -qy, qz, qw) once, which contradicted the code and scattered the mesh)

# WLD data is EverQuest space, and EverQuest is +Z up (verified: the head
# bone of auk_chr and zof_chr sits at (0, 0, +2.2) in raw fragment space).
# Noesis previews +Z up - that is why the EQG map (-x,-y,z) shows ahf standing
# - so WLD must keep Z as Z. The maps below are the Vemdas dual path (zones
# negate X, non-zone negates Z, which normalises the mirrored authoring of the
# two content types) with the old Y<->Z swap removed: swapping Y and Z laid
# every .s3d model on its back, which reads as "the weights are broken" because
# the armature ends up rotated out of the mesh.
#
# If some other host wants Y up, pre-compose both paths with the same rotation;
# do NOT swap only one of them or zone and character data stop agreeing.

# --- WLD zone path ---
def wld_zone_pos(pos):
    return (-pos[0], -pos[1], pos[2])

def wld_zone_nrm(nrm):
    return (-nrm[0], -nrm[1], nrm[2])

def wld_zone_trans(t):
    return (-t[0], -t[1], t[2])

def wld_zone_quat(q):
    return (-q[0], -q[1], q[2], q[3])

# --- WLD non-zone (characters, equipment) path ---
def wld_nonzone_pos(pos):
    return (pos[0], pos[1], pos[2])

def wld_nonzone_nrm(nrm):
    return (nrm[0], nrm[1], nrm[2])

def wld_nonzone_trans(t):
    return (t[0], t[1], t[2])

def wld_nonzone_quat(q):
    return (q[0], q[1], q[2], q[3])

# --- EQG path ---
def eqg_to_yup_pos(pos):
    return (-pos[0], -pos[1], pos[2])

def eqg_to_yup_normal(nrm):
    return (-nrm[0], -nrm[1], nrm[2])

def eqg_quat(q):
    # EQG (.mod/.mds/.ani) rotations are stored conjugated ("transposed").
    # Our axis map is a frame rotation by pi about Z, which commutes with
    # conjugation as a sign flip, so the mapped form of the CONJUGATE is
    # (qx, qy, -qz, qw). Verified numerically: with this form, animated bone
    # pivots stay on their weighted vertices (120/121 vs 13/121 for ae3) and
    # rest pivots sit ~10x closer to the verts they carry, across mds
    # creatures, race bodies, and item .mod files alike.
    return (q[0], q[1], -q[2], q[3])

def noemat43_to_mat43(m):
    """Read a NoeMat43 back into this module's row-major 3x4 tuple."""
    try:
        rows = [m[0], m[1], m[2], m[3]]
    except Exception:
        rows = list(getattr(m, 'rows'))
    r0, r1, r2, r3 = rows
    return (r0[0], r0[1], r0[2], r3[0],
            r1[0], r1[1], r1[2], r3[1],
            r2[0], r2[1], r2[2], r3[2])

def mat43_to_quat(m):
    """Quaternion of the rotation part (assumes unit-scale columns).

    Row-major 3x4: R00=m0 R01=m1 R02=m2 / R10=m4 R11=m5 R12=m6 /
    R20=m8 R21=m9 R22=m10. The vector terms must be R21-R12, R02-R20 and
    R10-R01; writing them the other way round yields the CONJUGATE rotation,
    which is silent for symmetric mirror poses and very visible everywhere
    else (it is what crumpled models once the rest keys used it).
    """
    trace = m[0] + m[5] + m[10]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[9] - m[6]) / s
        y = (m[2] - m[8]) / s
        z = (m[4] - m[1]) / s
    elif m[0] > m[5] and m[0] > m[10]:
        s = math.sqrt(1.0 + m[0] - m[5] - m[10]) * 2.0
        w = (m[9] - m[6]) / s
        x = 0.25 * s
        y = (m[1] + m[4]) / s
        z = (m[2] + m[8]) / s
    elif m[5] > m[10]:
        s = math.sqrt(1.0 + m[5] - m[0] - m[10]) * 2.0
        w = (m[2] - m[8]) / s
        x = (m[1] + m[4]) / s
        y = 0.25 * s
        z = (m[6] + m[9]) / s
    else:
        s = math.sqrt(1.0 + m[10] - m[0] - m[5]) * 2.0
        w = (m[4] - m[1]) / s
        x = (m[2] + m[8]) / s
        y = (m[6] + m[9]) / s
        z = 0.25 * s
    return quat_normalize((x, y, z, w))

def mat43_decompose(m):
    """(quat, translation, scale) for a T*R*S matrix; scale from column norms."""
    t = (m[3], m[7], m[11])
    cols = ((m[0], m[4], m[8]), (m[1], m[5], m[9]), (m[2], m[6], m[10]))
    scale = []
    for c in cols:
        n = math.sqrt(c[0]*c[0] + c[1]*c[1] + c[2]*c[2])
        scale.append(n if n > 1e-9 else 1.0)
    sx, sy, sz = scale
    r = (m[0]/sx, m[1]/sy, m[2]/sz, 0.0,
         m[4]/sx, m[5]/sy, m[6]/sz, 0.0,
         m[8]/sx, m[9]/sy, m[10]/sz, 0.0)
    return mat43_to_quat(r), t, (sx, sy, sz)

def bone_matrix(b):
    """The NoeMat43 of a NoeBone, across host versions.

    Real Noesis keeps it in _matrix behind getMatrix(); older builds (and the
    offline harness stub) exposed .mat. Reading .mat unconditionally threw
    "'NoeBone' object has no attribute 'mat'" in the host and made every
    skinned .eqg/.s3d fail to build.
    """
    getter = getattr(b, 'getMatrix', None)
    if getter is not None:
        return getter()
    mat = getattr(b, 'mat', None)
    if mat is not None:
        return mat
    return getattr(b, '_matrix')


def rest_local_matrices(bones):
    """Bind-pose LOCAL transform per bone (parent world inverse * world).

    Animations that do not key every bone leave the rest to Noesis, which
    poses an unkeyed bone at its bind WORLD matrix - composed under a posed
    parent that flings the bone (and its vertices) away. Builders use these to
    emit rest keys for unkeyed bones instead.
    """
    worlds = [noemat43_to_mat43(bone_matrix(b)) for b in bones]
    out = []
    for i, b in enumerate(bones):
        p = getattr(b, 'parentIndex', -1)
        if 0 <= p < len(worlds):
            inv = mat43_inverse(worlds[p])
            out.append(mat43_multiply(inv, worlds[i]) if inv is not None else mat43_identity())
        else:
            out.append(worlds[i])
    return out

# --- UV V flip (all paths) ---
def flip_v(uv):
    return (uv[0], -uv[1])
