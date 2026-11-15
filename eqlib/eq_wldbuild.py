"""WLD model building shared by the zone, character, and equipment loaders.

Actor-driven building follows Everquest_Model_Viewer: an .s3d offers one
model per actor (0x14 -> 0x2D mesh instances / 0x11 skeleton instances),
else all meshes as one. Skeleton rest poses come from each bone's first
track frame, including the i16 bone scale in the last track field.
"""
import re
import struct

from inc_noesis import *
import noesis
import rapi

from eqlib.eq_wld import (
    WldFile, WldDmSpriteDef2, WldDmSpriteDef, WldDmSprite, WldActorDef,
    WldHierarchicalSprite, WldHierarchicalSpriteDef, WldTrackDef, WldTrack,
    WldMaterialDef, WldMaterialPalette, WldParticleCloudDef, BinReader,
)
from eqlib.eq_const import *
from eqlib.eq_mat43 import (
    mat43_identity, mat43_multiply, mat43_from_quat_translation_scale,
    mat43_to_noemat43, mat43_get_translation, mat43_decompose, rest_local_matrices,
    wld_zone_pos, wld_zone_nrm, wld_zone_trans, wld_zone_quat,
    wld_nonzone_pos, wld_nonzone_nrm, wld_nonzone_trans, wld_nonzone_quat,
)
from eqlib.eq_ani import decompress_track_transform
from eqlib.eq_material import load_texture_from_archive, load_layered_texture


# ---------------------------------------------------------------- meshes
def resolve_mesh_frag(wld, ref):
    """Resolve a mesh reference: a 0x36/0x2C directly, or a 0x2D instance."""
    if not ref or ref <= 0:
        return None
    frag = wld.get_fragment_by_ref(ref)
    if isinstance(frag, (WldDmSpriteDef2, WldDmSpriteDef)):
        return frag
    if isinstance(frag, WldDmSprite):
        mesh = wld.get_fragment_by_ref(frag.mesh_ref)
        if isinstance(mesh, (WldDmSpriteDef2, WldDmSpriteDef)):
            return mesh
    return None


