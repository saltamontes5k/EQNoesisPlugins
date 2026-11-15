from inc_noesis import *
import noesis
import rapi

from eqlib.eq_pfs import PfsArchive
from eqlib.eq_const import *


def registerNoesisTypes():
    handle = noesis.register("EverQuest S3D/EQG", ".s3d")
    noesis.setHandlerTypeCheck(handle, eqCheckType)
    noesis.setHandlerLoadModel(handle, eqLoadModel)

    handle2 = noesis.register("EverQuest S3D/EQG", ".eqg")
    noesis.setHandlerTypeCheck(handle2, eqCheckType)
    noesis.setHandlerLoadModel(handle2, eqLoadModel)

    # No noesis.logPopup() here: it pops a modal Debug Log window on every
    # startup. Debugging trick that does work in the host: temporarily add
    # logPopup() above and redirect sys.stdout to a file at the top of
    # eqLoadModel - Noesis swallows printed output otherwise.
    print("[EQ] Plugin registered OK")
    return 1


def eqCheckType(data):
    try:
        if len(data) < 12:
            return 0
        bs = NoeBitStream(data)
        bs.readInt()
        magic = bs.readUInt()
        version = bs.readInt()
        if magic == 0x20534650 and (version == 0x00010000 or version == 0x00020000):
            return 1
    except:
        pass
    return 0


_CONTENT_ZONE = 0
_CONTENT_CHARACTER = 1
_CONTENT_EQUIPMENT = 2
_CONTENT_UNKNOWN = 3


def _detect_content_type(archive):
    file_names = [f.lower() for f in archive.get_file_names()]

    has_chr_name = any('_chr' in fn for fn in file_names) or any('chr2' in fn for fn in file_names)
    has_obj_name = any('_obj' in fn for fn in file_names)
    has_mod = any(fn.endswith('.mod') for fn in file_names)
    has_mds = any(fn.endswith('.mds') for fn in file_names)
    has_ani = any(fn.endswith('.ani') for fn in file_names)
    has_wld = any(fn.endswith('.wld') for fn in file_names)
    has_pts = any(fn.endswith('.pts') for fn in file_names)
    has_prt = any(fn.endswith('.prt') for fn in file_names)
    has_eff = any(fn.endswith('.eff') for fn in file_names)
    has_zon = any(fn.endswith('.zon') for fn in file_names)
    has_lay = any(fn.endswith('.lay') for fn in file_names)
    has_ter = any(fn.endswith('.ter') for fn in file_names)

    # A modern zone archive has no .wld at all: the ground is a .ter and the
    # props are .mod files placed by a .zon. Check this before the .mod rules
    # below, or such archives land in the character/equipment paths.
    if has_ter or (has_zon and has_mod):
        return _CONTENT_ZONE

    if has_mod or has_mds:
        if has_ani or has_zon or has_lay:
            return _CONTENT_CHARACTER
        for fn in file_names:
            bn = fn.rsplit('.', 1)[0].lower()
            if bn.startswith('it') and len(bn) >= 4:
                return _CONTENT_EQUIPMENT
        if has_chr_name:
            return _CONTENT_CHARACTER
        return _CONTENT_EQUIPMENT

    if has_chr_name and not has_obj_name:
        return _CONTENT_CHARACTER

    if has_wld:
        if has_obj_name:
            return _CONTENT_ZONE
        if not has_chr_name:
            return _CONTENT_ZONE

    if has_zon or has_ter:
        return _CONTENT_ZONE

    # Geometry-free archives (armor .lay + textures, .pts/.prt/.eff effects)
    # have nothing to build. Route them through the character/equipment loader
    # so it can say what they are; the zone loader would just return 0 silently.
    if not has_wld and not has_mod and not has_mds and (has_lay or has_pts or has_prt or has_eff):
        return _CONTENT_CHARACTER

    return _CONTENT_ZONE


def eqLoadModel(data, mdlList):
    print("[EQ] LoadModel called, data size=%d" % len(data))

    try:
        archive = PfsArchive.from_bytes(data)
        print("[EQ] Archive has %d files" % len(archive.files))
    except Exception as e:
        print("[EQ] Archive parse failed: %s" % str(e))
        import traceback
        traceback.print_exc()
        return 0

    content_type = _detect_content_type(archive)
    type_names = {0:"ZONE", 1:"CHARACTER", 2:"EQUIPMENT"}
    print("[EQ] Content type: %s" % type_names.get(content_type, "?"))

    try:
        if content_type == _CONTENT_ZONE:
            print("[EQ] Calling zone loader...")
            from eqlib.eq_zone import load_zone
            r = load_zone(archive, mdlList)
            print("[EQ] Zone result=%d, models=%d" % (r, len(mdlList)))
            return r
        elif content_type == _CONTENT_CHARACTER:
            print("[EQ] Calling character loader...")
            from eqlib.eq_character import load_character
            r = load_character(archive, mdlList)
            print("[EQ] Character result=%d, models=%d" % (r, len(mdlList)))
            return r
        else:
            print("[EQ] Calling equipment loader...")
            from eqlib.eq_equipment import load_equipment
            r = load_equipment(archive, mdlList)
            print("[EQ] Equipment result=%d, models=%d" % (r, len(mdlList)))
            return r
    except Exception as e:
        print("[EQ] Load failed: %s" % str(e))
        import traceback
        traceback.print_exc()
        return 0
