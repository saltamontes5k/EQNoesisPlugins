from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile
from eqlib.eq_const import *
from eqlib.eq_mod import EqgModFile, EqgMdsFile, build_bone_tree
from eqlib.eq_ani import EqgAniFile
from eqlib.eq_mat43 import (
    mat43_identity, mat43_multiply, mat43_from_quat_translation_scale,
    mat43_to_noemat43, mat43_inverse, quat_normalize, mat43_decompose,
    rest_local_matrices, eqg_to_yup_pos, eqg_to_yup_normal, eqg_quat,
)
from eqlib.eq_material import load_texture_from_archive
from eqlib.eq_wldbuild import (build_actor_models, build_wld_anims_multi,
                                build_bind_pose_anim, _unique_mesh_namer)

import math
import re


def load_character(archive, mdl_list):
    has_wld = archive.has_file_containing('.wld')

    if has_wld:
        return _load_character_wld(archive, mdl_list)

    return _load_eqg_models(archive, mdl_list)


# ===================================================================
# EQG (.mod / .mds / .ani) path
# ===================================================================
_PART_RE = re.compile(r'^([a-z0-9]+)_(\d\d)_(\d\d)_.+\.mod$', re.IGNORECASE)
_HAIR_RE = re.compile(r'^([a-z0-9]+)_(hair|tattoo|facial[a-z]*)_(\d\d)\.mod$', re.IGNORECASE)


def _find_body_mod(mod_names):
    """The body .mod is the one other .mod files extend (<race>_NN_NN_*.mod,
    <race>_hair_00.mod)."""
    stems = [fn.rsplit('.', 1)[0].lower() for fn in mod_names]
    for fn, stem in zip(mod_names, stems):
        prefix = stem + '_'
        if any(s.startswith(prefix) for s in stems if s != stem):
            return fn
    return mod_names[0] if mod_names else None