class WldMaterialBank(object):
    """Builds deduplicated Noesis materials for WLD palette entries."""

    def __init__(self, wld, archive):
        self.wld = wld
        self.archive = archive
        wld.resolve_material_textures()
        self._palette_cache = {}
        self.tex_list = []
        self.mat_list = []
        self._mat_index = {}
        self.mat_vmode = {}

    def _texture_vmode(self, name):
        """'dds' for a top-down DDS page, 'bmp' for bottom-up BMP data.

        The V mapping has to match the decoder's row order, not the content
        type: everything Luclin+ ships DDS and would otherwise come out upside
        down, while classic .s3d BMP pages need the negated V.
        """
        if not name:
            return 'bmp'
        stem = name.rsplit('.', 1)[0]
        for cand in (name, stem + '.dds', stem + '.bmp', stem + '.tga'):
            data = self.archive.get_file(cand)
            if data is None:
                continue
            if data[:4] == b'DDS ':
                return 'dds'
            if data[:2] == b'BM':
                return 'bmp'
            return 'bmp'
        return 'bmp'

    def vmode_for(self, mat_idx):
        if mat_idx is None:
            return 'bmp'
        return self.mat_vmode.get(mat_idx, 'bmp')

    def material_indices_for_palette(self, palette_ref):
        """Global material indices for one palette (None where unresolved)."""
        if not palette_ref or palette_ref <= 0:
            return []
        if palette_ref in self._palette_cache:
            return self._palette_cache[palette_ref]
        pal = self.wld.get_fragment_by_ref(palette_ref)
        indices = []
        if isinstance(pal, WldMaterialPalette):
            for mat_ref in pal.material_refs:
                mat = self.wld.get_fragment_by_ref(mat_ref) if mat_ref > 0 else None
                indices.append(self._material_index(mat))
        self._palette_cache[palette_ref] = indices
        return indices

    def _material_index(self, mat):
        if not isinstance(mat, WldMaterialDef):
            return None
        key = mat.frag_index
        if key in self._mat_index:
            return self._mat_index[key]

        rm_low = mat.render_method & 0xFF
        # The render method's low byte decides how it's drawn (gequip's
        # materials): 0x13 = cut-out, 0x0A/0x05/0x0B = see-through,
        # 0x09/0x17/0x19/0x12/0x31 = glows, 0 = invisible boundary.
        kind = 'invisible' if rm_low == 0 else 'cutout' if rm_low == 0x13 else \
            'translucent' if rm_low in (0x05, 0x0A, 0x0B) else \
            'glow' if rm_low in (0x09, 0x12, 0x17, 0x19, 0x31) else 'opaque'

        tex = None
        tex_label = ''
        if kind != 'invisible' and mat.texture_name:
            tex = load_texture_from_archive(self.archive, mat.texture_name,
                                            masked=(kind == 'cutout'))
            if tex is None and mat.layer_name:
                layered = load_layered_texture(self.archive, mat.texture_name, mat.layer_name)
                if layered is not None:
                    tex = layered
            if tex is not None:
                self.tex_list.append(tex)
                tex_label = tex.name

        base_name = mat.name or 'mat_%d' % mat.frag_index
        noe_mat = NoeMaterial(base_name, tex_label)
        r, g, b, a = mat.rgb_pen
        alpha = a / 255.0
        if kind == 'translucent':
            # 0x05/0x0A/0x0B are EQ's see-through methods (50/25/75%). Drawn
            # opaque, every smoke card becomes a solid plane - ael_chr's air
            # elemental turns into a pile of grey sheets. Everquest_Model_
            # Viewer draws this kind alpha-blended at that opacity.
            alpha = 0.25 if rm_low == 0x0A else 0.75 if rm_low == 0x0B else 0.5
        else:
            # EQ leaves the pen alpha at 0 for lit materials; force opaque so
            # nothing depends on the host ignoring alpha without a blend flag.
            alpha = 1.0
        noe_mat.setDiffuseColor(NoeVec4([r / 255.0, g / 255.0, b / 255.0, alpha]))
        mflags = 0
        if mat.flags & 0x01 or kind in ('cutout', 'translucent', 'glow'):
            mflags |= noesis.NMATFLAG_TWOSIDED
        if kind == 'translucent':
            mflags |= getattr(noesis, 'NMATFLAG_BASICBLEND', 0)
        if mflags:
            noe_mat.setFlags(mflags)
        if kind == 'cutout':
            # EQ's cut-out method is a mask in the texture (8-bit BMPs get
            # palette index 0 as alpha, see eq_material). Without an alpha
            # test the masked texels draw as solid quads - Everquest_Model_
            # Viewer renders every cutout material with alphaTest 0.5.
            try:
                noe_mat.setAlphaTest(0.5)
            except AttributeError:
                pass
        idx = len(self.mat_list)
        self.mat_list.append(noe_mat)
        self._mat_index[key] = idx
        self.mat_vmode[idx] = self._texture_vmode(mat.texture_name)
        return idx


# ---------------------------------------------------------------- skeleton
def _axis_mappers(axis):
    if axis == 'zone':
        return wld_zone_pos, wld_zone_nrm, wld_zone_trans, wld_zone_quat
    return wld_nonzone_pos, wld_nonzone_nrm, wld_nonzone_trans, wld_nonzone_quat


def _track_first_frame(wld, track_ref):
    """First frame of the track a dag references: (quat, trans, scale) raw axes."""
    track = wld.get_fragment_by_ref(track_ref) if track_ref > 0 else None
    if not isinstance(track, WldTrack):
        return None
    tdef = wld.get_fragment_by_ref(track.track_def_ref) if track.track_def_ref > 0 else None
    if not isinstance(tdef, WldTrackDef) or not tdef.frame_transforms:
        return None
    return decompress_track_transform(tdef.frame_transforms[0])


