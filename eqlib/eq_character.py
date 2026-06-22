from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile
from eqlib.eq_wld import (
    WldHierarchicalSpriteDef, WldDmSpriteDef2, WldTrackDef, WldTrack,
    WldMaterialDef, WldMaterialPalette, WldPolyhedronDef,
)
from eqlib.eq_const import *
from eqlib.eq_ani import EqgAniFile, decompress_track_transform, parse_track_name
from eqlib.eq_mod import EqgModFile, EqgMdsFile, build_bone_tree
from eqlib.eq_mat43 import (mat43_from_quat_translation, mat43_multiply, mat43_identity,
    wld_zone_pos, wld_zone_nrm,
    wld_nonzone_pos, wld_nonzone_nrm,
    wld_nonzone_trans, wld_nonzone_quat,
    eqg_to_yup_pos, eqg_to_yup_normal,
    eqg_quat, flip_v)
from eqlib.eq_material import load_texture_from_archive


def load_character(archive, mdl_list):
    has_wld = archive.has_file_containing('.wld')

    if has_wld:
        return _load_character_wld(archive, mdl_list)

    return _load_eqg_mesh(archive, mdl_list)


def _load_eqg_mesh(archive, mdl_list):
    mod_files = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mod')]
    mds_files = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mds')]

    all_meshes = []
    tex_list = []
    mat_list = []

    for mod_fn in mod_files:
        data = archive.get_file(mod_fn)
        if not data:
            continue
        try:
            mod = EqgModFile(data)
            _build_eqg_geom(mod, archive, all_meshes, tex_list, mat_list)
        except Exception as e:
            print("[EQ Char] MOD build error: %s" % str(e))

    for mds_fn in mds_files:
        data = archive.get_file(mds_fn)
        if not data:
            continue
        try:
            mds = EqgMdsFile(data)
            _build_eqg_mds_geom(mds, archive, all_meshes, tex_list, mat_list)
        except Exception as e:
            print("[EQ Char] MDS build error: %s" % str(e))

    if not all_meshes:
        return 0

    mdl = NoeModel(all_meshes, [], [], NoeModelMaterials(tex_list, mat_list))
    mdl_list.append(mdl)
    return 1


def _compute_wld_bind_pose(wld, skeletons):
    from eqlib.eq_wld import WldTrack, WldTrackDef
    from eqlib.eq_ani import decompress_track_transform
    import math

    trackdefs = {}
    tracks = {}
    for f in wld.fragments:
        if isinstance(f, WldTrackDef):
            trackdefs[f.frag_index + 1] = f
        if isinstance(f, WldTrack):
            tracks[f.frag_index + 1] = f

    local_mats = {}
    world_mats = {}
    parents = {}

    for skel in skeletons:
        if not hasattr(skel, 'dags'):
            continue
        dags = skel.dags
        bone_mats = {}
        bone_parents = {}

        for i, dag in enumerate(dags):
            q = (0, 0, 0, 1)
            t = (0, 0, 0)
            if dag['track_ref'] > 0:
                track = tracks.get(dag['track_ref']) or wld.get_fragment_by_ref(dag['track_ref'])
                if isinstance(track, WldTrack):
                    td = trackdefs.get(track.track_def_ref)
                    if td and td.frame_transforms:
                        use16 = bool(td.flags & 0x08)
                        xform = decompress_track_transform(td.frame_transforms[0], use16)
                        q = xform['rotation']
                        t = xform['translation']

            m = mat43_from_quat_translation(q, t)
            bone_mats[i] = m
            bone_parents[i] = -1

        for i, dag in enumerate(dags):
            for child_idx in dag['sub_dags']:
                if 0 <= child_idx < len(dags):
                    bone_parents[child_idx] = i

        root_ids = [i for i in range(len(dags)) if bone_parents[i] < 0]
        if not root_ids:
            root_ids = [0]

        def compute_world(idx, parent_world):
            m = mat43_multiply(parent_world, bone_mats[idx]) if parent_world else bone_mats[idx]
            bone_mats[idx] = m
            for child_idx in dags[idx]['sub_dags']:
                if 0 <= child_idx < len(dags):
                    compute_world(child_idx, m)

        for rid in root_ids:
            compute_world(rid, None)

        local_mats[skel.frag_index] = bone_mats
        world_mats[skel.frag_index] = bone_mats

    return world_mats


