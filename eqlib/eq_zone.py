from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile
from eqlib.eq_const import *
from eqlib.eq_material import load_texture_from_archive
from eqlib.eq_mat43 import (
    wld_zone_pos, wld_zone_nrm, wld_zone_trans, wld_zone_quat,
    mat43_from_quat_translation_scale, quat_multiply, quat_from_axis_angle,
    bone_matrix, mat43_to_noemat43,
)
from eqlib.eq_wldbuild import build_actor_models, build_all_meshes_model, _unique_mesh_namer
from eqlib.eq_ter import EqgTerFile
from eqlib.eq_zon import EqgZonFile
from eqlib.eq_mod import EqgModFile


# Instance + terrain vertex budget. A big zone (arginhiz has 7650 instances
# over 492k terrain verts) would otherwise push tens of millions of vertices
# at Noesis.
MAX_SCENE_VERTS = 1500000

# Baked per-vertex colours: the .zon LIT arrays are per-vertex RGBA for each
# instance and the .ter carries a per-vertex tint. EQ usually leaves the LIT
# alpha at 0, so alpha is forced opaque or everything renders invisible.
ZONE_VERTEX_COLORS = True
ZONE_MARKERS = True


def load_zone(archive, mdl_list):
    wld_data = _pick_wld(archive)
    if wld_data is None:
        return load_modern_zone(archive, mdl_list)

    wld = WldFile(wld_data)

    # One model per named actor (equipment catalogs and placed objects), else
    # every mesh as one model - matching Everquest_Model_Viewer's listing.
    zone_label = _zone_label(archive)
    try:
        actor_models = build_actor_models(wld, archive, axis='zone')
    except Exception as e:
        print("[EQ Zone] actor build failed: %s" % str(e))
        actor_models = []
    named = [m for m in actor_models if getattr(m, 'name', '') and not getattr(m, 'name').startswith('actor_')]
    if named:
        mdl_list.extend(named)
        print("[EQ Zone] %d named actor models" % len(named))
        return 1

    try:
        mdl = build_all_meshes_model(wld, archive, axis='zone', label=zone_label)
    except Exception as e:
        print("[EQ Zone] mesh build failed: %s" % str(e))
        mdl = None
    if mdl is None:
        print("[EQ Zone] No meshes loaded")
        return 0
    mdl_list.append(mdl)
    return 1


def _pick_wld(archive):
    for fn in archive.get_file_names():
        lower = fn.lower()
        if lower.endswith('.wld') and '_obj' not in lower and 'objects' not in lower and 'lights' not in lower:
            return archive.get_file(fn)
    for fn in archive.get_file_names():
        if fn.lower().endswith('.wld'):
            return archive.get_file(fn)
    return None


def _zone_label(archive):
    try:
        for fn in archive.get_file_names():
            if fn.lower().endswith('.wld'):
                return fn.rsplit('.', 1)[0]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Modern zones: .ter ground + .zon placed .mod props