def compute_skeleton(wld, skel, axis):
    """Bones for a 0x10 skeleton: NoeBone list (index == dag index), the bone
    name list, parent indices, and world matrices.
    """
    _, _, map_trans, map_quat = _axis_mappers(axis)
    dags = skel.dags
    n = len(dags)
    parents = [-1] * n
    for i, dag in enumerate(dags):
        for child in dag['sub_dags']:
            if 0 <= child < n:
                parents[child] = i

    local_mats = []
    for i, dag in enumerate(dags):
        frame = _track_first_frame(wld, dag['track_ref'])
        if frame is None:
            local_mats.append(mat43_identity())
        else:
            q = map_quat(frame['rotation'])
            t = map_trans(frame['translation'])
            s = frame.get('scale', 1.0)
            local_mats.append(mat43_from_quat_translation_scale(q, t, (s, s, s)))

    world = [None] * n

    def compute(i, parent_world):
        m = mat43_multiply(parent_world, local_mats[i]) if parent_world is not None else local_mats[i]
        world[i] = m
        for child in dags[i]['sub_dags']:
            if 0 <= child < n:
                compute(child, m)

    for i in range(n):
        if parents[i] < 0:
            compute(i, None)
    for i in range(n):
        if world[i] is None:
            world[i] = local_mats[i]

    names = []
    for i, dag in enumerate(dags):
        nm = wld.string_hash.get(-dag['name_ref'], '') if dag['name_ref'] < 0 else ''
        names.append(nm or ('bone_%d' % i))

    bones = []
    for i in range(n):
        bones.append(NoeBone(i, names[i], mat43_to_noemat43(world[i]),
                             names[parents[i]] if parents[i] >= 0 else '',
                             parents[i]))
    return bones, names, parents, world


def _bone_for_vertex_map(pieces, vert_count, fallback_bone):
    bone_of = [-1] * vert_count
    v = 0
    for count, bone in (pieces or []):
        if bone < 0:
            continue
        for _ in range(count):
            if v >= vert_count:
                break
            bone_of[v] = bone
            v += 1
    if fallback_bone is not None:
        for i in range(vert_count):
            if bone_of[i] < 0:
                bone_of[i] = fallback_bone
    return bone_of


def _build_part_meshes(mesh_frag, bone_of, world_mats, bank, axis,
                       mesh_label, mapped_bones=None):
    """NoeMesh list for one mesh part: faces split by material run, WLD
    winding reversed, V negated.

    Skinned WLD vertices are stored in bone space; they are pre-posed by the
    bone's bind world matrix so the mesh geometry lands in model space (the
    convention Noesis skins with - it applies posed * bindInv itself), and
    per-vertex weights keep the mesh rigged for animations.
    """
    map_pos, map_nrm, _, _ = _axis_mappers(axis)
    verts = mesh_frag.vertices
    uvs = mesh_frag.uvs
    nrms = mesh_frag.normals
    faces = [f['indices'] for f in mesh_frag.faces]
    nvert = len(verts)

    posed = bone_of is not None and world_mats is not None and \
        any(b >= 0 for b in bone_of)
    if posed:
        pos_list = []
        nrm_list = []
        for vi in range(nvert):
            b = bone_of[vi]
            v = verts[vi]
            nv = nrms[vi] if vi < len(nrms) else (0.0, 0.0, 1.0)
            if b >= 0 and b < len(world_mats):
                m = world_mats[b]
                x = v[0] * m[0] + v[1] * m[1] + v[2] * m[2] + m[3]
                y = v[0] * m[4] + v[1] * m[5] + v[2] * m[6] + m[7]
                z = v[0] * m[8] + v[1] * m[9] + v[2] * m[10] + m[11]
                nx = nv[0] * m[0] + nv[1] * m[1] + nv[2] * m[2]
                ny = nv[0] * m[4] + nv[1] * m[5] + nv[2] * m[6]
                nz = nv[0] * m[8] + nv[1] * m[9] + nv[2] * m[10]
                ln = (nx * nx + ny * ny + nz * nz) ** 0.5
                if ln > 1e-9:
                    nx, ny, nz = nx / ln, ny / ln, nz / ln
                v = (x, y, z)
                nv = (nx, ny, nz)
            pos_list.append(NoeVec3(map_pos(v)))
            nrm_list.append(NoeVec3(map_nrm(nv)))
    else:
        pos_list = [NoeVec3(map_pos(v)) for v in verts]
        nrm_list = [NoeVec3(map_nrm(nrms[vi] if vi < len(nrms) else (0.0, 0.0, 1.0)))
                    for vi in range(nvert)]

    # Which way V has to go depends on how the texture was decoded, not on the
    # content type: BMP rows are kept in file order (a BMP stores bottom-up) so
    # they need the negated V, while DDS rows are top-down and need 1-V. Luclin
    # era .s3d bodies are DDS pages - using the BMP rule there turned every head
    # on those models upside down.
    uv_list = [NoeVec3((uvs[vi][0], -uvs[vi][1], 0.0)) if vi < len(uvs) else NoeVec3((0.0, 0.0, 0.0))
               for vi in range(nvert)]
    # DDS rows are already top-down, which is what Noesis samples from V=0, so
    # those pages keep the stored V unchanged (same as Everquest_Model_Viewer,
    # which feeds raw UVs to a flipY=false texture).
    uv_list_dds = [NoeVec3((uvs[vi][0], uvs[vi][1], 0.0)) if vi < len(uvs) else NoeVec3((0.0, 0.0, 0.0))
                   for vi in range(nvert)]

    runs = mesh_frag.face_material_groups or [(len(faces), 0)]
    pal_indices = bank.material_indices_for_palette(getattr(mesh_frag, 'material_palette_ref', -1))

    out = []
    face_i = 0
    run_i = 0
    for count, pal_idx in runs:
        if pal_idx < 0:
            pal_idx = 0
        mat_idx = None
        if pal_idx < len(pal_indices):
            mat_idx = pal_indices[pal_idx]
        if mat_idx is None:
            mat_idx = 0 if bank.mat_list else None
        run_uv = uv_list_dds if bank.vmode_for(mat_idx) == 'dds' else uv_list
        tris = []
        used = {}
        local_to_src = []
        sub_pos = []
        sub_uv = []
        sub_nrm = []
        for _ in range(count):
            if face_i >= len(faces):
                break
            i0, i1, i2 = faces[face_i]
            face_i += 1
            # WLD winds the other way round (Everquest_Model_Viewer wldModel)
            src = (i0, i2, i1)
            if not all(0 <= vi < nvert for vi in src):
                continue
            for vi in src:
                if vi not in used:
                    used[vi] = len(sub_pos)
                    local_to_src.append(vi)
                    sub_pos.append(pos_list[vi])
                    sub_uv.append(run_uv[vi])
                    sub_nrm.append(nrm_list[vi])
            tris.extend([used[src[0]], used[src[1]], used[src[2]]])
        if not tris:
            continue
        mat_name = bank.mat_list[mat_idx].name if (mat_idx is not None and mat_idx < len(bank.mat_list)) else ''
        # per-run suffix keeps mesh names unique within the model
        noe_mesh = NoeMesh(tris, sub_pos, '%s_r%d' % (mesh_label, run_i), mat_name)
        noe_mesh.setUVs(sub_uv)
        noe_mesh.setNormals(sub_nrm)
        if bone_of is not None and mapped_bones is not None:
            weights = []
            for src_vi in local_to_src:
                b = bone_of[src_vi] if src_vi < len(bone_of) else -1
                mb = mapped_bones[b] if (0 <= b < len(mapped_bones)) else -1
                weights.append(NoeVertWeight([mb if mb >= 0 else 0], [1.0]))
            noe_mesh.setWeights(weights)
        out.append(noe_mesh)
        run_i += 1
    return out