def _transform_wld_verts(mesh, world_mats, skel_idx):
    if not mesh.skin_assignment_groups:
        return mesh.vertices

    vert_count = len(mesh.vertices)
    bone_for_vert = [-1] * vert_count
    v_start = 0
    for count, bone_idx in mesh.skin_assignment_groups:
        for vi in range(v_start, min(v_start + count, vert_count)):
            bone_for_vert[vi] = bone_idx
        v_start += count

    mats = world_mats.get(skel_idx, {})
    if not mats:
        return mesh.vertices

    result = list(mesh.vertices)
    for vi in range(vert_count):
        bi = bone_for_vert[vi]
        if bi < 0:
            continue
        bm = mats.get(bi)
        if bm is None:
            continue
        v = mesh.vertices[vi]
        x = v[0] * bm[0] + v[1] * bm[1] + v[2] * bm[2] + bm[3]
        y = v[0] * bm[4] + v[1] * bm[5] + v[2] * bm[6] + bm[7]
        z = v[0] * bm[8] + v[1] * bm[9] + v[2] * bm[10] + bm[11]
        result[vi] = (x, y, z)
    return result


def _load_character_wld(archive, mdl_list):
    wld_data = None
    for fn in archive.get_file_names():
        if fn.lower().endswith('.wld'):
            wld_data = archive.get_file(fn)
            break
    if wld_data is None:
        return 0

    wld = WldFile(wld_data)
    meshes = wld.get_fragments_of_type(FRAG_DM_SPRITE_DEF2)
    if not meshes:
        return 0

    skeletons = [f for f in wld.fragments if isinstance(f, WldHierarchicalSpriteDef)]
    world_mats = _compute_wld_bind_pose(wld, skeletons) if skeletons else {}
    skel_idx = skeletons[0].frag_index if skeletons else -1

    textures = wld.resolve_material_textures()
    palettes = wld.get_fragments_of_type(FRAG_MATERIAL_PALETTE)

    mat_by_palette = {}
    for pal in palettes:
        if isinstance(pal, WldMaterialPalette):
            for i, mr in enumerate(pal.material_refs):
                mat = wld.get_fragment_by_ref(mr)
                if isinstance(mat, WldMaterialDef):
                    mat_by_palette[i] = mat

    tex_list = []
    mat_list = []
    for pi in sorted(mat_by_palette.keys()):
        mat = mat_by_palette[pi]
        tex_name = mat.texture_name or textures.get(mat.frag_index + 1, '')
        mat_name = 'mat_%d' % len(mat_list)
        tex = None
        if tex_name:
            tex = load_texture_from_archive(archive, tex_name)
        if tex:
            tex_list.append(tex)
        noe_mat = NoeMaterial(mat_name, tex_name if tex else '')
        r, g, b, a = mat.rgb_pen
        noe_mat.setDiffuseColor(NoeVec4([r/255.0, g/255.0, b/255.0, a/255.0]))
        mat_list.append(noe_mat)
    if not mat_list:
        mat_list.append(NoeMaterial('mat_0', ''))

    all_meshes = []
    for mesh in meshes:
        if not isinstance(mesh, WldDmSpriteDef2) or not mesh.vertices or not mesh.faces:
            continue
        try:
            verts = _transform_wld_verts(mesh, world_mats, skel_idx)
            cx, cy, cz = mesh.center_offset
            pos_list = [NoeVec3(wld_nonzone_pos((v[0] + cx, v[1] + cy, v[2] + cz))) for v in verts]
            nrm_list = [NoeVec3(wld_nonzone_nrm(n)) for n in mesh.normals]
            uv_list = [NoeVec3((uv[0], -uv[1], 0.0)) for uv in mesh.uvs]
            if not pos_list:
                continue

            min_l = min(len(pos_list), len(uv_list), len(nrm_list))
            del pos_list[min_l:]; del uv_list[min_l:]; del nrm_list[min_l:]

            tri_list = []
            for f in mesh.faces:
                i0, i1, i2 = f['indices']
                if i0 < min_l and i1 < min_l and i2 < min_l:
                    tri_list.extend([i0, i1, i2])
            if tri_list:
                noe_mesh = NoeMesh(tri_list, pos_list, 'mesh_%d' % mesh.frag_index, mat_list[0].name)
                noe_mesh.setUVs(uv_list)
                noe_mesh.setNormals(nrm_list)
                all_meshes.append(noe_mesh)
        except Exception as e:
            print("[EQ WLD] mesh error: %s" % str(e))

    if not all_meshes:
        return 0

    mdl = NoeModel(all_meshes, [], [], NoeModelMaterials(tex_list, mat_list))
    mdl_list.append(mdl)
    return 1