def _load_eqg_models(archive, mdl_list):
    """EQG characters and equipment.

    Skinned representation (Noesis convention, confirmed by the shipped NIF
    loader): NoeBone matrices carry the WORLD bind transform and mesh vertices
    stay in model space - Noesis composes keyed locals through the hierarchy
    and renders sum(w * posed * bindInv * v). (An older comment here claimed
    bone-space vertices, which is not what the code does.)
    """
    mod_names = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mod')]
    mds_names = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mds')]
    ani_names = [fn for fn in archive.get_file_names() if fn.lower().endswith('.ani')]

    # pre-parse animations: "<animcode>_<modelid>.ani" -> model id -> files
    anims_by_id = {}
    for fn in ani_names:
        data = archive.get_file(fn)
        if not data:
            continue
        try:
            ani = EqgAniFile(data)
            if ani.bone_anims and ani.duration_ms > 0:
                stem = fn.rsplit('.', 1)[0].lower()
                model_id = stem.rsplit('_', 1)[-1]
                anims_by_id.setdefault(model_id, []).append((fn, ani))
        except Exception as e:
            print("[EQ Char] ani parse error %s: %s" % (fn, str(e)))

    built = 0

    # MDS creature files: body + head variants share one skeleton
    for mds_fn in mds_names:
        data = archive.get_file(mds_fn)
        if not data:
            continue
        try:
            mds = EqgMdsFile(data)
            if not mds.models or not mds.bones:
                continue
            mdl = _build_mds_model(mds, mds_fn, archive, anims_by_id)
            if mdl is not None:
                mdl_list.append(mdl)
                built += 1
        except Exception as e:
            print("[EQ Char] MDS build error %s: %s" % (mds_fn, str(e)))

    if mds_names and built:
        return 1

    # .mod files: one body with parts, plus standalone skinned items
    body_fn = _find_body_mod(mod_names) if mod_names else None
    body_inv_binds = None
    body_mdl = None

    if body_fn is not None:
        data = archive.get_file(body_fn)
        if data:
            try:
                mod = EqgModFile(data)
                bones, bone_map, body_orig_to_new, body_inv_binds = \
                    _build_noe_bones_from_mod(mod.bones)
                stem = body_fn.rsplit('.', 1)[0].lower()
                mdl = _build_mod_model(mod, body_fn, archive, bones, bone_map,
                                       body_orig_to_new, body_inv_binds,
                                       anims_by_id.get(stem))
                if mdl is not None:
                    mdl_list.append(mdl)
                    body_mdl = mdl
                    built += 1

                # outfit/hair/tattoo parts skinned onto the body's skeleton
                for fn in mod_names:
                    if fn == body_fn:
                        continue
                    low = fn.lower()
                    if not (_PART_RE.match(low) or _HAIR_RE.match(low)):
                        continue
                    pdata = archive.get_file(fn)
                    if not pdata:
                        continue
                    try:
                        pmod = EqgModFile(pdata)
                        if not pmod.vertices or not pmod.faces:
                            continue
                        _build_mod_part_meshes(pmod, fn, archive, body_mdl,
                                               bone_map, body_inv_binds)
                    except Exception as e:
                        print("[EQ Char] part error %s: %s" % (fn, str(e)))
            except Exception as e:
                print("[EQ Char] MOD build error %s: %s" % (body_fn, str(e)))

    # standalone mods (equipment pieces, items with their own skeletons)
    for fn in mod_names:
        if fn == body_fn:
            continue
        low = fn.lower()
        stem = fn.rsplit('.', 1)[0].lower()
        if body_mdl is not None and (_PART_RE.match(low) or _HAIR_RE.match(low)):
            continue  # already handled as a body part
        data = archive.get_file(fn)
        if not data:
            continue
        try:
            mod = EqgModFile(data)
            if not mod.vertices or not mod.faces:
                continue
            bones, bone_map, orig_to_new, inv_binds = \
                _build_noe_bones_from_mod(mod.bones)
            mdl = _build_mod_model(mod, fn, archive, bones, bone_map,
                                   orig_to_new, inv_binds,
                                   anims_by_id.get(stem))
            if mdl is not None:
                mdl_list.append(mdl)
                built += 1
        except Exception as e:
            print("[EQ Char] MOD error %s: %s" % (fn, str(e)))

    if not built:
        # layout-only archives (armor .lay + textures; the geometry lives in
        # the race's .eqg) and other geometry-free archives
        has_lay = any(fn.lower().endswith('.lay') for fn in archive.get_file_names())
        has_geo = mod_names or mds_names or archive.has_file_containing('.wld')
        if has_lay and not has_geo:
            print("[EQ] Archive is an armor layout (.lay) + textures only; the "
                  "geometry lives in the race model archive, so there is nothing "
                  "to preview here.")
        elif not has_geo:
            print("[EQ] Archive holds no model geometry (no .wld/.mod/.mds); "
                  "nothing to preview here.")
        return 0

    # attachment-point markers from .pts files
    for fn in archive.get_file_names():
        if fn.lower().endswith('.pts') and mdl_list:
            pts_data = archive.get_file(fn)
            if pts_data:
                try:
                    from eqlib.eq_particle import parse_pts, build_particle_placeholder_geometry
                    for pt in parse_pts(pts_data):
                        mesh = build_particle_placeholder_geometry(
                            type('Dummy', (), {
                                'spawn_type': 3, 'gravity': 0.0,
                                'spawn_radius': 0.3, 'spawn_normal': pt['translation'],
                                'tint': (255, 128, 0, 255), 'lifespan': 1000,
                                'spawn_rate': 1, 'spawn_velocity': pt['translation'],
                            })(),
                            eqg_to_yup_pos(pt['translation']),
                        )
                        mdl_list[0].addMesh(mesh)
                except Exception:
                    pass

    return 1


# Per-axis scale keys are OFF. The bind now carries no scale and every key is a
# RATIO against the bone's stored scale, so a bone whose scale never changes
# keys a flat 1.0 (apx: 26,018 of 26,018 keys) and cancels exactly, the way it
# does in EQMV where pose and rest both carry the same scale. What is left is
# real animated squash, and the measured anisotropy across every character
# archive is at most 1.111 (vaf: 0.9 against 1.0), so the scalar average loses
# under 5% - not worth depending on NOEKF_SCALE_VECTOR_3, which no shipped
# Noesis plugin exercises.
EQG_VECTOR_SCALE = False