def _cloud_placeholder(wld, cloud_frag, bone_world, axis):
    """Small marker mesh for a 0x34 particle cloud hung on a bone."""
    try:
        from eqlib.eq_particle import build_particle_placeholder_geometry
        _, _, map_trans, _ = _axis_mappers(axis)
        pos = map_trans(mat43_get_translation(bone_world))
        mesh = build_particle_placeholder_geometry(cloud_frag, pos)
        return mesh
    except Exception:
        return None


def _resolve_skeleton(wld, ref):
    """A skeleton: a 0x10 directly, or a 0x11 instance -> its 0x10."""
    if not ref or ref <= 0:
        return None
    frag = wld.get_fragment_by_ref(ref)
    if isinstance(frag, WldHierarchicalSpriteDef):
        return frag
    if isinstance(frag, WldHierarchicalSprite):
        sk = wld.get_fragment_by_ref(frag.skeleton_ref)
        if isinstance(sk, WldHierarchicalSpriteDef):
            return sk
        sk = wld.get_fragment_by_ref(frag.skeleton_ref_alt)
        if isinstance(sk, WldHierarchicalSpriteDef):
            return sk
    return None


# ---------------------------------------------------------------- actors
def _actor_refs(wld, actor):
    refs = []
    for ref in actor.references:
        frag = wld.get_fragment_by_ref(ref) if ref > 0 else None
        if isinstance(frag, (WldDmSprite, WldHierarchicalSprite, WldHierarchicalSpriteDef)):
            refs.append(ref)
    if not refs:
        # Unexpected layout: scan the body for references
        # (Everquest_Model_Viewer wldActorParts fallback).
        data = getattr(actor, 'raw_data', b'')
        for off in range(4, max(0, len(data) - 3), 4):
            ref = struct.unpack_from('<i', data, off)[0]
            frag = wld.get_fragment_by_ref(ref) if ref > 0 else None
            if isinstance(frag, (WldDmSprite, WldHierarchicalSprite, WldHierarchicalSpriteDef)):
                refs.append(ref)
    seen = set()
    unique = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _actor_name(wld, actor):
    nm = actor.name or ''
    if nm.lower().endswith('_actordef'):
        nm = nm[:-len('_actordef')]
    return nm or ('actor_%d' % actor.frag_index)