def _build_eqg_mds_geom(mds, archive, all_meshes, tex_list, mat_list):
    _build_simple_materials(mds.materials, tex_list, mat_list, archive)

    for model in mds.models:
        if not model.vertices or not model.faces:
            continue

        pos_list = [NoeVec3(eqg_to_yup_pos(v.position)) for v in model.vertices]
        nrm_list = [NoeVec3(eqg_to_yup_normal(v.normal)) for v in model.vertices]
        uv_list = [NoeVec3((v.uv[0], -v.uv[1], 0.0)) for v in model.vertices]

        if not pos_list:
            continue

        faces_by_mat = {}
        for face in model.faces:
            mi = face.material_index
            if mi < 0:
                mi = 0
            if mi not in faces_by_mat:
                faces_by_mat[mi] = []
            faces_by_mat[mi].append(face)

        for mi, mat_faces in faces_by_mat.items():
            tri_list = []
            for face in mat_faces:
                i0, i1, i2 = face.indices
                if i0 < len(pos_list) and i1 < len(pos_list) and i2 < len(pos_list):
                    tri_list.extend([i0, i1, i2])
            if not tri_list:
                continue

            mat_name = mat_list[mi].name if mi < len(mat_list) else 'default'
            mesh_name = '%s_mat%d' % (model.name or 'mds', mi)
            noe_mesh = NoeMesh(tri_list, pos_list, mesh_name, mat_name)
            noe_mesh.setUVs(uv_list)
            noe_mesh.setNormals(nrm_list)
            all_meshes.append(noe_mesh)


def _build_bones_from_dags(dags, wld, parent_idx, parent_name=''):
    from inc_noesis import NoeBone, NoeMat43
    from eqlib.eq_wld import WldTrack, WldTrackDef
    from eqlib.eq_ani import decompress_track_transform

    trackdefs = {}
    tracks = {}
    for f in wld.fragments:
        if isinstance(f, WldTrackDef):
            trackdefs[f.frag_index + 1] = f
        if isinstance(f, WldTrack):
            tracks[f.frag_index + 1] = f

    bones = []
    bone_map = {}

    def process_dag(dag, pname, pidx):
        bone_name = wld.string_hash.get(dag['name_ref'], '')
        if not bone_name:
            bone_name = 'bone_%d' % len(bones)

        mat = NoeMat43()
        if dag['track_ref'] > 0:
            track = tracks.get(dag['track_ref']) or wld.get_fragment_by_ref(dag['track_ref'])
            if isinstance(track, WldTrack):
                td = trackdefs.get(track.track_def_ref)
                if td and td.frame_transforms:
                    use16 = bool(td.flags & 0x08)
                    xform = decompress_track_transform(td.frame_transforms[0], use16)
                    m = mat43_from_quat_translation(
                        wld_nonzone_quat(xform['rotation']),
                        wld_nonzone_trans(xform['translation']))
                    mat = NoeMat43((
                        NoeVec3((m[0], m[1], m[2])),
                        NoeVec3((m[4], m[5], m[6])),
                        NoeVec3((m[8], m[9], m[10])),
                        NoeVec3((m[3], m[7], m[11])),
                    ))

        bone = NoeBone(len(bones), bone_name, mat, pname, pidx)
        bones.append(bone)
        bone_map[bone_name.lower()] = bone.index
        new_pidx = bone.index

        for child_idx in dag['sub_dags']:
            if 0 <= child_idx < len(dags):
                process_dag(dags[child_idx], bone_name, new_pidx)

    for dag in dags:
        process_dag(dag, parent_name, parent_idx)

    return bones, bone_map


