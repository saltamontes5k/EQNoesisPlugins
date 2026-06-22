# EverQuest WLD fragment type codes
# Source: EQLanternproj quail/raw/rawfrag/rawfrag.go

FRAG_DEFAULT                = 0x00
FRAG_DEFAULT_PALETTE_FILE   = 0x01
FRAG_USER_DATA              = 0x02
FRAG_BM_INFO                = 0x03
FRAG_SIMPLE_SPRITE_DEF      = 0x04
FRAG_SIMPLE_SPRITE          = 0x05
FRAG_SPRITE_2D_DEF          = 0x06
FRAG_SPRITE_2D              = 0x07
FRAG_SPRITE_3D_DEF          = 0x08
FRAG_SPRITE_3D              = 0x09
FRAG_SPRITE_4D_DEF          = 0x0A
FRAG_SPRITE_4D              = 0x0B
FRAG_PARTICLE_SPRITE_DEF    = 0x0C
FRAG_PARTICLE_SPRITE        = 0x0D
FRAG_COMPOSITE_SPRITE_DEF   = 0x0E
FRAG_COMPOSITE_SPRITE       = 0x0F
FRAG_HIERARCHICAL_SPRITE_DEF = 0x10
FRAG_HIERARCHICAL_SPRITE    = 0x11
FRAG_TRACK_DEF              = 0x12
FRAG_TRACK                  = 0x13
FRAG_ACTOR_DEF              = 0x14
FRAG_ACTOR                  = 0x15
FRAG_SPHERE                 = 0x16
FRAG_POLYHEDRON_DEF         = 0x17
FRAG_POLYHEDRON             = 0x18
FRAG_SPHERE_LIST_DEF        = 0x19
FRAG_SPHERE_LIST            = 0x1A
FRAG_LIGHT_DEF              = 0x1B
FRAG_LIGHT                  = 0x1C
FRAG_POINT_LIGHT_OLD        = 0x1D
FRAG_POINT_LIGHT_OLD_DEF    = 0x1E
FRAG_SOUND_DEF              = 0x1F
FRAG_SOUND                  = 0x20
FRAG_WORLD_TREE             = 0x21
FRAG_REGION                 = 0x22
FRAG_ACTIVE_GEO_REGION      = 0x23
FRAG_SKY_REGION             = 0x24
FRAG_DIRECTIONAL_LIGHT_OLD  = 0x25
FRAG_BLIT_SPRITE_DEF        = 0x26
FRAG_BLIT_SPRITE            = 0x27
FRAG_POINT_LIGHT            = 0x28
FRAG_ZONE                   = 0x29
FRAG_AMBIENT_LIGHT          = 0x2A
FRAG_DIRECTIONAL_LIGHT      = 0x2B
FRAG_DM_SPRITE_DEF          = 0x2C
FRAG_DM_SPRITE              = 0x2D
FRAG_DM_TRACK_DEF           = 0x2E
FRAG_DM_TRACK               = 0x2F
FRAG_MATERIAL_DEF           = 0x30
FRAG_MATERIAL_PALETTE       = 0x31
FRAG_DM_RGB_TRACK_DEF       = 0x32
FRAG_DM_RGB_TRACK           = 0x33
FRAG_PARTICLE_CLOUD_DEF     = 0x34
FRAG_GLOBAL_AMBIENT_LIGHT   = 0x35
FRAG_DM_SPRITE_DEF2         = 0x36
FRAG_DM_TRACK_DEF2          = 0x37

FRAG_NAMES = {
    0x00: "Default", 0x01: "DefaultPaletteFile", 0x02: "UserData",
    0x03: "BMInfo", 0x04: "SimpleSpriteDef", 0x05: "SimpleSprite",
    0x06: "Sprite2DDef", 0x07: "Sprite2D", 0x08: "Sprite3DDef",
    0x09: "Sprite3D", 0x0A: "Sprite4DDef", 0x0B: "Sprite4D",
    0x0C: "ParticleSpriteDef", 0x0D: "ParticleSprite",
    0x0E: "CompositeSpriteDef", 0x0F: "CompositeSprite",
    0x10: "HierarchicalSpriteDef", 0x11: "HierarchicalSprite",
    0x12: "TrackDef", 0x13: "Track", 0x14: "ActorDef", 0x15: "Actor",
    0x16: "Sphere", 0x17: "PolyhedronDef", 0x18: "Polyhedron",
    0x19: "SphereListDef", 0x1A: "SphereList",
    0x1B: "LightDef", 0x1C: "Light",
    0x1D: "PointLightOld", 0x1E: "PointLightOldDef",
    0x1F: "SoundDef", 0x20: "Sound",
    0x21: "WorldTree", 0x22: "Region", 0x23: "ActiveGeoRegion",
    0x24: "SkyRegion", 0x25: "DirectionalLightOld",
    0x26: "BlitSpriteDef", 0x27: "BlitSprite",
    0x28: "PointLight", 0x29: "Zone",
    0x2A: "AmbientLight", 0x2B: "DirectionalLight",
    0x2C: "DMSpriteDef", 0x2D: "DMSprite",
    0x2E: "DMTrackDef", 0x2F: "DMTrack",
    0x30: "MaterialDef", 0x31: "MaterialPalette",
    0x32: "DmRGBTrackDef", 0x33: "DmRGBTrack",
    0x34: "ParticleCloudDef", 0x35: "GlobalAmbientLightDef",
    0x36: "DmSpriteDef2", 0x37: "DmTrackDef2",
}

# WLD file identifiers
WLD_FILE_IDENTIFIER     = 0x54503D02
WLD_FORMAT_OLD          = 0x00015500
WLD_FORMAT_NEW          = 0x1000C800

# PFS archive constants
PFS_MAGIC               = 0x20534650  # "PFS " in little-endian
PFS_FILENAME_CRC        = 0x61580AC9
EQZIP_FILENAME_CRC      = 0xFFFFFFFF
PFS_VERSION_1           = 0x00010000
PFS_VERSION_2           = 0x00020000

# WLD type categories for content detection
WLD_TYPE_ZONE           = 0
WLD_TYPE_ZONE_OBJECTS   = 1
WLD_TYPE_LIGHTS         = 2
WLD_TYPE_OBJECTS        = 3
WLD_TYPE_SKY            = 4
WLD_TYPE_CHARACTERS     = 5
WLD_TYPE_EQUIPMENT      = 6

# Particle cloud spawn types
PARTICLE_SPAWN_SPHERE   = 1
PARTICLE_SPAWN_PLANE    = 2
PARTICLE_SPAWN_STREAM   = 3
PARTICLE_SPAWN_NONE     = 4
