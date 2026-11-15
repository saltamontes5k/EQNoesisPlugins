# EverQuest S3D/EQG Noesis Plugin

Preview and export EverQuest zone, character, and equipment models directly in Noesis.

## Features

- **Zones** — `.s3d` zone archives with textured geometry (0x36 and 0x2C meshes), correct face winding, and material render-method handling (cut-out, translucent, glow)
- **Named actors** — equipment catalogs (`gequip.s3d`, object archives) build one named model per 0x14 actor instead of one untextured jumble
- **Characters** — pre-Luclin and Luclin `.s3d` bodies load as skinned models: full skeletons (with the WLD track bone-scale fix for eyes/seat bones), per-vertex skin weights, per-palette materials, and animations pulled from companion archives (`<race>_chr2.s3d`, `global3_chr.s3d`)
- **EQG characters/creatures** — `.mod` bodies with outfit/hair parts skinned onto the body skeleton, `.mds` creatures (body + head, 32-byte vertices), per-vertex weights
- **Animations** — EQGA `.ani` files (absolute-millisecond keys) and WLD track fragments both build Noesis keyframed animations, including bone-scale tracks
- **Equipment** — weapon/armor `.eqg` items load individually rigged where skinned, with attachment-point markers from `.pts`
- **Textures** — DDS (DXT1/3/5 and uncompressed RGB/RGBA via channel masks), BMP (8-bit palettised incl. cut-out masking, 24/32-bit, client row order), TGA (24/32-bit, raw + RLE); `Chroma*` shaders and WLD cut-out render methods get an alpha test, so masked pages cut out instead of drawing solid; Luclin armor-page layering (`<page>.dds_layer`) composited over the skin page

## Installation

1. Copy `fmt_everquest_s3d.py` and the `eqlib/` folder into `Noesis/plugins/python/`
2. Restart Noesis or press **Alt+T,R** to reload plugins

## Usage

Open any `.s3d` or `.eqg` file from your EverQuest installation. Content type is auto-detected:

| File | Detected as | What you get |
|------|------------|--------------|
| `gfaydark.s3d` | Zone | All zone geometry, textured |
| `gequip.s3d` | Zone (named actors) | One named model per item |
| `zeb_chr.s3d` | Character (WLD) | Skinned race models + animations |
| `globalhuf_chr.s3d` | Character (WLD) | Luclin half-elf body, rigged, 150+ anims from companions |
| `ala.eqg` | Character (EQG/MDS) | Creature body, rigged, 20 anims |
| `dkm.eqg` | Character (EQG) | Drakkin body + outfit parts, 90 anims |
| `fireelfchain.eqg` | Equipment | Skinned Hero's Forge pieces |
| `it110800.eqg` | Equipment | Rigged/static item + `.pts` markers |

Character archives also find animations in sibling archives in the same folder (`<race>_chr2.s3d`, `global3_chr.s3d`), so open files from your EverQuest directory for the full animation sets.

Command-line export works too: `Noesis64.exe ?cmode "D:\EverQuest\ala.eqg" "out.obj"`

## Format notes (verified against Everquest_Model_Viewer)

- **PFS** — zlib block chains; name table maps to entries in data-offset order
- **EQGM .mod** — 32-byte vertices (v1/v2) or 44 bytes (v3, rgba + uv2); vertex size verified against file length
- **EQGS .mds** — vertices are always 32 bytes; per-model weight records; body + `HE??` head variants
- **EQGA .ani** — keys are 44 bytes with **absolute** millisecond timestamps (not deltas)
- **WLD tracks** — old format: always 8×i16 frames (the last value is a bone **scale**, e.g. 244 seats Luclin eyes, 6 = human seat bone, 163 = gnome R_POINT 0.64× weapons); new format: float frames
- **WLD meshes** — vertices are stored relative to each mesh's center offset (baked in at parse time); WLD faces wind opposite to expected (swapped at build)
- **UVs** — WLD uses V negated; EQG (creatures, race bodies, outfit parts, items — skinned or static alike) flips V to `1 - v`, because EQG stores V=0 at the image top and Noesis samples V=0 at the bottom. BMP rows are kept in file order, matching how the client maps WLD UVs
- **Skinned model representation (Noesis convention)** — bones carry the WORLD bind matrix and vertices stay in model space; Noesis composes keyframed local transforms through the hierarchy and renders `posed * bindInv * v` (same convention as the shipped UE4/Oblivion loaders). WLD bone-space vertices are pre-posed by the bone's bind world (exact, one bone per vertex)
- **Scale keys** — Noesis `NOEKF_SCALE_SCALAR_1` keyframes carry a plain float, not a vector (a vector hangs the exporter)
- **Python 3.2** — Noesis embeds an old interpreter: no `min()/max(default=)`, and heavy per-pixel Python loops (e.g. uncompressed-DDS decode) are extremely slow

## Known Issues

- Particle effects are shown as placeholder geometry (emitter location indicators); emitter sprites in the client's `*Effects` folders are not resolved
- Animated WLD textures (bitmap lists with sleep/frame fields) show their first frame only
- Texture-only or animation-only archives (e.g. `bmpwad*.s3d`, `*_chr2.s3d` without geometry) load no models by design
- Armor **layout archives** (`<item>.eqg` containing only a `.lay` file + textures, e.g. `anasti_sul_cloth.eqg`) hold no geometry — the `.lay` assigns textures to a model that lives in the race's archive — so nothing can be previewed; the log explains this when it happens
- Classic races borrow animations from `global3_chr.s3d`; pose-blending and cross-race track fitting (as in Everquest_Model_Viewer) is not implemented

## License

**No Assets Included:** This repository contains source code only. It does not contain any copyrighted assets (models, textures, sounds, or game data) from EverQuest. Users must provide their own legally obtained copy of the game to utilize these tools.

**Trademark:** EverQuest is a registered trademark of Daybreak Game Company LLC. This project is not affiliated with, endorsed by, or licensed by Daybreak Game Company LLC.

## Build Notes

### Coordinate System

EverQuest is Z-up and Noesis previews Z-up, so no path swaps Y and Z. The Vemdas dual-path normalisation is kept, re-targeted at Z-up:
- **Zones:** `(-x, -y, z)`
- **Non-zone (characters/equipment):** identity `(x, y, z)`
- **EQG MOD/MDS:** `(-x, -y, z)`

EQG bone/animation rotations are stored **conjugated** ("transposed"); `eqg_quat` folds that into the axis map (`(qx, qy, -qz, qw)`). Verified numerically: animated bone pivots stay on their weighted vertices only with the conjugated form (raw scatters 100+ of 121 bones off the mesh).

### References

- [Noesis](https://richwhitehouse.com/index.php?content=inc_projects.php&showproject=91) — Model viewer and export tool
- [Everquest_Model_Viewer](https://github.com/Zero-Hex/Everquest_Model_Viewer) — Browser-based EQ model viewer; source of the verified format details used in this update (PFS name mapping, MOD/MDS vertex sizes, ANI timestamps, WLD track scale, texture formats, layer compositing, actor/skeleton structure)
- [EQSage](https://github.com/knervous/eqsage) — JavaScript S3D/EQG converter and viewer
- [LanternEQ](https://www.lanterneq.com) — EQ asset extraction toolchain
- [LEM-Vemdas](https://github.com/vemdas/LanternExtractor) — C# extractor with composable vector translation pipeline
- [EQLanternProj](https://github.com/tmyhres/LanternGoExtract) — Go port of LanternExtractor
