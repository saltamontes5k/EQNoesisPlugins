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
)
from eqlib.eq_wldbuild import build_actor_models, build_all_meshes_model, _unique_mesh_namer
from eqlib.eq_ter import EqgTerFile
from eqlib.eq_zon import EqgZonFile
from eqlib.eq_mod import EqgModFile


# Instance + terrain vertex budget. A big zone (arginhiz has 7650 instances
# over 492k terrain verts) would otherwise push tens of millions of vertices
# at Noesis.
MAX_SCENE_VERTS = 1500000


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
            indices.append(remap[tri[0]])
            indices.append(remap[tri[1]])
            indices.append(remap[tri[2]])
        if not indices:
            continue
        mesh = NoeMesh(indices, sub_pos, namer('%s_ter_m%d' % (label, mi)), bank.material_name(gidx))
        mesh.setUVs(sub_uv)
        mesh.setNormals(sub_nrm)
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
                slot = [[], [], [], [], 0]   # pos, uv, nrm, tris, base
                acc[gidx] = slot
            base = slot[4]
            remap = {}
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


def load_modern_zone(archive, mdl_list):
    """.ter terrain plus the .mod models the .zon places on it."""
    ter_name = None
    for fn in archive.get_file_names():
        if fn.lower().endswith('.ter'):
            ter_name = fn
            break
    label = ter_name.rsplit('.', 1)[0] if ter_name else _zone_label(archive) or 'zone'

    bank = _SceneMaterials(archive)
    meshes = []
    budget = MAX_SCENE_VERTS

    ter = None
    if ter_name is not None:
        try:
            ter = EqgTerFile(archive.get_file(ter_name))
            print("[EQ Zone] %s v%d: %d verts / %d faces / %d materials"
                  % (ter_name, ter.version, len(ter.vertices), len(ter.faces), len(ter.materials)))
        except Exception as e:
            print("[EQ Zone] .ter parse failed: %s" % str(e))
            ter = None

    used = _build_ter_meshes(ter, bank, label, meshes, budget) if ter is not None else 0

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
        elif zon is not None:
            print("[EQ Zone] %s is a classic text zone (terrain params only)" % zon_name)

    if not meshes:
        # No terrain and no binary placement (e.g. nektulos.eqg: props only,
        # its classic .zon is terrain parameters): fall back to listing the
        # .mod props as separate models so the archive still previews.
        print("[EQ Zone] no .ter/.zon geometry; falling back to the prop list")
        from eqlib.eq_character import _load_eqg_models
        return _load_eqg_models(archive, mdl_list)

    mdl = NoeModel(meshes, [], [], NoeModelMaterials(bank.textures, bank.materials))
    try:
        mdl.name = label
    except Exception:
        pass
    mdl_list.append(mdl)
    print("[EQ Zone] scene: %d meshes, %d materials, %d terrain verts, %d instances"
          % (len(meshes), len(bank.materials), used, placed))
    return 1