def _build_noe_bones_from_mod(mod_bones):
    """NoeBone list with WORLD bind matrices.

    Noesis skins GLTF-style: it composes each bone's keyframed LOCAL
    transforms through the hierarchy and renders sum(w * posed * bindInv * v)
    with vertices left in model space (the UE4/Oblivion loaders hand it world
    bind matrices plus model-space verts the same way). Unkeyed bones pose at
    their bind matrix, so the mesh shows the bind pose as stored.

    Returns (bones, {name -> new index}, {file bone index -> new index},
    [inverse bind matrices by new index]).

    .mod/.mds/.ani rotations are stored conjugated ("transposed"); eqg_quat
    folds that into the axis map (verified: animated pivots stay on their
    weighted verts only with the conjugated form).
    """
    bones = []
    children, roots = build_bone_tree(mod_bones)

    stack = [(r, -1, '') for r in reversed(roots)]
    orig_to_new = {}
    name_map = {}
    bone_names = []
    bone_parents = []
    local_mats = []
    rest_scales = []

    while stack:
        orig_idx, parent_idx, parent_name = stack.pop()
        if orig_idx in orig_to_new:
            continue

        bone = mod_bones[orig_idx]
        new_idx = len(bone_names)
        q = quat_normalize(eqg_quat(bone.rotation))
        # Bind carries rotation+translation only; the bone's stored scale is
        # kept aside and the animation divides by it. That makes the skinning
        # invariant to whether the host honours scale in the bone matrices:
        #   posed(scale A) * bind(scale R)^-1  ==  posed(A/R) * bind(scale 1)^-1
        # EQMV composes the full 3-axis scale both sides, so a constant scale
        # cancels there; dividing here reproduces that with scalar keys only.
        local = mat43_from_quat_translation_scale(
            q, eqg_to_yup_pos(bone.pivot), (1.0, 1.0, 1.0))
        bone_rest_scale = tuple(bone.scale) if bone.scale else (1.0, 1.0, 1.0)
        bone_names.append(bone.name or 'bone_%d' % new_idx)
        bone_parents.append(parent_idx)
        local_mats.append(local)
        rest_scales.append(bone_rest_scale)
        orig_to_new[orig_idx] = new_idx
        if bone.name:
            name_map[bone.name.lower()] = new_idx

        child_list = children.get(orig_idx, [])
        for child_idx in reversed(child_list):
            if child_idx not in orig_to_new:
                stack.append((child_idx, new_idx, bone.name or ''))

    # orphans (inconsistent child/sibling chains) become root-level bones
    for orig_idx in range(len(mod_bones)):
        if orig_idx not in orig_to_new:
            bone = mod_bones[orig_idx]
            new_idx = len(bone_names)
            q = quat_normalize(eqg_quat(bone.rotation))
            local = mat43_from_quat_translation_scale(
                q, eqg_to_yup_pos(bone.pivot), (1.0, 1.0, 1.0))
            bone_names.append(bone.name or 'bone_%d' % new_idx)
            bone_parents.append(-1)
            local_mats.append(local)
            rest_scales.append(tuple(bone.scale) if bone.scale else (1.0, 1.0, 1.0))
            orig_to_new[orig_idx] = new_idx
            if bone.name:
                name_map[bone.name.lower()] = new_idx

    if not local_mats:
        local_mats.append(mat43_identity())
        bone_names.append('root')
        bone_parents.append(-1)

    # compose world bind matrices (parents are always created first)
    worlds = []
    for i in range(len(local_mats)):
        p = bone_parents[i]
        w = mat43_multiply(worlds[p], local_mats[i]) if 0 <= p < len(worlds) else local_mats[i]
        worlds.append(w)

    bones = []
    for i in range(len(local_mats)):
        p = bone_parents[i]
        noe_bone = NoeBone(i, bone_names[i], mat43_to_noemat43(worlds[i]),
                           bone_names[p] if p >= 0 else '', p)
        noe_bone._eq_rest_scale = rest_scales[i]
        bones.append(noe_bone)

    inv_binds = []
    for w in worlds:
        inv = mat43_inverse(w)
        inv_binds.append(inv if inv is not None else mat43_identity())

    return bones, name_map, orig_to_new, inv_binds


def _vertex_weights(vtx, orig_to_new):
    """Normalized (bone index, weight) pairs for one vertex.

    Zero-weight slots are dropped, never kept: the previous else-branch had the
    test inverted, so outfit parts (which pass orig_to_new=None) lost every
    real weight and came back rigidly bound to the first empty slot's bone.
    """
    pairs = []
    for bi, bw in zip(vtx.bone_indices, vtx.bone_weights):
        if bw <= 0.001:
            continue
        idx = int(bi)
        if orig_to_new is not None:
            idx = orig_to_new.get(idx, -1)
        if idx >= 0:
            pairs.append((idx, bw))
    if not pairs:
        return [(0, 1.0)]
    total = sum(w for _, w in pairs)
    if total <= 0:
        return [(pairs[0][0], 1.0)]
    return [(b, w / total) for b, w in pairs]


def _diffuse_texture_name(mat_info):
    diffuse = ''
    fallback = ''
    for prop in mat_info.properties:
        if len(prop) >= 3 and prop[1] == 2:
            low = prop[0].lower()
            if low == 'e_texturediffuse0':
                diffuse = prop[2]
                break
            if low in ('e_texturebump0', 'e_texturenormal0') and not fallback:
                fallback = prop[2]
    return diffuse or fallback


