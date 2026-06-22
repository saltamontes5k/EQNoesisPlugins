from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile
from eqlib.eq_wld import WldParticleCloudDef
from eqlib.eq_const import *
from eqlib.eq_character import (
    _build_simple_materials, _build_eqg_geom, _build_eqg_mds_geom,
)
from eqlib.eq_mod import EqgModFile, EqgMdsFile
from eqlib.eq_particle import build_particle_placeholder_geometry, parse_pts, parse_prt, parse_eff
from eqlib.eq_mat43 import eqg_to_yup_pos


def load_equipment(archive, mdl_list):
    has_wld = archive.has_file_containing('.wld')

    if has_wld:
        return _load_equipment_wld(archive, mdl_list)

    return _load_eqg_equip(archive, mdl_list)


def _load_eqg_equip(archive, mdl_list):
    mod_files = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mod')]
    mds_files = [fn for fn in archive.get_file_names() if fn.lower().endswith('.mds')]

    all_meshes = []
    tex_list = []
    mat_list = []

    for fn in mod_files:
        data = archive.get_file(fn)
        if not data:
            continue
        try:
            mod = EqgModFile(data)
            _build_eqg_geom(mod, archive, all_meshes, tex_list, mat_list)
        except Exception as e:
            print("[EQ Equip] MOD error %s: %s" % (fn, str(e)))

    for fn in mds_files:
        data = archive.get_file(fn)
        if not data:
            continue
        try:
            mds = EqgMdsFile(data)
            _build_eqg_mds_geom(mds, archive, all_meshes, tex_list, mat_list)
        except Exception as e:
            print("[EQ Equip] MDS error %s: %s" % (fn, str(e)))

    for fn in archive.get_file_names():
        lower = fn.lower()
        if lower.endswith('.pts'):
            pts_data = archive.get_file(fn)
            if pts_data:
                try:
                    pts_points = parse_pts(pts_data)
                    for pt in pts_points:
                        p = build_particle_placeholder_geometry(
                            type('Dummy', (), {
                                'spawn_type': 3, 'gravity': 0.0,
                                'spawn_radius': 0.3, 'spawn_normal': pt['translation'],
                                'tint': (255, 128, 0, 255), 'lifespan': 1000,
                                'spawn_rate': 1, 'spawn_velocity': pt['translation'],
                            })(),
                            eqg_to_yup_pos(pt['translation']),
                        )
                        all_meshes.append(p)
                except Exception:
                    pass

    if not all_meshes:
        return 0

    mdl = NoeModel(all_meshes, [], [], NoeModelMaterials(tex_list, mat_list))
    mdl_list.append(mdl)
    return 1


def _load_equipment_wld(archive, mdl_list):
    from eqlib.eq_character import load_character

    result = load_character(archive, mdl_list)

    wld_data = None
    for fn in archive.get_file_names():
        if fn.lower().endswith('.wld'):
            wld_data = archive.get_file(fn)
            break
    if wld_data is None:
        return result

    wld = WldFile(wld_data)
    particles = wld.get_fragments_of_type(FRAG_PARTICLE_CLOUD_DEF)

    for p in particles:
        if isinstance(p, WldParticleCloudDef):
            mesh = build_particle_placeholder_geometry(p)
            if mdl_list:
                mdl_list[0].addMesh(mesh)

    return result