def _build_anims_from_wld(wld, bones, bone_map):
    anims = []
    tracks = wld.get_fragments_of_type(FRAG_TRACK)
    trackdefs_by_ref = {}

    for td in wld.get_fragments_of_type(FRAG_TRACK_DEF):
        if isinstance(td, WldTrackDef):
            trackdefs_by_ref[td.frag_index] = td

    anim_tracks = {}
    for track in tracks:
        if not isinstance(track, WldTrack):
            continue
        anim_name, model_name, piece_name = parse_track_name(track.name)
        if not anim_name:
            anim_name = 'anim'
        if anim_name not in anim_tracks:
            anim_tracks[anim_name] = {}

        td = trackdefs_by_ref.get(track.track_def_ref - 1)
        if td is None:
            td = wld.get_fragment_by_ref(track.track_def_ref)
        if isinstance(td, WldTrackDef):
            lower_piece = piece_name.lower()
            bone_idx = bone_map.get(lower_piece, -1)
            if bone_idx >= 0:
                anim_tracks[anim_name][bone_idx] = td

    for anim_name, bone_trackdefs in anim_tracks.items():
        max_frames = 1
        for td in bone_trackdefs.values():
            max_frames = max(max_frames, len(td.frame_transforms))

        if max_frames <= 1:
            continue

        kf_bones = []
        for bi in range(len(bones)):
            kf_bone = NoeKeyFramedBone(bi)
            td = bone_trackdefs.get(bi)
            if td and td.frame_transforms:
                use_int16 = bool(td.flags & 0x08)
                times = []
                rots = []
                trans = []
                for fi, ft in enumerate(td.frame_transforms):
                    t = fi / 10.0
                    xform = decompress_track_transform(ft, use_int16)
                    times.append(t)
                    rots.append(wld_nonzone_quat(xform['rotation']))
                    trans.append(wld_nonzone_trans(xform['translation']))
                if rots:
                    kf_bone.setRotation(
                        [NoeKeyFramedValue(times[i], NoeQuat(rots[i])) for i in range(len(times))],
                        type=noesis.NOEKF_ROTATION_QUATERNION_4,
                    )
                if trans:
                    kf_bone.setTranslation(
                        [NoeKeyFramedValue(times[i], NoeVec3(trans[i])) for i in range(len(times))],
                        type=noesis.NOEKF_TRANSLATION_VECTOR_3,
                    )
            kf_bones.append(kf_bone)

        anim = NoeKeyFramedAnim(anim_name, bones, kf_bones, 10.0)
        anims.append(anim)

    return anims


def _build_eqg_geom(mod, archive, all_meshes, tex_list, mat_list):
    _build_simple_materials(mod.materials, tex_list, mat_list, archive)

    pos_list = [NoeVec3(eqg_to_yup_pos(v.position)) for v in mod.vertices]
    nrm_list = [NoeVec3(eqg_to_yup_normal(v.normal)) for v in mod.vertices]
    uv_list = [NoeVec3((v.uv[0], -v.uv[1], 0.0)) for v in mod.vertices]

    if not pos_list:
        return

    faces_by_mat = {}
    for face in mod.faces:
        mi = face.material_index
        if mi < 0:
            mi = 0
        if mi not in faces_by_mat:
            faces_by_mat[mi] = []
        faces_by_mat[mi].append(face)

    for mi, mat_faces in faces_by_mat.items():
        tri_list = []
        for face in mat_faces:
            i0, i1, i2 = face.indices
            if i0 < len(pos_list) and i1 < len(pos_list) and i2 < len(pos_list):
                tri_list.extend([i0, i1, i2])
        if not tri_list:
            continue

        mat_name = mat_list[mi].name if mi < len(mat_list) else 'default'
        mesh_name = '%s_mat%d' % (mod.name or 'mesh', mi)
        noe_mesh = NoeMesh(tri_list, pos_list, mesh_name, mat_name)
        noe_mesh.setUVs(uv_list)
        noe_mesh.setNormals(nrm_list)
        all_meshes.append(noe_mesh)