def build_actor_models(wld, archive, axis='nonzone', with_anims=False):
    """One Noesis model per actor; [] when the WLD has no usable actors."""
    bank = WldMaterialBank(wld, archive)
    models = []

    for actor in wld.get_fragments_of_type(FRAG_ACTOR_DEF):
        refs = _actor_refs(wld, actor)
        if not refs:
            continue

        # resolve every ref, picking the largest skeleton as the primary bone set
        skeletons = []
        for r in refs:
            sk = _resolve_skeleton(wld, r)
            if sk is not None:
                skeletons.append(sk)
        primary = None
        bones, bone_names, world_mats = [], [], None
        if skeletons:
            primary = max(skeletons, key=lambda s: len(s.dags))
            bones, bone_names, _, world_mats = compute_skeleton(wld, primary, axis)

        all_meshes = []
        used_mat_indices = set()
        name_mesh = _unique_mesh_namer()
        for ref in refs:
            raw_frag = wld.get_fragment_by_ref(ref)
            skel = _resolve_skeleton(wld, ref)
            if skel is not None:
                frag = skel
                mapped_bones = None
                sk_world = world_mats
                if frag is not primary:
                    # map this skeleton's bones into the primary by name
                    _, names2, _, world2 = compute_skeleton(wld, frag, axis)
                    name_to_idx = {}
                    for bi, bn in enumerate(bone_names):
                        name_to_idx[bn.upper()] = bi
                    mapped_bones = [name_to_idx.get(bn.upper(), -1) for bn in names2]
                    sk_world = world2
                elif bones:
                    mapped_bones = list(range(len(bones)))

                # meshes hung on bones (per-dag mesh refs and the 0x200 skin list)
                for dag_i, dag in enumerate(frag.dags):
                    mesh = resolve_mesh_frag(wld, dag['mesh_ref'])
                    if mesh is not None:
                        bone_of = _bone_for_vertex_map(mesh.skin_assignment_groups,
                                                       len(mesh.vertices), dag_i)
                        label = name_mesh(mesh.name or 'part_%d' % mesh.frag_index)
                        built = _build_part_meshes(
                            mesh, bone_of, sk_world, bank, axis, label,
                            mapped_bones=mapped_bones)
                        all_meshes.extend(built)
                    else:
                        cloud = wld.get_fragment_by_ref(dag['mesh_ref']) if dag['mesh_ref'] > 0 else None
                        if isinstance(cloud, WldParticleCloudDef) and sk_world is not None:
                            pm = _cloud_placeholder(wld, cloud, sk_world[dag_i], axis)
                            if pm is not None:
                                all_meshes.append(pm)
                if frag.flags & 0x200:
                    for dm in frag.dm_sprites:
                        mesh = resolve_mesh_frag(wld, dm)
                        if mesh is None:
                            continue
                        bone_of = _bone_for_vertex_map(mesh.skin_assignment_groups,
                                                       len(mesh.vertices), None)
                        label = name_mesh(mesh.name or 'part_%d' % mesh.frag_index)
                        built = _build_part_meshes(
                            mesh, bone_of, sk_world, bank, axis, label,
                            mapped_bones=mapped_bones)
                        all_meshes.extend(built)

            elif isinstance(raw_frag, WldDmSprite):
                mesh = resolve_mesh_frag(wld, ref)
                if mesh is None:
                    continue
                label = name_mesh(mesh.name or 'part_%d' % mesh.frag_index)
                built = _build_part_meshes(mesh, None, None, bank, axis, label)
                all_meshes.extend(built)

        if not all_meshes:
            continue

        # per-model material/texture subset: NoeMesh references materials by
        # name, so a slice of the bank lists still resolves.
        for me in all_meshes:
            for i, m in enumerate(bank.mat_list):
                if m.name == me.matName:
                    used_mat_indices.add(i)
                    break
        mats_subset = [bank.mat_list[i] for i in sorted(used_mat_indices)]
        if not mats_subset and bank.mat_list:
            mats_subset = [bank.mat_list[0]]
        used_tex_names = set(m.texName for m in mats_subset if getattr(m, 'texName', ''))
        tex_subset = [t for t in bank.tex_list if t.name in used_tex_names]

        anims = []
        if with_anims and bones:
            anims = build_wld_anims(wld, bones, axis)
        if bones:
            tpose = build_bind_pose_anim(bones)
            if tpose is not None:
                anims.append(tpose)

        mdl = NoeModel(all_meshes, bones, anims, NoeModelMaterials(tex_subset, mats_subset))
        try:
            mdl.name = _actor_name(wld, actor)
        except Exception:
            pass
        models.append(mdl)
    return models