def _apply_shader_flags(noe_mat, shader):
    """EQG materials say how they are drawn in their shader name.

    The prefix of the client's compiled pixel shader is what matters
    (Everquest_Model_Viewer draws "chroma*" with alphaTest 0.5 and "alpha*"
    blended). Chroma is the cut-out shader: hair strands, cloth fringes and
    straps are cut out on the page's alpha, so without the test they draw as
    solid quads and swallow whatever is behind them.
    """
    s = (shader or '').lower()
    try:
        if s.startswith('chroma'):
            noe_mat.setAlphaTest(0.5)
    except Exception:
        pass


def _build_mod_materials(model, archive):
    tex_list = []
    mat_list = []
    for mat_info in model.materials:
        tex_name = _diffuse_texture_name(mat_info)
        tex = None
        if tex_name and archive:
            tex = load_texture_from_archive(archive, tex_name)
        noe_mat = NoeMaterial(mat_info.name or 'mat', tex_name if tex else '')
        _apply_shader_flags(noe_mat, mat_info.shader)
        mat_list.append(noe_mat)
        if tex is not None:
            tex_list.append(tex)
    if not mat_list:
        mat_list.append(NoeMaterial('default', ''))
    return tex_list, mat_list


def _faces_by_material(faces, mat_count):
    faces_by_mat = {}
    for face in faces:
        mi = face.material_index
        if mi < 0 or mi >= mat_count:
            mi = 0
        faces_by_mat.setdefault(mi, []).append(face)
    return faces_by_mat


def _build_mod_model(mod, src_name, archive, bones, bone_map, orig_to_new,
                     inv_binds, anim_entry):
    """One model for a .mod (body or standalone skinned item).

    UV rule: EQG stores V=0 at the image top (D3D convention) and Noesis
    samples V=0 at the bottom, so V is flipped for every EQG mesh - skinned or
    static. Verified against Everquest_Model_Viewer's render: "V as stored"
    puts the skirt stripes on the legs and the hair mask on the face.
    """
    if not mod.vertices or not mod.faces:
        return None
    tex_list, mat_list = _build_mod_materials(mod, archive)

    skinned = bool(bones) and len(bones) > 0

    # vertices stay in model space; Noesis applies posed * bindInv per bone
    pos_list = [NoeVec3(eqg_to_yup_pos(v.position)) for v in mod.vertices]
    nrm_list = [NoeVec3(eqg_to_yup_normal(v.normal)) for v in mod.vertices]
    uv_list = [NoeVec3((v.uv[0], 1.0 - v.uv[1], 0.0)) for v in mod.vertices]

    name_mesh = _unique_mesh_namer()
    all_meshes = []
    for mi, mat_faces in _faces_by_material(mod.faces, len(mat_list)).items():
        tri_list = []
        vert_map = {}
        sub_pos = []
        sub_uv = []
        sub_nrm = []
        weights = []
        for face in mat_faces:
            i0, i1, i2 = face.indices
            for vi in (i0, i1, i2):
                if vi >= len(pos_list):
                    continue
                if vi not in vert_map:
                    vert_map[vi] = len(sub_pos)
                    sub_pos.append(pos_list[vi])
                    sub_uv.append(uv_list[vi])
                    sub_nrm.append(nrm_list[vi])
                    if skinned:
                        ws = _vertex_weights(mod.vertices[vi], orig_to_new)
                        weights.append(NoeVertWeight([b for b, _ in ws],
                                                     [w for _, w in ws]))
            if all(vi < len(pos_list) for vi in (i0, i1, i2)):
                tri_list.extend([vert_map[i0], vert_map[i1], vert_map[i2]])
        if not tri_list:
            continue
        mesh_name = name_mesh('%s_mat%d' % (mod.name or src_name.rsplit('.', 1)[0], mi))
        noe_mesh = NoeMesh(tri_list, sub_pos, mesh_name, mat_list[mi].name)
        noe_mesh.setUVs(sub_uv)
        noe_mesh.setNormals(sub_nrm)
        if skinned:
            noe_mesh.setWeights(weights)
        all_meshes.append(noe_mesh)

    if not all_meshes:
        return None

    anims = []
    if anim_entry and bones:
        anims = _build_anims_list(anim_entry, bones)
    if bones:
        tpose = build_bind_pose_anim(bones)
        if tpose is not None:
            anims.append(tpose)

    mats = NoeModelMaterials(tex_list, mat_list)
    mdl = NoeModel(all_meshes, bones, anims, mats)
    try:
        mdl.name = mod.name or src_name.rsplit('.', 1)[0]
    except Exception:
        pass
    return mdl