# ---------------------------------------------------------------------------
class _SceneMaterials(object):
    """One shared material/texture list for a whole zone scene."""

    def __init__(self, archive):
        self.archive = archive
        self.textures = []
        self.materials = []
        self._index = {}
        self._tex_names = {}
        self._mode = {}

    def add(self, mat_info):
        from eqlib.eq_character import _diffuse_texture_name
        tex_name = _diffuse_texture_name(mat_info) if mat_info is not None else ''
        name = (mat_info.name if mat_info is not None else '') or 'zone_mat'
        key = (name.lower(), (tex_name or '').lower())
        if key in self._index:
            return self._index[key], tex_name
        idx = len(self.materials)
        tex = None
        if tex_name:
            tex = load_texture_from_archive(self.archive, tex_name)
        noe_mat = NoeMaterial(name, tex_name if tex is not None else '')
        # Untextured terrain/patch materials (EQ's "FailsafeShader", blocker
        # planes) otherwise glare pure white; grey reads as unpainted geometry.
        if tex is None:
            r, g, b, a = 140, 140, 140, 255
        elif mat_info is not None and hasattr(mat_info, 'rgb_pen'):
            r, g, b, a = mat_info.rgb_pen
        else:
            r, g, b, a = 255, 255, 255, 255
        noe_mat.setDiffuseColor(NoeVec4([r / 255.0, g / 255.0, b / 255.0, a / 255.0]))
        try:
            from eqlib.eq_character import _apply_shader_flags
            _apply_shader_flags(noe_mat, getattr(mat_info, 'shader', '') if mat_info is not None else '')
        except Exception:
            pass
        if tex is not None:
            self.textures.append(tex)
        self.materials.append(noe_mat)
        self._index[key] = idx
        self._tex_names[idx] = tex_name
        return idx, tex_name

    def material_name(self, idx):
        if 0 <= idx < len(self.materials):
            return self.materials[idx].name
        return ''


def _zone_uvs(vi, uvs, vert_count):
    # .ter/.mod pages are DDS: top-down rows, so the stored V is already right.
    if vi < len(uvs):
        u, v = uvs[vi]
        return NoeVec3((u, 1.0 - v, 0.0))
    return NoeVec3((0.0, 0.0, 0.0))


def _build_ter_meshes(ter, bank, label, out_meshes, budget):
    """One NoeMesh per material run of the terrain."""
    if not ter.vertices or not ter.faces:
        return 0
    map_pos = wld_zone_pos
    map_nrm = wld_zone_nrm
    pos = [NoeVec3(map_pos(v.position)) for v in ter.vertices]
    nrm = [NoeVec3(map_nrm(v.normal)) for v in ter.vertices]
    uv = [NoeVec3((v.uv[0], 1.0 - v.uv[1], 0.0)) for v in ter.vertices]
    tint = [NoeVec4([v.tint[0] / 255.0, v.tint[1] / 255.0, v.tint[2] / 255.0, 1.0])
            for v in ter.vertices]
    by_mat = {}
    for f in ter.faces:
        by_mat.setdefault(f.material_index if f.material_index >= 0 else 0, []).append(f.indices)

    namer = _unique_mesh_namer()
    used = 0
    for mi, tris in sorted(by_mat.items()):
        mat_info = ter.materials[mi] if 0 <= mi < len(ter.materials) else None
        gidx, _ = bank.add(mat_info)
        remap = {}
        sub_pos = []
        sub_uv = []
        sub_nrm = []
        sub_col = []
        use_col = False
        indices = []
        for tri in tris:
            if max(tri) >= len(pos):
                continue
            for vi in tri:
                if vi not in remap:
                    remap[vi] = len(sub_pos)
                    sub_pos.append(pos[vi])
                    sub_uv.append(uv[vi])
                    sub_nrm.append(nrm[vi])
                    sub_col.append(tint[vi])
            indices.append(remap[tri[0]])
            indices.append(remap[tri[1]])
            indices.append(remap[tri[2]])
        if not indices:
            continue
        mesh = NoeMesh(indices, sub_pos, namer('%s_ter_m%d' % (label, mi)), bank.material_name(gidx))
        mesh.setUVs(sub_uv)
        mesh.setNormals(sub_nrm)
        if sub_col and ZONE_VERTEX_COLORS:
            mesh.setColors(sub_col)
        out_meshes.append(mesh)
        used += len(sub_pos)
        if used > budget:
            print("[EQ Zone] terrain vertex budget reached (%d)" % used)
            break
    return used