def _build_bones_from_mod(mod_bones):
    bones = []
    children, roots = build_bone_tree(mod_bones)

    stack = [(r, -1, '') for r in reversed(roots)]
    orig_to_new = {}

    while stack:
        orig_idx, parent_idx, parent_name = stack.pop()
        if orig_idx in orig_to_new:
            continue

        bone = mod_bones[orig_idx]
        new_idx = len(bones)

        mat = mat43_from_quat_translation(eqg_quat(bone.rotation), eqg_to_yup_pos(bone.pivot))
        noe_mat = NoeMat43((
            NoeVec3((mat[0], mat[1], mat[2])),
            NoeVec3((mat[4], mat[5], mat[6])),
            NoeVec3((mat[8], mat[9], mat[10])),
            NoeVec3((mat[3], mat[7], mat[11])),
        ))

        noe_bone = NoeBone(new_idx, bone.name or 'bone_%d' % new_idx, noe_mat, parent_name, parent_idx)
        bones.append(noe_bone)
        orig_to_new[orig_idx] = new_idx

        child_list = children.get(orig_idx, [])
        for child_idx in reversed(child_list):
            if child_idx not in orig_to_new:
                stack.append((child_idx, new_idx, bone.name or ''))

    if not bones:
        bones = [NoeBone(0, 'root', NoeMat43())]

    return bones


def _build_skin_vertices(vertices, bone_count):
    result = []
    for vtx in vertices:
        sv = type('SkinVertex', (), {})()
        sv.position = vtx.position
        sv.normal = vtx.normal
        sv.uv = vtx.uv
        has_weights = any(w > 0.001 for w in vtx.bone_weights)
        if has_weights:
            sv.bone_indices = list(vtx.bone_indices[:4])
            sv.bone_weights = list(vtx.bone_weights[:4])
        else:
            sv.bone_indices = [0, 0, 0, 0]
            sv.bone_weights = [1.0, 0.0, 0.0, 0.0]
        result.append(sv)
    return result


def _build_simple_materials(materials, tex_list, mat_list, archive=None):
    if not materials:
        mat = NoeMaterial('default', '')
        mat_list.append(mat)
        return

    for i, mat_info in enumerate(materials):
        mat_name = mat_info.name if hasattr(mat_info, 'name') else mat_info.get('name', 'material_%d' % i)
        tex_name = ''
        props = mat_info.properties if hasattr(mat_info, 'properties') else mat_info.get('properties', [])
        for prop in props:
            if isinstance(prop, tuple) and len(prop) >= 3:
                pname, ptype, pval = prop[0], prop[1], prop[2]
                if ptype == 2 and pname.lower() in ('e_texturediffuse0', 'e_texturebump0', 'e_texturenormal0'):
                    tex_name = pval
                    break

        if tex_name and archive:
            tex_data = archive.get_file(tex_name)
            if tex_data is None:
                tex_name = ''

        found_tex = None
        if tex_name and archive:
            found_tex = load_texture_from_archive(archive, tex_name)
        noe_mat = NoeMaterial(mat_name, tex_name if found_tex else '')
        mat_list.append(noe_mat)
        if found_tex:
            tex_list.append(found_tex)


