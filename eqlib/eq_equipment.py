from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_wld import WldFile, WldParticleCloudDef
from eqlib.eq_const import *
from eqlib.eq_character import _load_eqg_models
from eqlib.eq_particle import build_particle_placeholder_geometry


def load_equipment(archive, mdl_list):
    has_wld = archive.has_file_containing('.wld')

    if has_wld:
        return _load_equipment_wld(archive, mdl_list)

    return _load_eqg_equip(archive, mdl_list)


def _load_eqg_equip(archive, mdl_list):
    # .mod/.mds items share the character builder: each standalone skinned
    # item becomes its own model with bones, weights and its .ani animations.
    return _load_eqg_models(archive, mdl_list)


def _load_equipment_wld(archive, mdl_list):
    # actor-driven build (same as characters), then particle cloud markers
    from eqlib.eq_character import _load_character_wld
    result = _load_character_wld(archive, mdl_list)

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
            try:
                mesh = build_particle_placeholder_geometry(p)
                if mdl_list:
                    mdl_list[0].addMesh(mesh)
            except Exception:
                pass

    return result