def build_all_meshes_model(wld, archive, axis='zone', label=None):
    """Zones without actors: every 0x36/0x2C mesh as one static model."""
    bank = WldMaterialBank(wld, archive)
    name_mesh = _unique_mesh_namer()
    all_meshes = []
    for frag in wld.fragments:
        if not isinstance(frag, (WldDmSpriteDef2, WldDmSpriteDef)):
            continue
        if not frag.vertices or not frag.faces:
            continue
        label_i = name_mesh(frag.name or ('mesh_%d' % frag.frag_index))
        try:
            all_meshes.extend(_build_part_meshes(
                frag, None, None, bank, axis, label_i))
        except Exception as e:
            print("[EQ WLD] mesh build error %s: %s" % (label_i, str(e)))
    if not all_meshes:
        return None
    mats = NoeModelMaterials(bank.tex_list, bank.mat_list)
    mdl = NoeModel(all_meshes, [], [], mats)
    if label:
        try:
            mdl.name = label
        except Exception:
            pass
    return mdl


# ---------------------------------------------------------------- anims
_TRACK_RE = re.compile(r'^[A-Z]\d\d')


def build_wld_anims(wld, bones, axis='nonzone'):
    return build_wld_anims_multi([wld], bones, axis)


def _sample_index(times, t):
    """Index of the key at or before t, and the blend fraction to the next."""
    n = len(times)
    if n == 0:
        return 0, 0.0
    if t <= times[0]:
        return 0, 0.0
    if t >= times[-1]:
        return n - 1, 0.0
    lo, hi = 0, n - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    span = times[hi] - times[lo]
    if span <= 1e-9:
        return lo, 0.0
    return lo, (t - times[lo]) / span


def _resample_q(times, quats, frame_times):
    out = []
    for t in frame_times:
        i, f = _sample_index(times, t)
        a = quats[i]
        b = quats[i + 1] if i + 1 < len(quats) else a
        if f <= 0.0:
            out.append(a)
            continue
        d = a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]
        if d < 0.0:
            b = (-b[0], -b[1], -b[2], -b[3])
        q = (a[0] + (b[0] - a[0]) * f,
             a[1] + (b[1] - a[1]) * f,
             a[2] + (b[2] - a[2]) * f,
             a[3] + (b[3] - a[3]) * f)
        ln = (q[0]*q[0] + q[1]*q[1] + q[2]*q[2] + q[3]*q[3]) ** 0.5
        out.append((q[0]/ln, q[1]/ln, q[2]/ln, q[3]/ln) if ln > 1e-9 else a)
    return out


def _resample_v(times, vecs, frame_times):
    out = []
    for t in frame_times:
        i, f = _sample_index(times, t)
        a = vecs[i]
        b = vecs[i + 1] if i + 1 < len(vecs) else a
        if f <= 0.0:
            out.append(a)
            continue
        out.append((a[0] + (b[0] - a[0]) * f,
                    a[1] + (b[1] - a[1]) * f,
                    a[2] + (b[2] - a[2]) * f))
    return out


def _resample_s(times, vals, frame_times):
    out = []
    for t in frame_times:
        i, f = _sample_index(times, t)
        a = vals[i]
        b = vals[i + 1] if i + 1 < len(vals) else a
        out.append(a if f <= 0.0 else a + (b - a) * f)
    return out