def _build_ani_from_eqga(ani, bones):
    from inc_noesis import NoeKeyFramedBone, NoeKeyFramedValue, NoeKeyFramedAnim, NoeQuat, NoeVec3

    bone_name_to_idx = {}
    for bone in bones:
        bone_name_to_idx[bone.name.lower()] = bone.index

    all_frames = {}
    max_time = 0.0

    for ba in ani.bone_anims:
        bone_idx = bone_name_to_idx.get(ba.name.lower(), -1)
        if bone_idx < 0:
            continue
        frame_times = []
        frame_rots = []
        frame_trans = []
        cumulative_ms = 0
        for frame in ba.frames:
            cumulative_ms += frame.milliseconds
            t = cumulative_ms / 1000.0
            frame_times.append(t)
            r = eqg_quat(frame.rotation)
            frame_rots.append(NoeQuat((r[0], r[1], r[2], r[3])))
            frame_trans.append(NoeVec3(eqg_to_yup_pos(frame.translation)))
            max_time = max(max_time, t)
        all_frames[bone_idx] = (frame_times, frame_rots, frame_trans)

    if not all_frames:
        return None

    kf_bones = []
    for bi in range(len(bones)):
        kf_bone = NoeKeyFramedBone(bi)
        if bi in all_frames:
            times, rots, trans = all_frames[bi]
            kf_bone.setRotation(
                [NoeKeyFramedValue(times[i], rots[i]) for i in range(len(times))],
                type=noesis.NOEKF_ROTATION_QUATERNION_4,
            )
            if any((t[0] != 0.0 or t[1] != 0.0 or t[2] != 0.0) for t in trans):
                kf_bone.setTranslation(
                    [NoeKeyFramedValue(times[i], trans[i]) for i in range(len(times))],
                    type=noesis.NOEKF_TRANSLATION_VECTOR_3,
                )
        kf_bones.append(kf_bone)

    fps = 10.0
    if max_time > 0:
        fps = max(1.0, len(all_frames[list(all_frames.keys())[0]][0]) / max_time)

    return NoeKeyFramedAnim('animation', bones, kf_bones, fps)


def _build_material_list(wld, archive, textures, tex_list, mat_list):
    tex_name_to_index = {}
    materials = wld.get_fragments_of_type(FRAG_MATERIAL_DEF)
    for mat in materials:
        if not isinstance(mat, WldMaterialDef):
            continue
        mat_name = mat.name if mat.name else 'mat_%d' % mat.frag_index
        tex_name = mat.texture_name or textures.get(mat.frag_index + 1, '')
        tex_obj = None
        if tex_name:
            tex_obj = load_texture_from_archive(archive, tex_name)
        r, g, b, a = mat.rgb_pen
        noe_mat = NoeMaterial(mat_name, tex_name if tex_obj else '')
        noe_mat.setDiffuseColor(NoeVec4([r/255.0, g/255.0, b/255.0, a/255.0]))
        if mat.flags & 0x01:
            noe_mat.setFlags(noesis.NMATFLAG_TWOSIDED)
        mat_list.append(noe_mat)
        if tex_obj:
            tex_list.append(tex_obj)
    return tex_name_to_index


def _build_skinned_mesh(mesh, bones, bone_map):
    pos_list = [NoeVec3(wld_nonzone_pos(v)) for v in mesh.vertices]
    uv_list = [NoeVec3((uv[0], uv[1], 0.0)) for uv in mesh.uvs]
    nrm_list = [NoeVec3(wld_nonzone_nrm(n)) for n in mesh.normals]

    if not pos_list:
        return None

    min_len = min(len(pos_list), len(uv_list), len(nrm_list))
    pos_list = pos_list[:min_len]
    uv_list = uv_list[:min_len]
    nrm_list = nrm_list[:min_len]

    tri_list = []
    for face in mesh.faces:
        i0, i1, i2 = face['indices']
        if i0 < min_len and i1 < min_len and i2 < min_len:
            tri_list.extend([i0, i1, i2])

    if not tri_list:
        return None

    weights = [NoeVertWeight([0, 0, 0, 0], [1.0, 0.0, 0.0, 0.0]) for _ in range(min_len)]

    noe_mesh = NoeMesh(tri_list, pos_list, mesh.name or 'mesh', 'mat_0')
    noe_mesh.setUVs(uv_list)
    noe_mesh.setNormals(nrm_list)
    noe_mesh.setWeights(weights)

    return noe_mesh
