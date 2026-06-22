from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile, BinReader
from eqlib.eq_wld import (
    WldDmSpriteDef2, WldMaterialDef, WldMaterialPalette,
    WldSimpleSpriteDef, WldBMInfo,
)
from eqlib.eq_const import *
from eqlib.eq_material import load_texture_from_archive
from eqlib.eq_mat43 import wld_zone_pos, wld_zone_nrm


def load_zone(archive, mdl_list):
    wld_data = None
    for fn in archive.get_file_names():
        lower = fn.lower()
        if lower.endswith('.wld') and '_obj' not in lower and 'objects' not in lower and 'lights' not in lower:
            wld_data = archive.get_file(fn)
            break
    if wld_data is None:
        for fn in archive.get_file_names():
            if fn.lower().endswith('.wld'):
                wld_data = archive.get_file(fn)
                break
    if wld_data is None:
        return 0

    wld = WldFile(wld_data)
    textures = wld.resolve_material_textures()

    palettes = wld.get_fragments_of_type(FRAG_MATERIAL_PALETTE)
    meshes = wld.get_fragments_of_type(FRAG_DM_SPRITE_DEF2)

    mat_by_palette_index = {}
    for pal in palettes:
        if isinstance(pal, WldMaterialPalette):
            for i, mat_ref in enumerate(pal.material_refs):
                mat = wld.get_fragment_by_ref(mat_ref)
                if isinstance(mat, WldMaterialDef):
                    mat_by_palette_index[i] = mat

    tex_list = []
    mat_list = []
    mat_list_by_pal_idx = {}

    for mat_idx in sorted(mat_by_palette_index.keys()):
        mat = mat_by_palette_index[mat_idx]
        tex_name = mat.texture_name or textures.get(mat.frag_index + 1, '')
        mat_name = 'mat_%d' % mat_idx

        tex = None
        if tex_name:
            tex = load_texture_from_archive(archive, tex_name)
        if tex:
            tex_list.append(tex)

        if tex:
            noe_mat = NoeMaterial(mat_name, tex_name)
        else:
            noe_mat = NoeMaterial(mat_name, '')
        noe_mat.setDiffuseColor(NoeVec4([mat.rgb_pen[0]/255.0, mat.rgb_pen[1]/255.0, mat.rgb_pen[2]/255.0, 1.0]))
        if mat.flags & 0x01:
            noe_mat.setFlags(noesis.NMATFLAG_TWOSIDED)
        mat_list_by_pal_idx[mat_idx] = len(mat_list)
        mat_list.append(noe_mat)

    all_meshes = []
    for mesh in meshes:
        if not isinstance(mesh, WldDmSpriteDef2):
            continue
        if not mesh.vertices or not mesh.faces:
            continue
        try:
            result = _build_meshes(mesh, mat_list_by_pal_idx)
            if result:
                all_meshes.extend(result)
        except Exception as e:
            print("[EQ Zone] Mesh build error: %s" % str(e))

    if not all_meshes:
        print("[EQ Zone] No meshes loaded")
        return 0

    mdl = NoeModel(all_meshes, [], [], NoeModelMaterials(tex_list, mat_list))
    mdl_list.append(mdl)
    return 1


def _build_meshes(mesh, mat_list_by_pal_idx):
    cx, cy, cz = mesh.center_offset
    pos_list = [NoeVec3(wld_zone_pos((v[0] + cx, v[1] + cy, v[2] + cz))) for v in mesh.vertices]
    uv_list = [NoeVec3((uv[0], -uv[1], 0.0)) for uv in mesh.uvs]
    nrm_list = [NoeVec3(wld_zone_nrm(n)) for n in mesh.normals]
    if not pos_list:
        return None

    max_len = max(len(pos_list), len(uv_list), len(nrm_list))
    while len(pos_list) < max_len:
        pos_list.append(NoeVec3((0.0, 0.0, 0.0)))
    while len(uv_list) < max_len:
        uv_list.append(NoeVec3((0.0, 0.0, 0.0)))
    while len(nrm_list) < max_len:
        nrm_list.append(NoeVec3((0.0, 0.0, 1.0)))

    min_len = min(len(pos_list), len(uv_list), len(nrm_list))
    pos_list = pos_list[:min_len]
    uv_list = uv_list[:min_len]
    nrm_list = nrm_list[:min_len]

    if not mesh.face_material_groups:
        tri_list = []
        for face in mesh.faces:
            i0, i1, i2 = face['indices']
            if i0 < min_len and i1 < min_len and i2 < min_len:
                tri_list.extend([i0, i1, i2])
        if not tri_list:
            return None
        mat_name = 'mat_0'
        noe_mesh = NoeMesh(tri_list, pos_list, mesh.name or 'zone_geo', mat_name)
        noe_mesh.setUVs(uv_list)
        noe_mesh.setNormals(nrm_list)
        return [noe_mesh]

    split_meshes = []
    face_idx = 0
    for poly_count, pal_idx in mesh.face_material_groups:
        if poly_count == 0:
            continue
        sub_tris = []
        sub_verts = []
        sub_uvs = []
        sub_nrms = []
        vert_map = {}
        for _ in range(poly_count):
            if face_idx >= len(mesh.faces):
                break
            f = mesh.faces[face_idx]
            i0, i1, i2 = f['indices']
            for vi in (i0, i1, i2):
                if vi not in vert_map:
                    new_idx = len(sub_verts)
                    vert_map[vi] = new_idx
                    sub_verts.append(pos_list[vi] if vi < len(pos_list) else NoeVec3((0, 0, 0)))
                    sub_uvs.append(uv_list[vi] if vi < len(uv_list) else NoeVec3((0, 0, 0)))
                    sub_nrms.append(nrm_list[vi] if vi < len(nrm_list) else NoeVec3((0, 0, 1)))
            sub_tris.append(vert_map[i0])
            sub_tris.append(vert_map[i1])
            sub_tris.append(vert_map[i2])
            face_idx += 1

        if sub_tris:
            mat_idx = mat_list_by_pal_idx.get(pal_idx, 0)
            mat_name = 'mat_%d' % mat_idx
            noe_mesh = NoeMesh(sub_tris, sub_verts, mesh.name or 'zone_geo', mat_name)
            noe_mesh.setUVs(sub_uvs)
            noe_mesh.setNormals(sub_nrms)
            split_meshes.append(noe_mesh)

    return split_meshes if split_meshes else None