def build_wld_anims_multi(wlds, bones, axis='nonzone'):
    """Noesis keyframed animations from 0x12/0x13 track fragments across one
    or more WLDs (a body archive's rest poses plus companion animation
    archives such as <race>_chr2.s3d and global3_chr.s3d).

    Track names look like P01HUMR_POINT_TRACK: the first three characters are
    the animation key, the rest the race-prefixed bone name matching the dag
    (<RACE><BONE>_DAG). Frame times come from the track's sleep field.
    """
    _, _, map_trans, map_quat = _axis_mappers(axis)
    bone_by_suffix = {}
    for b in bones:
        nm = b.name.upper()
        bone_by_suffix[nm] = b.index
        if nm.endswith('_DAG'):
            bone_by_suffix[nm[:-len('_DAG')]] = b.index

    anim_tracks = {}
    seen_track_names = set()
    for wld in wlds:
        if wld is None:
            continue
        for track in wld.get_fragments_of_type(FRAG_TRACK):
            if not isinstance(track, WldTrack):
                continue
            name = (track.name or '').upper()
            if not name.endswith('_TRACK') or not _TRACK_RE.match(name):
                continue
            if name in seen_track_names:
                continue
            seen_track_names.add(name)
            anim_name = name[:3]
            rest = name[3:-len('_TRACK')]
            # Track names are <ANIM><RACE><BONE>, sometimes with a variant
            # character between the anim code and the race
            # (L08A + HUF + PEPELVIS); the variant joins the anim key.
            matches = []
            if rest in bone_by_suffix:
                matches.append((bone_by_suffix[rest], anim_name))
            elif len(rest) > 1 and rest[1:] in bone_by_suffix:
                matches.append((bone_by_suffix[rest[1:]], anim_name + rest[0]))
            elif rest:
                # suffix match: dag names may carry extra prefixes. Prefer the
                # LONGEST candidate (most specific) and iterate in sorted order
                # - iterating the dict directly picked an arbitrary bone, and
                # an empty suffix (the actor-level "AUK_TRACK" / "ZOF_TRACK"
                # fragments) matched every bone at once.
                cands = [k for k in bone_by_suffix.keys() if k.endswith(rest)]
                if cands:
                    cands.sort(key=len, reverse=True)
                    matches.append((bone_by_suffix[cands[0]], anim_name))
            if not matches:
                continue
            bone_idx, anim_name = matches[0]
            tdef = wld.get_fragment_by_ref(track.track_def_ref) if track.track_def_ref > 0 else None
            if not isinstance(tdef, WldTrackDef) or not tdef.frame_transforms:
                continue
            sleep_ms = track.frame_ms if (track.flags & 0x1 and track.frame_ms > 0) else 100
            anim_tracks.setdefault(anim_name, {})[bone_idx] = (tdef, sleep_ms)

    anims = []
    rest_locals = rest_local_matrices(bones)
    for anim_name in sorted(anim_tracks.keys()):
        bone_tracks = anim_tracks[anim_name]
        # Every track in a clip must run on ONE clock. Tracks carry their own
        # frame_ms and they genuinely differ inside a single animation
        # (woe_v2's C05 has 16 tracks at 100 ms and 51 at 66 ms), so feeding
        # each bone its own timestamps while Noesis plays the clip at a single
        # frameRate makes the bones drift apart - that is the jank. Resample
        # every track onto the finest rate present.
        end_t = 0.0
        min_sleep = 1000.0
        for tdef, sleep_ms in bone_tracks.values():
            n = len(tdef.frame_transforms)
            if n > 1:
                end_t = max(end_t, (n - 1) * sleep_ms / 1000.0)
            if sleep_ms <= 0:
                sleep_ms = 100
            min_sleep = min(min_sleep, float(sleep_ms))
        if min_sleep <= 0.0 or min_sleep > 1000.0:
            min_sleep = 100.0
        fps = 1000.0 / min_sleep
        frame_times = []
        n_frames = int(round(end_t * fps)) + 1
        if n_frames < 2:
            n_frames = 2
        for fi in range(n_frames):
            frame_times.append(fi / fps)

        kf_bones = []
        for b in bones:
            kf = NoeKeyFramedBone(b.index)
            entry = bone_tracks.get(b.index)
            if entry is not None:
                tdef, sleep_ms = entry
                if sleep_ms <= 0:
                    sleep_ms = 100
                times = []
                rots = []
                trans = []
                scales = []
                for fi, ft in enumerate(tdef.frame_transforms):
                    xform = decompress_track_transform(ft)
                    times.append(fi * sleep_ms / 1000.0)
                    rots.append(map_quat(xform['rotation']))
                    trans.append(map_trans(xform['translation']))
                    scales.append(xform.get('scale', 1.0))
                if rots:
                    rs = _resample_q(times, rots, frame_times)
                    kf.setRotation([NoeKeyFramedValue(frame_times[i], NoeQuat(rs[i]))
                                    for i in range(n_frames)],
                                   type=noesis.NOEKF_ROTATION_QUATERNION_4)
                # Track frames carry the FULL local translation and scale -
                # always set them, since an unset component may otherwise
                # evaluate as zero/identity and collapse the skeleton during
                # playback.
                ts = _resample_v(times, trans, frame_times)
                kf.setTranslation([NoeKeyFramedValue(frame_times[i], NoeVec3(ts[i]))
                                   for i in range(n_frames)],
                                  type=noesis.NOEKF_TRANSLATION_VECTOR_3)
                # NOEKF_SCALE_SCALAR_1 keys carry a plain float, not a
                # vector; skip insane values rather than explode playback.
                if all(0.001 <= s <= 16.0 for s in scales):
                    ss = _resample_s(times, scales, frame_times)
                    kf.setScale([NoeKeyFramedValue(frame_times[i], ss[i])
                                 for i in range(n_frames)],
                                type=noesis.NOEKF_SCALE_SCALAR_1)
            else:
                # Bone with no track in this animation: pin it to its rest
                # LOCAL. Noesis otherwise poses an unkeyed bone at its bind
                # WORLD matrix and the bone (plus its vertices) flies away.
                q, tr, sc = mat43_decompose(rest_locals[b.index])
                kt = (0.0, end_t)
                kf.setRotation([NoeKeyFramedValue(t, NoeQuat(q)) for t in kt],
                               type=noesis.NOEKF_ROTATION_QUATERNION_4)
                kf.setTranslation([NoeKeyFramedValue(t, NoeVec3(tr)) for t in kt],
                                  type=noesis.NOEKF_TRANSLATION_VECTOR_3)
                if abs(sc[0] - sc[1]) < 1e-4 and abs(sc[1] - sc[2]) < 1e-4:
                    kf.setScale([NoeKeyFramedValue(t, sc[0]) for t in kt],
                                type=noesis.NOEKF_SCALE_SCALAR_1)
                else:
                    kf.setScale([NoeKeyFramedValue(t, NoeVec3(sc)) for t in kt],
                                type=noesis.NOEKF_SCALE_VECTOR_3)
            kf_bones.append(kf)
        anims.append(NoeKeyFramedAnim(anim_name, bones, kf_bones, fps))
    return anims