def _mod_parent_list(mod_bones):
    """Parent indices for EQG bones, derived from child/sibling links."""
    children, _ = build_bone_tree(mod_bones)
    parents = [-1] * len(mod_bones)
    for i, lst in children.items():
        for c in lst:
            if 0 <= c < len(parents):
                parents[c] = i
    return parents


def _build_mod_part_meshes(pmod, src_name, archive, body_mdl, body_bone_map,
                           body_inv_binds):
    """Outfit/hair/tattoo pieces skinned onto the body skeleton (bones are
    matched by name; unmatchable bones walk up to ROOT_BONE like EQMV's
    loadParts). Part vertices are model-space like the body's, so they go in
    as-is and only their weight bone indices get remapped onto the body.
    """
    if not pmod.vertices or not pmod.faces or body_mdl is None:
        return
    tex_list, mat_list = _build_mod_materials(pmod, archive)

    body_mats = body_mdl.mats
    for t in tex_list:
        if not any(x.name == t.name for x in body_mats.textures):
            body_mats.textures.append(t)
    mat_index_map = {}
    for m in mat_list:
        existing = next((i for i, mm in enumerate(body_mats.materials) if mm.name == m.name), None)
        if existing is None:
            body_mats.materials.append(m)
            mat_index_map[m.name] = len(body_mats.materials) - 1
        else:
            mat_index_map[m.name] = existing

    # body bone indices by name (case-insensitive)
    body_name_map = {}
    for b in body_mdl.bones:
        body_name_map[b.name.lower()] = b.index

    # part bone -> body bone remap; walk up the part's parents on a miss
    part_parents = _mod_parent_list(pmod.bones)
    remap = [0] * len(pmod.bones)
    for i, b in enumerate(pmod.bones):
        mapped = -1
        cur = i
        for _ in range(len(pmod.bones) + 1):
            nm = ((pmod.bones[cur].name or '') if 0 <= cur < len(pmod.bones) else '').lower()
            if nm in body_name_map:
                mapped = body_name_map[nm]
                break
            if nm == 'root_bone':
                mapped = body_name_map.get('root_bone', body_name_map.get('root', 0))
                break
            if cur < 0:
                break
            cur = part_parents[cur]
        remap[i] = mapped if mapped >= 0 else 0

    # part vertices stay in model space; weights reference the mapped body bones
    pos_list = [NoeVec3(eqg_to_yup_pos(v.position)) for v in pmod.vertices]
    nrm_list = [NoeVec3(eqg_to_yup_normal(v.normal)) for v in pmod.vertices]
    uv_list = [NoeVec3((v.uv[0], 1.0 - v.uv[1], 0.0)) for v in pmod.vertices]  # D3D -> Noesis V flip

    name_mesh = _unique_mesh_namer()
    piece_label = src_name.rsplit('.', 1)[0]
    for mi, mat_faces in _faces_by_material(pmod.faces, len(mat_list)).items():
        tri_list = []
        vert_map = {}
        sub_pos = []
        sub_uv = []
        sub_nrm = []
        weights = []
        for face in mat_faces:
            i0, i1, i2 = face.indices
            for vi in (i0, i1, i2):
                if vi >= len(pos_list):
                    continue
                if vi not in vert_map:
                    vert_map[vi] = len(sub_pos)
                    sub_pos.append(pos_list[vi])
                    sub_uv.append(uv_list[vi])
                    sub_nrm.append(nrm_list[vi])
                    # part bone -> body bone; several part bones can land on
                    # the same body bone, so merge instead of repeating it.
                    keys = []
                    acc = {}
                    for bi, bw in _vertex_weights(pmod.vertices[vi], None):
                        mb = remap[bi] if 0 <= bi < len(remap) else 0
                        if mb in acc:
                            acc[mb] += bw
                        else:
                            acc[mb] = bw
                            keys.append(mb)
                    weights.append(NoeVertWeight(keys, [acc[k] for k in keys]))
            if all(vi < len(pos_list) for vi in (i0, i1, i2)):
                tri_list.extend([vert_map[i0], vert_map[i1], vert_map[i2]])
        if not tri_list:
            continue
        mesh_name = name_mesh('%s_mat%d' % (piece_label, mi))
        noe_mesh = NoeMesh(tri_list, sub_pos, mesh_name, mat_list[mi].name)
        noe_mesh.setUVs(sub_uv)
        noe_mesh.setNormals(sub_nrm)
        noe_mesh.setWeights(weights)
        body_mdl.meshes.append(noe_mesh)