def _instance_matrix(inst):
    """T * Rz * Ry * Rx * S, in the zone (== EQG) axis frame."""
    q = quat_multiply(
        quat_from_axis_angle((0.0, 0.0, 1.0), float(inst.rotation[0])),
        quat_multiply(
            quat_from_axis_angle((0.0, 1.0, 0.0), -float(inst.rotation[1])),
            quat_from_axis_angle((1.0, 0.0, 0.0), float(inst.rotation[2])),
        ),
    )
    s = float(inst.scale) if inst.scale > 0.0 else 1.0
    return mat43_from_quat_translation_scale(
        wld_zone_quat(q), wld_zone_trans(inst.translation), (s, s, s))


def _transform_point(m, p):
    return (m[0]*p[0] + m[1]*p[1] + m[2]*p[2] + m[3],
            m[4]*p[0] + m[5]*p[1] + m[6]*p[2] + m[7],
            m[8]*p[0] + m[9]*p[1] + m[10]*p[2] + m[11])


def _transform_normal(m, n):
    x = m[0]*n[0] + m[1]*n[1] + m[2]*n[2]
    y = m[4]*n[0] + m[5]*n[1] + m[6]*n[2]
    z = m[8]*n[0] + m[9]*n[1] + m[10]*n[2]
    ln = (x*x + y*y + z*z) ** 0.5
    if ln > 1e-9:
        return (x / ln, y / ln, z / ln)
    return (x, y, z)


def _build_instance_meshes(archive, zon, ter_instances, bank, label, out_meshes, budget):
    """Every .mod the .zon places, baked into one mesh per material."""
    from eqlib.eq_mat43 import eqg_to_yup_pos, eqg_to_yup_normal
    mod_cache = {}
    acc = {}   # material index -> [pos, uv, nrm, indices, vert_count]
    total = 0
    placed = 0
    missing = 0
    for inst in zon.instances:
        name = inst.model
        if not name or not name.lower().endswith('.mod'):
            continue
        data = archive.get_file(name)
        if data is None:
            missing += 1
            continue
        if name.lower() not in mod_cache:
            try:
                mod_cache[name.lower()] = EqgModFile(data)
            except Exception:
                mod_cache[name.lower()] = None
        mod = mod_cache[name.lower()]
        if mod is None or not mod.vertices or not mod.faces:
            continue
        m = _instance_matrix(inst)
        by_mat = {}
        for f in mod.faces:
            by_mat.setdefault(f.material_index if f.material_index >= 0 else 0, []).append(f.indices)
        verts = mod.vertices
        for mi, tris in by_mat.items():
            mat_info = mod.materials[mi] if 0 <= mi < len(mod.materials) else None
            gidx, _ = bank.add(mat_info)
            slot = acc.get(gidx)
            if slot is None:
                slot = [[], [], [], [], 0, []]   # pos, uv, nrm, tris, base, colour
                acc[gidx] = slot
            remap = {}
            lits = inst.lits
            for tri in tris:
                if max(tri) >= len(verts):
                    continue
                for vi in tri:
                    if vi not in remap:
                        v = verts[vi]
                        remap[vi] = len(slot[0])
                        slot[0].append(NoeVec3(_transform_point(m, eqg_to_yup_pos(v.position))))
                        slot[1].append(NoeVec3((v.uv[0], 1.0 - v.uv[1], 0.0)))
                        slot[2].append(NoeVec3(_transform_normal(m, eqg_to_yup_normal(v.normal))))
                        if vi < len(lits):
                            lit = lits[vi]
                            slot[5].append(NoeVec4([lit[0] / 255.0, lit[1] / 255.0,
                                                    lit[2] / 255.0, 1.0]))
                        else:
                            slot[5].append(NoeVec4([1.0, 1.0, 1.0, 1.0]))
                    slot[3].append(remap[vi])
            slot[4] = len(slot[0])
        total += len(verts)
        placed += 1
        if total > budget:
            print("[EQ Zone] instance vertex budget reached after %d instances (%d verts)"
                  % (placed, total))
            break

    namer = _unique_mesh_namer()
    for gidx in sorted(acc.keys()):
        slot = acc[gidx]
        if not slot[3]:
            continue
        mesh = NoeMesh(slot[3], slot[0], namer('%s_inst_m%d' % (label, gidx)), bank.material_name(gidx))
        mesh.setUVs(slot[1])
        mesh.setNormals(slot[2])
        if slot[5] and ZONE_VERTEX_COLORS:
            mesh.setColors(slot[5])
        out_meshes.append(mesh)
    return placed, missing


