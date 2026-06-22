# EverQuest S3D/EQG Noesis Plugin

Preview and export EverQuest zone, character, and equipment models directly in Noesis.

## Features

- **Zones** — Load `.s3d` zone files with textured geometry
- **Characters** — Pre-Luclin `_chr.s3d` with skeleton bind-pose vertex assembly. Post-Luclin `.eqg` with skinned meshes
- **Equipment** — Weapon, armor, and item `.eqg` files with particle emitter placeholders
- **Textures** — DDS textures loaded directly from archives (DXT1/3/5)

## Installation

1. Copy `fmt_everquest_s3d.py` and the `eqlib/` folder into `Noesis/plugins/python/`
2. Restart Noesis or press **Alt+T,R** to reload plugins

## Usage

Open any `.s3d` or `.eqg` file from your EverQuest installation. Content type is auto-detected:

| File | Detected as |
|------|------------|
| `gfaydark.s3d` | Zone |
| `zeb_chr.s3d` | Character (WLD) |
| `ala.eqg` | Character (EQG) |
| `fireelfchain.eqg` | Equipment |

## Known Issues

- Textures for newer EQG files may fail to load if the referenced DDS isn't in the archive
- Particle effects are shown as placeholder geometry (emitter location indicators)
- Some post-Luclin character models may have bone naming differences

## License

**No Assets Included:** This repository contains source code only. It does not contain any copyrighted assets (models, textures, sounds, or game data) from EverQuest. Users must provide their own legally obtained copy of the game to utilize these tools.

**Trademark:** EverQuest is a registered trademark of Daybreak Game Company LLC. This project is not affiliated with, endorsed by, or licensed by Daybreak Game Company LLC.

## Build Notes

### Coordinate System

Uses the Vemdas dual-path convention:
- **Zones:** `swap Y↔Z + negate X` → `(-x, z, y)`
- **Non-zone (characters/equipment):** `swap Y↔Z + negate Z` → `(x, z, -y)`
- **EQG MOD/MDS:** `(-x, -y, z)`

### References

- [Noesis](https://richwhitehouse.com/index.php?content=inc_projects.php&showproject=91) — Model viewer and export tool
- [EQSage](https://github.com/knervous/eqsage) — JavaScript S3D/EQG converter and viewer
- [LanternEQ](https://www.lanterneq.com) — EQ asset extraction toolchain
- [LEM-Vemdas](https://github.com/vemdas/LanternExtractor) — C# extractor with composable vector translation pipeline
- [EQLanternProj](https://github.com/tmyhres/LanternGoExtract) — Go port of LanternExtractor