def _build_mds_model(mds, src_name, archive, anims_by_id):
    """MDS creature: body piece + first head piece on one skeleton
    (Everquest_Model_Viewer's default view). .mds vertices are always 32
    bytes; weights are per-piece records.
    """
    tex_list, mat_list = _build_mod_materials(mds, archive)
    bones, bone_map, orig_to_new, inv_binds = _build_noe_bones_from_mod(mds.bones)

    heads = [m for m in mds.models if re.search(r'HE\d\d$', m.name or '', re.IGNORECASE)]
    bodies = [m for m in mds.models if m not in heads]
    if bodies:
        use = bodies[:1] + heads[:1]
    else:
        use = mds.models[:1]

    stem = src_name.rsplit('.', 1)[0].lower()
    anims = []
    if bones:
        anims = _build_anims_list(anims_by_id.get(stem), bones)
        tpose = build_bind_pose_anim(bones)
        if tpose is not None:
            anims.append(tpose)

    name_mesh = _unique_mesh_namer()
    all_meshes = []
    for piece in use:
        pos_list = [NoeVec3(eqg_to_yup_pos(v.position)) for v in piece.vertices]
        nrm_list = [NoeVec3(eqg_to_yup_normal(v.normal)) for v in piece.vertices]
        uv_list = [NoeVec3((v.uv[0], 1.0 - v.uv[1], 0.0)) for v in piece.vertices]  # D3D -> Noesis V flip

        for mi, mat_faces in _faces_by_material(piece.faces, len(mat_list)).items():
            tri_list = []
            vert_map = {}
            sub_pos = []
            sub_uv = []
            sub_nrm = []
            weights = []
            for face in mat_faces:
                i0, i1, i2 = face.indices
                for vi in (i0, i1, i2):
                    if vi >= len(pos_list):
                        continue
                    if vi not in vert_map:
                        vert_map[vi] = len(sub_pos)
                        sub_pos.append(pos_list[vi])
                        sub_uv.append(uv_list[vi])
                        sub_nrm.append(nrm_list[vi])
                        ws = _vertex_weights(piece.vertices[vi], orig_to_new)
                        weights.append(NoeVertWeight([b for b, _ in ws],
                                                     [w for _, w in ws]))
                if all(vi < len(pos_list) for vi in (i0, i1, i2)):
                    tri_list.extend([vert_map[i0], vert_map[i1], vert_map[i2]])
            if not tri_list:
                continue
            mesh_name = name_mesh('%s_%s_mat%d' % (stem, piece.name or 'body', mi))
            noe_mesh = NoeMesh(tri_list, sub_pos, mesh_name, mat_list[mi].name)
            noe_mesh.setUVs(sub_uv)
            noe_mesh.setNormals(sub_nrm)
            noe_mesh.setWeights(weights)
            all_meshes.append(noe_mesh)

    if not all_meshes:
        return None
    mats = NoeModelMaterials(tex_list, mat_list)
    mdl = NoeModel(all_meshes, bones, anims, mats)
    try:
        mdl.name = stem
    except Exception:
        pass
    return mdl


def _anim_display_name(ani_fn):
    stem = ani_fn.rsplit('.', 1)[0]
    m = re.search(r'^(.*)_[a-z0-9]+$', stem, re.IGNORECASE)
    return (m.group(1) if m else stem).upper()


def _build_anims_list(anim_entries, bones):
    anims = []
    for ani_fn, ani in (anim_entries or []):
        anim = _build_ani_from_eqga(ani, bones, _anim_display_name(ani_fn))
        if anim is not None:
            anims.append(anim)
    return anims