def build_bind_pose_anim(bones, name="T-Pose"):
    """A one-clip bind pose, so Noesis offers the rest pose as an animation.

    EQ's clips never include a T-pose, and Noesis concatenates every clip onto
    one timeline, so without this there is no way to look at the model as it
    was authored. Two keys (start/end) at each bone's rest LOCAL.
    """
    if not bones:
        return None
    try:
        rest = rest_local_matrices(bones)
        kf_bones = []
        for i in range(len(bones)):
            q, tr, sc = mat43_decompose(rest[i])
            kf = NoeKeyFramedBone(i)
            kt = (0.0, 0.033)
            kf.setRotation([NoeKeyFramedValue(t, NoeQuat(q)) for t in kt],
                           type=noesis.NOEKF_ROTATION_QUATERNION_4)
            kf.setTranslation([NoeKeyFramedValue(t, NoeVec3(tr)) for t in kt],
                              type=noesis.NOEKF_TRANSLATION_VECTOR_3)
            if abs(sc[0] - sc[1]) < 1e-4 and abs(sc[1] - sc[2]) < 1e-4:
                kf.setScale([NoeKeyFramedValue(t, sc[0]) for t in kt],
                            type=noesis.NOEKF_SCALE_SCALAR_1)
            else:
                kf.setScale([NoeKeyFramedValue(t, NoeVec3(sc)) for t in kt],
                            type=noesis.NOEKF_SCALE_VECTOR_3)
            kf_bones.append(kf)
        return NoeKeyFramedAnim(name, bones, kf_bones, 30.0)
    except Exception:
        return None


def _unique_mesh_namer():
    """Mesh names must be unique per model; Noesis renames (with a warning)
    when they collide."""
    used = {}

    def claim(name):
        base = name or 'mesh'
        n = used.get(base, 0)
        used[base] = n + 1
        return base if n == 0 else '%s_%d' % (base, n + 1)

    return claim