def _find_zon(archive, label):
    for fn in archive.get_file_names():
        if fn.lower().endswith('.zon'):
            return archive.get_file(fn), fn
    # Loose .zon next to the archive (arena.eqg has none inside).
    try:
        import os
        src = rapi.getLastCheckedName()
        if not src:
            return None, None
        try:
            folder = rapi.getDirForFilePath(src)
        except Exception:
            folder = os.path.dirname(src)
        stem = os.path.basename(src).rsplit('.', 1)[0]
        for cand in (stem + '.zon', label + '.zon'):
            path = os.path.join(folder, cand)
            if os.path.exists(path):
                return bytes(rapi.loadIntoByteArray(path)), cand
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Area volumes and point lights
# ---------------------------------------------------------------------------
def _grid_layout(models):
    """Lay models out on a grid, for archives that ship no placement data."""
    import math as _math
    boxes = []
    biggest = 1.0
    for mdl in models:
        lo = [1e18, 1e18, 1e18]
        hi = [-1e18, -1e18, -1e18]
        for mesh in mdl.meshes:
            for p in mesh.positions:
                for a in range(3):
                    if p[a] < lo[a]:
                        lo[a] = p[a]
                    if p[a] > hi[a]:
                        hi[a] = p[a]
        for a in range(3):
            if lo[a] > hi[a]:
                lo[a] = hi[a] = 0.0
        boxes.append((lo, hi))
        size = max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
        if size > biggest:
            biggest = size
    cell = biggest * 1.25
    cols = int(_math.ceil(_math.sqrt(len(models))))
    for i, mdl in enumerate(models):
        lo, hi = boxes[i]
        cx = (lo[0] + hi[0]) * 0.5
        cy = (lo[1] + hi[1]) * 0.5
        tx = (i % cols) * cell - (cols - 1) * cell * 0.5 - cx
        ty = (i // cols) * cell - cy
        for mesh in mdl.meshes:
            mesh.setPositions([NoeVec3((p[0] + tx, p[1] + ty, p[2])) for p in mesh.positions])
        try:
            for bone in getattr(mdl, 'bones', []):
                mat = bone_matrix(bone)
                moved = [list(mat[r]) for r in range(4)]
                moved[3] += tx
                moved[7] += ty
                bone.setMatrix(mat43_to_noemat43(moved))
        except Exception:
            pass
    print("[EQ Zone] no placement data: laid %d props out on a %dx grid"
          % (len(models), cols))


def _add_solid_material(bank, name, rgba):
    """A flat-coloured material for marker geometry (deduped by name)."""
    key = (name.lower(), '')
    if key in bank._index:
        return bank._index[key]
    idx = len(bank.materials)
    noe_mat = NoeMaterial(name, '')
    noe_mat.setDiffuseColor(NoeVec4(list(rgba)))
    noe_mat.setFlags(noesis.NMATFLAG_TWOSIDED)
    bank.materials.append(noe_mat)
    bank._index[key] = idx
    bank._tex_names[idx] = ''
    return idx


def _quat_euler(rz, ry, rx):
    return quat_multiply(
        quat_from_axis_angle((0.0, 0.0, 1.0), cz_safe(rz)),
        quat_multiply(
            quat_from_axis_angle((0.0, 1.0, 0.0), cz_safe(ry)),
            quat_from_axis_angle((1.0, 0.0, 0.0), cz_safe(rx)),
        ),
    )


def cz_safe(v):
    return float(v)


def _rotate_vec(q, v):
    """Rotate v by unit quaternion q (x, y, z, w)."""
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def _build_area_markers(zon, bank, label, out_meshes):
    """Wireframe boxes for the zone's AREA volumes."""
    if not zon.areas:
        return 0
    gidx = _add_solid_material(bank, 'zone_area', (0.15, 0.9, 0.25, 1.0))
    mat_name = bank.material_name(gidx)
    pos = []
    idxs = []
    for area in zon.areas:
        hx = abs(float(area.extents[0]))
        hy = abs(float(area.extents[1]))
        hz = abs(float(area.extents[2]))
        if hx <= 0.0 or hy <= 0.0 or hz <= 0.0:
            continue
        # AREA orientation follows the add-on: rotations stored RZ, RY, RX and
        # applied as euler (RX, RY, RZ), i.e. Rz * Ry * Rx.
        q = _quat_euler(area.orientation[0], area.orientation[1], area.orientation[2])
        cx, cy, cz = area.center
        corners = []
        for sx in (-hx, hx):
            for sy in (-hy, hy):
                for sz in (-hz, hz):
                    rx, ry, rz = _rotate_vec(q, (sx, sy, sz))
                    corners.append(wld_zone_pos((cx + rx, cy + ry, cz + rz)))
        # 12 edges, each a thin quad
        thick = max(1.5, 0.004 * max(hx, hy, hz))
        pairs = ((0, 1), (2, 3), (4, 5), (6, 7),
                 (0, 2), (1, 3), (4, 6), (5, 7),
                 (0, 4), (1, 5), (2, 6), (3, 7))
        for a, b in pairs:
            pa = corners[a]
            pb = corners[b]
            base = len(pos)
            # a cross of two thin quads so the edge reads from any angle
            for axis in (1, 2):
                for s in (-1.0, 1.0):
                    off = [0.0, 0.0, 0.0]
                    off[axis] = s * thick
                    pos.append(NoeVec3((pa[0] + off[0], pa[1] + off[1], pa[2] + off[2])))
                    pos.append(NoeVec3((pb[0] + off[0], pb[1] + off[1], pb[2] + off[2])))
                idxs.extend([base, base + 1, base + 2, base + 2, base + 1, base + 3])
                base += 4
    if not idxs:
        return 0
    mesh = NoeMesh(idxs, pos, '%s_areas' % label, mat_name)
    mesh.setNormals([NoeVec3((0.0, 0.0, 1.0))] * len(pos))
    out_meshes.append(mesh)
    return len(zon.areas)


def _build_light_markers(zon, bank, label, out_meshes):
    """Small octahedra at each point light, tinted by the light colour."""
    if not zon.lights:
        return 0
    by_colour = {}
    for light in zon.lights:
        r, g, b = (max(0.0, min(1.0, float(c))) for c in light.color)
        key = (round(r, 2), round(g, 2), round(b, 2))
        by_colour.setdefault(key, []).append(light)

    namer = _unique_mesh_namer()
    count = 0
    for key in sorted(by_colour.keys()):
        r, g, b = key
        gidx = _add_solid_material(bank, 'zone_light_%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255)),
                                   (r + 0.15, g + 0.15, b + 0.15, 1.0))
        pos = []
        idxs = []
        for light in by_colour[key]:
            size = max(4.0, min(float(light.radius) * 0.2, 40.0))
            c = wld_zone_pos(light.position)
            base = len(pos)
            pos.extend([
                NoeVec3((c[0] + size, c[1], c[2])),
                NoeVec3((c[0] - size, c[1], c[2])),
                NoeVec3((c[0], c[1] + size, c[2])),
                NoeVec3((c[0], c[1] - size, c[2])),
                NoeVec3((c[0], c[1], c[2] + size)),
                NoeVec3((c[0], c[1], c[2] - size)),
            ])
            for a, bb in ((0, 2), (2, 1), (1, 3), (3, 0)):
                idxs.extend([base + a, base + bb, base + 4])
                idxs.extend([base + bb, base + a, base + 5])
            count += 1
        if idxs:
            mesh = NoeMesh(idxs, pos, namer('%s_lights' % label), bank.material_name(gidx))
            out_meshes.append(mesh)
    return count


def load_modern_zone(archive, mdl_list):
    """.ter terrain plus the .mod models the .zon places on it."""
    # A zone can ship several .ter files (arxmentis has ter_am_main and
    # ter_arxmentis); all of them are ground, so load every one.
    ter_names = [fn for fn in archive.get_file_names() if fn.lower().endswith('.ter')]
    ter_name = ter_names[0] if ter_names else None
    label = _zone_label(archive) or (ter_name.rsplit('.', 1)[0] if ter_name else 'zone')
    if ter_name:
        label = ter_name.rsplit('.', 1)[0]

    bank = _SceneMaterials(archive)
    meshes = []
    budget = MAX_SCENE_VERTS

    used = 0
    ter = None
    for name in ter_names:
        try:
            ter = EqgTerFile(archive.get_file(name))
        except Exception as e:
            print("[EQ Zone] .ter parse failed (%s): %s" % (name, str(e)))
            continue
        print("[EQ Zone] %s v%d: %d verts / %d faces / %d materials"
              % (name, ter.version, len(ter.vertices), len(ter.faces), len(ter.materials)))
        used += _build_ter_meshes(ter, bank, name.rsplit('.', 1)[0], meshes, max(0, budget - used))
        if used > budget:
            print("[EQ Zone] terrain budget reached, skipping remaining .ter files")
            break

    zon_data, zon_name = _find_zon(archive, label)
    placed = missing = 0
    instance_count = 0
    if zon_data:
        try:
            zon = EqgZonFile(zon_data)
        except Exception as e:
            print("[EQ Zone] .zon parse failed: %s" % str(e))
            zon = None
        if zon is not None and zon.is_binary:
            instance_count = len(zon.instances)
            print("[EQ Zone] %s: %d models / %d instances / %d areas / %d lights"
                  % (zon_name, len(zon.models), len(zon.instances), len(zon.areas), len(zon.lights)))
            placed, missing = _build_instance_meshes(
                archive, zon, ter, bank, label, meshes, max(0, budget - used))
            print("[EQ Zone] placed %d instances (%d referenced models missing)"
                  % (placed, missing))
            n_areas = _build_area_markers(zon, bank, label, meshes) if ZONE_MARKERS else 0
            n_lights = _build_light_markers(zon, bank, label, meshes) if ZONE_MARKERS else 0
            if n_areas or n_lights:
                print("[EQ Zone] markers: %d area boxes, %d light markers" % (n_areas, n_lights))
        elif zon is not None:
            print("[EQ Zone] %s is a classic text zone (terrain params only)" % zon_name)

    if not meshes:
        # No terrain and no binary placement (e.g. nektulos.eqg: props only,
        # its classic .zon is terrain parameters): fall back to listing the
        # .mod props as separate models so the archive still previews.
        print("[EQ Zone] no .ter/.zon geometry; falling back to the prop list")
        from eqlib.eq_character import _load_eqg_models
        result = _load_eqg_models(archive, mdl_list)
        if len(mdl_list) > 1:
            # No placement data at all (atiiki's .zon is the classic text form,
            # terrain parameters only), so every .mod would sit at the origin
            # and they all pile up. Spread them out so the props can at least
            # be looked at individually.
            _grid_layout(mdl_list)
        return result

    mdl = NoeModel(meshes, [], [], NoeModelMaterials(bank.textures, bank.materials))
    try:
        mdl.name = label
    except Exception:
        pass
    mdl_list.append(mdl)
    print("[EQ Zone] scene: %d meshes, %d materials, %d terrain verts, %d instances"
          % (len(meshes), len(bank.materials), used, placed))
    return 1