def _build_ani_from_eqga(ani, bones, anim_name):
    """EQGA keyframes: 44-byte keys {u32 ms (absolute), pos3, quat, scale3}.
    Keyframes are bone-local, composed by Noesis through the hierarchy.
    """
    bone_name_to_idx = {}
    rest_scales = {}
    for bone in bones:
        bone_name_to_idx[bone.name.lower()] = bone.index
        rest_scales[bone.index] = getattr(bone, '_eq_rest_scale', (1.0, 1.0, 1.0))

    all_frames = {}
    max_time = 0.0
    for ba in ani.bone_anims:
        bone_idx = bone_name_to_idx.get(ba.name.lower(), -1)
        if bone_idx < 0 or not ba.frames:
            continue
        frame_times = []
        frame_rots = []
        frame_trans = []
        frame_scales = []
        for frame in ba.frames:
            t = frame.milliseconds / 1000.0
            frame_times.append(t)
            r = eqg_quat(frame.rotation)
            frame_rots.append(NoeQuat(r))
            frame_trans.append(NoeVec3(eqg_to_yup_pos(frame.translation)))
            # Per-axis scale, not an average: model-specific bones carry
            # strongly non-uniform keys (apx's CHEST_CLAV_PADL01 is
            # (0.273, 0.254, 0.589)) and collapsing them to one scalar skews
            # every vertex that bone owns.
            s = frame.scale
            # ratio against the bind scale (the bind carries no scale)
            rs = rest_scales.get(bone_idx, (1.0, 1.0, 1.0))
            frame_scales.append((
                s[0] / rs[0] if rs[0] > 1e-6 else s[0],
                s[1] / rs[1] if rs[1] > 1e-6 else s[1],
                s[2] / rs[2] if rs[2] > 1e-6 else s[2],
            ))
            if t > max_time:
                max_time = t
        all_frames[bone_idx] = (frame_times, frame_rots, frame_trans, frame_scales)

    if not all_frames:
        return None

    rest_locals = rest_local_matrices(bones)
    kf_bones = []
    for bi in range(len(bones)):
        kf_bone = NoeKeyFramedBone(bi)
        if bi in all_frames:
            times, rots, trans, scales = all_frames[bi]
            kf_bone.setRotation(
                [NoeKeyFramedValue(times[i], rots[i]) for i in range(len(times))],
                type=noesis.NOEKF_ROTATION_QUATERNION_4,
            )
            # EQG .ani keys carry the FULL local translation (110 of 118 ae3
            # tracks equal the rest pivot per frame) - always set them, since
            # an unset component may otherwise evaluate as zero and collapse
            # the skeleton during playback.
            kf_bone.setTranslation(
                [NoeKeyFramedValue(times[i], trans[i]) for i in range(len(times))],
                type=noesis.NOEKF_TRANSLATION_VECTOR_3,
            )
            # Scale keys: SCALAR_1 (a plain float) is the well-trodden path and
            # stays for uniform scales. Bones that carry non-uniform scale
            # (apx's CHEST_CLAV_PADL01 is (0.273, 0.254, 0.589)) need the
            # per-axis form instead - averaging them skewed the whole mesh.
            # Some tracks carry garbage (gcst_ba_1_ae3 spikes to -404 on a lip
            # bone); skip the scale track entirely for those.
            uniform = True
            for sc in scales:
                if abs(sc[0] - sc[1]) > 1e-4 or abs(sc[1] - sc[2]) > 1e-4:
                    uniform = False
                    break
            if uniform:
                flat = [sc[0] for sc in scales]
                if all(0.001 <= v <= 16.0 for v in flat):
                    kf_bone.setScale(
                        [NoeKeyFramedValue(times[i], flat[i]) for i in range(len(times))],
                        type=noesis.NOEKF_SCALE_SCALAR_1,
                    )
            elif EQG_VECTOR_SCALE and all(0.001 <= v <= 16.0 for sc in scales for v in sc):
                kf_bone.setScale(
                    [NoeKeyFramedValue(times[i], NoeVec3(scales[i])) for i in range(len(times))],
                    type=noesis.NOEKF_SCALE_VECTOR_3,
                )
            elif not EQG_VECTOR_SCALE:
                flat = [(sc[0] + sc[1] + sc[2]) / 3.0 for sc in scales]
                if all(0.001 <= v <= 16.0 for v in flat):
                    kf_bone.setScale(
                        [NoeKeyFramedValue(times[i], flat[i]) for i in range(len(times))],
                        type=noesis.NOEKF_SCALE_SCALAR_1,
                    )
        else:
            # Unkeyed bone: pin it to its rest LOCAL. Noesis poses an unkeyed
            # bone at its bind WORLD matrix, so the moment a parent is keyed
            # the child (and its vertices) shoot off - the "one wing on the
            # wrong side" / "pelvis rotated" glitches while scrubbing a blend.
            q, tr, sc = mat43_decompose(rest_locals[bi])
            kt = (0.0, max_time)
            kf_bone.setRotation([NoeKeyFramedValue(t, NoeQuat(q)) for t in kt],
                                type=noesis.NOEKF_ROTATION_QUATERNION_4)
            kf_bone.setTranslation([NoeKeyFramedValue(t, NoeVec3(tr)) for t in kt],
                                   type=noesis.NOEKF_TRANSLATION_VECTOR_3)
            if abs(sc[0] - sc[1]) < 1e-4 and abs(sc[1] - sc[2]) < 1e-4:
                kf_bone.setScale([NoeKeyFramedValue(t, sc[0]) for t in kt],
                                 type=noesis.NOEKF_SCALE_SCALAR_1)
            else:
                kf_bone.setScale([NoeKeyFramedValue(t, NoeVec3(sc)) for t in kt],
                                 type=noesis.NOEKF_SCALE_VECTOR_3)
        kf_bones.append(kf_bone)

    fps = 30.0
    if max_time > 0:
        first_track = all_frames[next(iter(all_frames))]
        fps = max(1.0, len(first_track[0]) / max_time)

    return NoeKeyFramedAnim(anim_name, bones, kf_bones, fps)


# ===================================================================
# WLD (.s3d) path - actor-driven, with a legacy fallback
# ===================================================================
def _companion_wlds():
    """WLDs of companion animation archives sitting next to the opened file
    (<race>_chr.s3d -> <race>_chr2.s3d + global3_chr.s3d; Luclin bodies keep
    their rest poses locally but their animations in the companions).
    """
    import os
    try:
        src = rapi.getLastCheckedName()
    except Exception:
        return []
    if not src:
        return []
    try:
        dir_path = rapi.getDirForFilePath(src)
    except Exception:
        dir_path = os.path.dirname(src)
    base = os.path.basename(src).lower()
    stem = base.rsplit('.', 1)[0] if '.' in base else base

    companions = []
    if stem.endswith('_chr'):
        companions.append(stem[:-len('_chr')] + '_chr2.s3d')
        companions.append('global3_chr.s3d')
    elif stem.endswith('_chr2'):
        companions.append('global3_chr.s3d')
    else:
        companions.append(stem + '_chr2.s3d')

    wlds = []
    for name in companions:
        if not name or name == base:
            continue
        path = os.path.join(dir_path, name)
        if not os.path.exists(path):
            continue
        try:
            data = rapi.loadIntoByteArray(path)
            comp = PfsArchive.from_bytes(bytes(data))
            for fn in comp.get_file_names():
                if fn.lower().endswith('.wld'):
                    wd = comp.get_file(fn)
                    if wd:
                        wlds.append(WldFile(wd))
        except Exception as e:
            print("[EQ WLD Char] companion %s: %s" % (name, str(e)))
    return wlds


def _attach_companion_anims(models):
    """Pull animations from companion archives into each skinned model."""
    if not models:
        return
    companions = _companion_wlds()
    if not companions:
        return
    for mdl in models:
        if not mdl.bones:
            continue
        try:
            anims = build_wld_anims_multi(companions, mdl.bones, 'nonzone')
            if anims:
                mdl.anims = list(mdl.anims) + anims
        except Exception as e:
            print("[EQ WLD Char] anim attach failed: %s" % str(e))


def _load_character_wld(archive, mdl_list):
    wld_data = None
    for fn in archive.get_file_names():
        if fn.lower().endswith('.wld'):
            wld_data = archive.get_file(fn)
            break
    if wld_data is None:
        return 0

    wld = WldFile(wld_data)

    try:
        models = build_actor_models(wld, archive, axis='nonzone', with_anims=True)
    except Exception as e:
        print("[EQ WLD Char] actor build failed: %s" % str(e))
        import traceback
        traceback.print_exc()
        models = []
    if models:
        _attach_companion_anims(models)
        mdl_list.extend(models)
        return 1

    return _load_character_wld_legacy(wld, archive, mdl_list)


def _load_character_wld_legacy(wld, archive, mdl_list):
    """Fallback: assemble every mesh with the first skeleton's bind pose."""
    from eqlib.eq_wld import WldDmSpriteDef2, WldHierarchicalSpriteDef
    meshes = wld.get_fragments_of_type(FRAG_DM_SPRITE_DEF2)
    if not meshes:
        return 0

    from eqlib.eq_wldbuild import compute_skeleton, WldMaterialBank
    from eqlib.eq_wldbuild import _bone_for_vertex_map, _build_part_meshes

    skeletons = [f for f in wld.fragments if isinstance(f, WldHierarchicalSpriteDef)]
    bank = WldMaterialBank(wld, archive)

    world_mats = None
    if skeletons:
        _, _, _, world_mats = compute_skeleton(wld, skeletons[0], 'nonzone')

    name_mesh = _unique_mesh_namer()
    all_meshes = []
    for mesh in meshes:
        if not mesh.vertices or not mesh.faces:
            continue
        try:
            if world_mats is not None and mesh.skin_assignment_groups:
                bone_of = _bone_for_vertex_map(mesh.skin_assignment_groups, len(mesh.vertices), None)
            else:
                bone_of = None
            label = name_mesh(mesh.name or ('mesh_%d' % mesh.frag_index))
            all_meshes.extend(_build_part_meshes(
                mesh, bone_of, world_mats, bank, 'nonzone', label))
        except Exception as e:
            print("[EQ WLD] mesh error: %s" % str(e))

    if not all_meshes:
        return 0

    mdl = NoeModel(all_meshes, [], [], NoeModelMaterials(bank.tex_list, bank.mat_list))
    mdl_list.append(mdl)
    return 1
