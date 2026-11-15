# HANDOFF — EverQuest Noesis Plugin (NoesisEQ)

**Status: working.** Bone poses are EQMV-verified to machine precision — the plugin's posed worlds match `dump_pose.js` exactly (bee 105/105 bones and parrot 159/159 bones, mean/median/max deviation 0.0000 at idle t=0.5 s). Geometry counts, textures and materials are verified with the offline harness in §5. Written for whoever (human or LLM) picks this up next. Everything below reflects the code as of 2026-11-14, including the fixes in §4 items 16-20.

---

## 1. What this is

A Noesis model plugin (`fmt_everquest_s3d.py` + `eqlib/`) that previews and exports EverQuest assets:

- `.s3d` archives (PFS containers with WLD scene files): zones, zone objects, character races, equipment catalogs
- `.eqg` archives (PFS containers with EQGM `.mod` / EQGS `.mds` models + EQGA `.ani` animations): Luclin-era+ creatures, race bodies with outfit parts, Hero's-Forge-style items

Content type is auto-detected per archive (zone / character / equipment). Character `.s3d` archives also pull **animations from sibling archives** in the same folder (`<race>_chr2.s3d`, `global3_chr.s3d`) via `rapi.getLastCheckedName()` / `rapi.loadIntoByteArray()` — so open files from the real EverQuest directory for full animation sets.

**Deployed location:** `C:\Noesis\plugins\python\` (copy `fmt_everquest_s3d.py` + `eqlib/`). Working repo: `C:\Users\pyrolisk\Documents\proj0\NoesisEQ\` (not a git repo). Test data: `D:\EverQuest\` (1141 `.s3d`, 2667 `.eqg`).

---

## 2. Architecture

| File | Role |
|---|---|
| `fmt_everquest_s3d.py` | Entry point. Type check (PFS magic + version), content detection, dispatch to loaders |
| `eqlib/eq_pfs.py` | PFS container: zlib block chains, name table (crc `0x61580AC9`), names pair with data entries **in data-offset order** |
| `eqlib/eq_const.py` | WLD fragment type codes, WLD/PFS magic + version constants, particle spawn types. Star-imported by almost every module |
| `eqlib/eq_wld.py` | WLD fragments: 0x36/0x2C meshes, 0x2D mesh instances, 0x10 skeletons (DAGs), 0x11 skeleton instances, 0x12/0x13 tracks, 0x14 actors, 0x30/0x31 materials/palettes, 0x03 bitmap lists, 0x34 particle clouds. Name refs are **negative** string-hash offsets |
| `eqlib/eq_wldbuild.py` | Shared WLD model builder: actor-driven models (`build_actor_models`), all-meshes fallback (`build_all_meshes_model`), skeleton composition (`compute_skeleton`), WLD keyframed anims (`build_wld_anims_multi`), material bank with render-method kinds + cutout masking + `_layer` compositing |
| `eqlib/eq_mod.py` | EQGM `.mod` (vsize 32/44 verified against file length) and EQGS `.mds` (always 32-byte verts, per-piece weights). `build_bone_tree` walks **firstChild + sibling chains** (see §4) |
| `eqlib/eq_ani.py` | EQGA `.ani`: 44-byte keys, **absolute ms timestamps**. WLD track frame decode (old: always 8×i16, new: floats; last i16 = bone scale /256) |
| `eqlib/eq_character.py` | EQG model builder: bones (world bind matrices), model-space verts + weights, outfit-part bone remapping, MDS body+head, `.ani` → NoeKeyFramedAnim, companion WLD anims |
| `eqlib/eq_material.py` | Textures: DXT1/3/5 passthrough, uncompressed DDS (bitmask), BMP (8-pal/24/32, client row order, cutout masking), TGA, Luclin `_layer` alpha compositing |
| `eqlib/eq_zone.py` | Zone dispatch: named actors → per-actor models; else all 0x36/0x2C meshes as one model; **modern zones** → `.ter` ground + `.zon` placed `.mod` props as one scene |
| `eqlib/eq_ter.py` | EQG terrain `.ter` (`EQGT`): materials, version-dependent vertex stride (32/44), faces; the ground of every Luclin+ zone |
| `eqlib/eq_zon.py` | Zone definition `.zon`: `EQGZ` binary (model list, per-instance translation/rotation/scale + per-vertex LIT colours, area volumes, point lights) and the classic `EQTZ` text form |
| `eqlib/eq_equipment.py` | Equipment dispatch (EQG → same builder; WLD → character path + cloud markers) |
| `eqlib/eq_particle.py` | `.pts` (EQPT: count@4, 164-byte records) and `.prt` (PTCL: count@4, 104/108-byte records) — fixed layouts; particles render as small placeholder markers |
| `eqlib/eq_mat43.py` | Row-major 3x4 math: quat→matrix, T·R·S compose, inverse, axis maps (see §3) |

---

## 3. The coordinate / skinning conventions (get these right or everything scrambles)

### Axis maps (Vemdas dual-path, per content type)
**EverQuest is +Z up** (verified: the head bone of `auk_chr` and `zof_chr` sits at `(0, 0, +2.2)` in raw fragment space) and **Noesis previews +Z up** (verified the other way round: the EQG map keeps Z and `ahf` stands upright). So no path may swap Y and Z.
- **WLD zones:** `(x,y,z) → (-x, -y, z)`
- **WLD non-zone (character `.s3d`):** identity
- **Exception — WLD item catalogs use the zone map.** `gequip.s3d` (and other actor catalogs) is detected as a *zone*, so `eq_zone` builds its actors with `axis='zone'` i.e. `(-x, -y, z)`. The 195 named item models in §6 are produced that way; `eq_equipment`'s WLD branch is effectively dead code.
- **EQG (.mod/.mds/.ani):** `(x,y,z) → (-x, -y, z)`
- Quats follow their positions' map (conjugation by the corresponding frame rotation).

- **V depends on the texture format, not the content type.** EQG pages are DDS, so they use `1 - v`. WLD pages: **BMP** (rows kept in file order, i.e. bottom-up) → `-v`; **DDS** (rows top-down) → the stored `v`. Luclin-era `.s3d` bodies are DDS, and applying the BMP rule there turned every Akhevan head upside down.

### EQG rotations are stored CONJUGATED
`.mod`/`.mds` bone quats and `.ani` key quats are transposed. `eqg_quat` returns `(qx, qy, -qz, qw)` — the axis-map image of the conjugate. **Do not "simplify" this back to the raw form**: verified numerically, raw scatters 100+ of 121 bones off the mesh. (Note: a naive "conjugation is absorbed by sign-flip maps" proof is wrong — the W sign survives.)

### Noesis skinning convention (GLTF-style, probed in-host)
- A `NoeBone`'s matrix = the **WORLD bind transform**, passed to the constructor. Noesis stores it privately: read it back with `getMatrix()` (it lives in `_matrix`). There is **no** `.mat` attribute — assuming one broke the build of every skinned archive with `'NoeBone' object has no attribute 'mat'`. Construction validates the matrix: passing `None` throws "Invalid type provided for bone matrix".
- Mesh vertices stay in **model space** (EQG stores bind-pose model-space verts; WLD bone-space verts get pre-posed by the bone's bind world, exact since one bone per vertex).
- Noesis composes keyframed **LOCAL** transforms through the bone hierarchy and renders `Σ w · posed · bindInv · v`. Same as the shipped UE4/Oblivion loaders (`rapi.multiplyBones` + model-space verts).
- `NoeMat43`'s three vec3s act as matrix **rows** under `transformPoint` (probed via a throwaway plugin + cmode log). Row-packing in `mat43_to_noemat43` is correct — don't "fix" it to columns.
- `NOEKF_SCALE_SCALAR_1` keyframes carry a **plain float**, not a `NoeVec3` (a vector hangs the exporter indefinitely).

### Keyframes must be COMPLETE
Always set rotation + translation + scale for every keyed bone:
- EQG `.ani` keys carry the **full local translation** (110/118 of ae3's idle tracks equal the rest pivot per frame — they are not deltas).
- WLD track frames carry full shift + scale.
- Leaving components unset makes Noesis evaluate them as zero/identity → skeleton collapse (the "melted blob").
- Guard scale keys: some tracks contain garbage (ae3's `gcst` spikes to **−404** on a lip bone) — the builders skip scale keys outside `[0.001, 16]`.

---

## 4. Bugs found & fixed (the journey — each was a distinct symptom)

1. **BMP textures never loaded** → classic content textureless. Added 8-pal/24/32 BMP (rows in **file order** — that's how the client maps WLD UVs; index 0 masks for cutout materials), TGA, uncompressed DDS.
2. **WLD fragment names all empty** → name refs are negative string-hash offsets; lookup never negated them.
3. **`.mds` parsed garbage** → MDS verts are always 32 bytes (not v3=44); weights use the per-model count field.
4. **`.mod` material desync** → a conditional field read (skip shader offset when name empty) desynced the stream. Always read all fields.
5. **`.ani` timestamps treated as deltas** → they are absolute ms.
6. **WLD tracks** → old format is always 8×i16 regardless of flags; new format uses floats; the 8th i16 is a **bone scale** (seats Luclin eyes: 244; human seat bone: 6; gnome R_POINT: 163 → 0.64× weapons).
7. **WLD 0x36 center offset** → vertices are stored relative to the mesh center; baked in at parse now (was collapsing zones to a pile at the origin).
8. **WLD winding** → faces wind opposite to expected; swapped at build (EQMV-verified).
9. **`min(..., default=)`** → Noesis embeds old Python (3.2-era, writes `cpython-32.pyc`); no `default=` kwarg, and per-pixel Python loops are ~50× slower. Also: no f-strings anywhere.
10. **`NoeBone` matrix validated at construction** → passing `None` then assigning throws (silently swallowed by loader try/excepts; found via file logging in `?cmode`).
11. **EQG conjugated quats** (see §3) → raw form scattered the mesh.
12. **Incomplete keyframes** (see §3) → skeleton collapse during playback ("melted blob").
13. **`build_bone_tree` consecutive-children assumption** → children are NOT always consecutive in the bone table; `ahf.mds` scatters them. Must walk `child_index` then each child's `next_index` (sibling) chain. The old assumption orphaned 30 bones of the Akhevan female (detached legs/spine, starburst skeleton). **ae3 happened to be consecutive, which masked the bug during validation.**
14. **PTS/PRT layouts** → count at +4, fixed-size records (the old length-prefixed parsing was wrong).
15. **Mesh name uniqueness** → Noesis warns and renames on duplicates; all builders now uniquify.
16. **24/32-bit BMP decode raised** → the per-row channel slice used the whole-image length as its stop, so every image taller than one row threw `attempt to assign bytes of size N to extended slice of size M`; `load_texture_from_archive` swallowed it in a bare `except`, so those pages silently rendered untextured. 8-bit palettised was fine, which is why it went unnoticed (851 of gequip's 853 BMPs are 8-bit; the other two, `blade.bmp` and `it153skull1.bmp`, now decode). 
17. **Outfit-part weights were inverted** → `_vertex_weights(v, None)` (the path every `_NN_NN_*` part takes) kept the slots whose weight was **below** the threshold and dropped the real ones, so parts came back rigidly bound to the first empty slot's bone: dkm's leg pieces were 114/116 vertices on bone 0. Parts now use their real bones and several part bones landing on one body bone are merged.
18. **`eq_equipment` NameError** → `WldParticleCloudDef` was used but never imported, so any WLD reaching the equipment path with 0x34 clouds died. Latent only because item catalogs are detected as zones.
19. **Geometry-free archives failed silently** → a `.lay`+texture armor archive was detected as a *zone*, so `load_zone` returned 0 and the "this is a layout, the geometry lives in the race archive" message (in the character loader) was unreachable. Those archives now route to the character loader and log.
20. **`noesis.logPopup()` in `registerNoesisTypes`** → popped the Debug Log window on every startup. Removed; the `print`s still go to Noesis's log.
21. **EQG V was never flipped** → skinned EQG kept "V as stored", which is the D3D convention while Noesis samples V=0 at the bottom. Symptom: the skirt stripes land on the legs, the hair mask on the face, and a body page reads as blotches. Found by re-rendering the textured mesh both ways and comparing with EQMV's `_eqtest/eqmv_shot/ahf_bind.png` — the flipped version is a pixel-level match. All EQG paths (body, head, outfit parts, both skinned and static) now emit `1 - v`.
22. **`Chroma_*` shaders ignored** → chroma is EQ's cut-out shader; without an alpha test the hair, cloth fringes and straps draw as solid quads that swallow what is behind them. EQG materials now call `setAlphaTest(0.5)` when the shader name starts with "chroma" (Everquest_Model_Viewer does the same).
23. **WLD cut-out materials had no alpha test** → 8-bit BMP palette index 0 was already turned into alpha for cut-out materials, but nothing tested it, so foliage/fences/cloth drew solid. `WldMaterialBank` now sets alpha test 0.5 for `cutout` render methods, like EQMV.
24. **Every WLD model was lying on its back** → the Vemdas maps swapped Y and Z (a glTF Y-up convention), but both EQ and Noesis preview are Z-up, so all `.s3d` content came in rotated 90° about X. It reads exactly like broken weight painting: the armature is rotated out of the mesh, a winged creature splays into a "spider", and only the skeleton still looks plausible. Fixed by dropping the swap (`wld_nonzone_*` is now identity, `wld_zone_*` is `(-x,-y,z)` — the same dual-path normalisation, re-targeted at Z-up, so zone and character data still agree with each other). Verified by re-rendering `auk_chr.s3d`: it is a robed, horned figure with two wings, hanging skull-chains and a mace, standing upright, with its head bone at `(0,0,+2.17)`.
25. **Unkeyed bones blew up during playback/blends** → clips key only the bones they animate (bee and ahf clips are ~3 short; the parrot/bee drop real bones, not just helpers), and Noesis poses an unkeyed bone at its bind WORLD matrix, so that bone and its vertices shoot away as soon as a parent is keyed. Both anim builders now pin every unkeyed bone to its rest LOCAL with keys at 0 and the clip end. Verified 0 unkeyed bones across bee (12 clips), ahf (13), auk (10) and dkm (90).
26. **Host API assumed from the harness stub** → `rest_local_matrices` read `bone.mat`, which exists only in the offline stub; the real `NoeBone` keeps the matrix in `_matrix` behind `getMatrix()`. Symptom: every skinned `.eqg`/`.s3d` (creatures included) returned 0 models and Noesis said "This file type cannot be previewed". Fixed with `bone_matrix(b)` (getMatrix → mat → _matrix), and the stub now mirrors `inc_noesis.NoeBone` exactly so a stub-only attribute can never hide this again.
27. **WLD DDS pages were V-negated** → `akm_chr.s3d` (and every Luclin-era `.s3d` body) ships DDS pages, which are top-down; the negated V that is right for classic BMP pages put the face upside down. The builder now picks the V rule per material from the page's actual magic (BMP → `-v`, DDS → stored `v`).
28. **Quaternion extraction had its vector terms inverted** → `mat43_to_quat` used `R12-R21` instead of `R21-R12` (and likewise for the other two), producing the CONJUGATE rotation. Nothing used it until the rest-pose keys did (unkeyed bones, T-pose), which is why models like `ank.eqg` came out crumpled while the bind pose looked fine. Fixed; the T-pose clip now reproduces the bind matrices to 1e-6 on ank/akm/ahf/bee.
29. **Non-uniform scale keys were averaged** → `.ani` scale is per-axis, and model-specific bones carry strongly non-uniform values (`apx`'s `CHEST_CLAV_PADL01` is `(0.273, 0.254, 0.589)`); the loader collapsed every key to one scalar, which skews every vertex those bones own - the "crumbly" look on `apx`/Aphexus while `bee`/`ahf` (which have zero non-uniform frames) stay flawless. Uniform clips still use `NOEKF_SCALE_SCALAR_1` (the proven path); only non-uniform clips switch to `NOEKF_SCALE_VECTOR_3` with a `NoeVec3`, so the blast radius stays on the models that were broken.
30. **WLD track-to-bone matching could pick an arbitrary bone** -> the suffix fallback iterated a dict and took whatever matched first, and the actor-level fragments (AUK_TRACK, ZOF_TRACK) leave an EMPTY suffix after the 3-character animation code, so endswith of an empty string matched every bone and the track could land on a random one. Empty suffixes are now skipped and ambiguous suffix matches take the longest (most specific) candidate in sorted order.
31. **Tracks inside one clip run at different frame rates** -> frame_ms is per track and genuinely differs inside one animation (woe_v2_chr C05: 16 tracks at 100 ms, 51 at 66 ms; 18 of its 19 clips are mixed). Feeding each bone its own timestamps while Noesis plays the clip at one frameRate makes the bones drift apart - the janky playback on woe, while auk_chr (all 33 ms) and zof_chr (nearly all 100 ms) are uniform and look smooth. build_wld_anims_multi now resamples every track of a clip onto the finest rate present, so all keyed bones share identical timestamps (verified: 66/66 keyed bones in woe C05, 16 keys, 0.000-0.990 s).

---

## 5. Validation methodology (reuse this!)

**Ground truth = Zero-Hex's Everquest_Model_Viewer** (MIT; local copy at `_ref_eqmv/Everquest_Model_Viewer-main/`). Its `eqg_viewer.html` is the most reliable EQ format documentation that exists — client-verified by its author. Cross-check every parser against it before shipping.

Tooling built for this (all under `C:\Users\pyrolisk\Documents\proj0\_eqtest\`):

- **`test_plugin.py`** — offline harness: stubs `inc_noesis`/`noesis`/`rapi`, runs the full load pipeline over any list of archives, prints meshes/tris/bones/anims/textures, **summed over every model the archive builds** (so a two-model archive like `ahf.eqg` reports double). Runs on a normal CPython (3.15 here) even though Noesis itself is 3.2. Use: `python test_plugin.py D:\EverQuest\file.eqg ...`
- **`eqmv_shot/`** — EQMV headless renderer. Chromium **is** installed (`%LOCALAPPDATA%ms-playwrightchromium-1254`); an agent sandbox that blocks process spawn reports `spawn EPERM` — that is the sandbox, not a missing browser, and it works with full filesystem access. Set `NODE_PATH` to `eqmv_shot/node_modules` and run: `node headless_shot.js <index.html> <archive> <out.png>` (`npm install playwright` + `npx playwright install chromium` if it is ever wiped), then
  `node headless_shot.js <index.html> <archive> <out.png> [anim] [seconds]`
  (built `index.html` via `build.py`; launches Chromium with `--use-gl=swiftshader`; feeds the archive via `page.setInputFiles('#file', arc)`).
- **`eqmv_shot/dump_pose.js`** — extracts EQMV's **posed bone world matrices** for an archive+anim+time via `page.evaluate` (its `readANI/sampleTrack/trs/conjTrs/worldMatrices` are page globals). This is the ground truth for animation math.
- **`test_conj.py` / `test_rest.py`** — the discriminators that found the conjugation bug (animated bone pivots inside mesh bbox; rest pivots vs their weighted verts).
- Noesis-side end-to-end: `Noesis64.exe ?cmode "D:/EverQuest/x.eqg" "out.obj"` (use forward slashes; backslash-quoting in bash returns exit=1 instantly). Verified working by the original pass; on this sandbox it exits 0 without writing anything (the exe starts a GUI fine, so treat a silent `?cmode` as an environment quirk and fall back to the harness).
- **To see why a real-Noesis load failed:** Noesis swallows `print` output, and `?cmode` may not run at all in a sandboxed session. What works: temporarily call `noesis.logPopup()` in `registerNoesisTypes` **and** redirect `sys.stdout` to a file at the top of `eqLoadModel` (restore it in a `finally`). The per-file `except` blocks print the real reason ("MDS build error x.mds: ...") but only the redirect makes it readable. Note that launching Noesis while an instance is already running just hands off to it — kill it first, or the new build never loads and nothing is logged.

**Validation results (posed bone worlds vs EQMV, same anim + timestamp, mapped by the axis convention):**
- `ae3.eqg` idle t=0: mean **0.20** units / 121 bones (residuals = unkeyed helper bones: camera rig, torch mount, name plates)
- `ae3.eqg` crmp t=0.5s: mean **0.21**
- `ahf.eqg` idle t=0.5s: mean **0.0012** / 115 bones, zero mismatches (that is one model — `ahf.eqg` ships `ahf.mds` *and* `akf.mds`, so the archive builds two models / 230 bones)
- Geometry counts match EQMV exactly, per model (ahf.mds body `AHF00` 3,397 tris / 2,446 verts / 115 bones; ae3 1,904 / 1,170 / 121). `test_plugin.py` prints *sums across the whole archive*, so ahf shows 6,794 / 4,892 / 230 there — double-counting is expected, not a regression.
- The skinning math was also re-checked offline (no Noesis host this pass): deforming the model-space verts with `posed · bindInv` from the plugin's own locals/bind matrices reconstructs EQMV's `ahf_bind.png` silhouette, and the idle pose at t=1.5 s is a natural standing pose. The old consecutive-children walk gives 31 roots / 30 detached bones on `ahf.mds`, which is the starburst in earlier screenshots.
- EQMV renders for reference: `_eqtest/eqmv_shot/*.png` (ahf = four-armed Akhevan female; ae3 = white hunched ghost; CRMP mid-frames show the arms legitimately flailing/crossing)

**Known EQMV limitation:** it times out headlessly on `zof_chr.s3d` (and warns it can't read DX10 DDS textures) — no ground truth exists there; zof was validated numerically instead (sane skeleton, mesh lands on it, 4.8×6.4-unit zombie).

---

## 6. Current state — what works

- Zones: textured, correct winding, material render-method kinds (cutout/translucent/glow), 0x2C + 0x36 meshes
- Equipment catalogs (`gequip.s3d`): 195 individually named item models
- Characters `.s3d` (classic + Luclin): skinned models with world-bind rigs, per-vertex weights, per-palette materials, animations from companions (`global_chr` → 31 models / 721 bones / 377 anims; `globalhuf_chr` → 158 anims / 110 bones)
- Creatures/characters `.eqg`: `.mds` (body + HE?? head) and `.mod` (body + `_NN_NN_*` outfit parts remapped onto the body skeleton + `_*_hair_00.mod`/`_tattoo_00.mod`), rigged, with `.ani` animations (dkm: 90 anims)
- Items and creatures: every EQG mesh flips V (`1 - v`) and `Chroma_*` shaders get a 0.5 alpha test (§4 items 21-22); WLD cut-out materials get the same test (§4 item 23)
- Modern zones (Luclin+): one scene of the `.ter` terrain plus every `.mod` the `.zon` places (arena 128 instances / 43 meshes; ashengate 799 / 246k verts; akhevatwo 476 / 488k), with a 1.5M-vertex budget
- Every skinned model also gets a **`T-Pose`** clip (its bind pose): EQ clips never include one and Noesis runs all clips on one timeline, so this is the only way to see the model as authored
- Command-line export works: `Noesis64.exe ?cmode "in" "out.obj"`

## 7. Shortcomings / open items (for the next pass)

1. **Unkeyed-bone playback semantics — FIXED (§4 item 25).** Noesis poses unkeyed bones at their bind WORLD matrix; every clip here leaves ~3 bones unkeyed (bee/ahf: camera rigs, torch mounts, name plates; the parrot/bee crops also drop real bones). Both animation builders now emit rest-LOCAL keys for every bone a clip does not key.
2. **Noesis timeline oddity — explained.** The slider spans **all clips of the model at once**: the total equals the sum of every clip's key count (ahf 406 ≈ the 401 shown, bee 621 ≈ 618, auk 1176 ≈ 1186). So "329.64 / 618" is a position inside the concatenation (or a cycle-blend between two clips), not a frame of the clip you think you selected. Judge a pose by picking one clip and turning cycle blend (F11) off.
3. **DX10 DDS textures** (fourcc `DX10`, extended header) are unsupported — **EQMV can't read them either** (it prints the same warning). A few ahf/akf body pages fall back to untextured. Fix = BC7/DX10 block decode if you want those pages.
4. **Animated WLD textures** (bitmap lists with frame sleep) render first frame only.
5. **Particles are placeholder markers** — `.pts`/`.prt` parse correctly now, but emitter sprites live in the client's `*Effects` folders and `actoremittersnew.edd` (EQMV documents the EDD layout: 416-byte records, name[64], texture[32], 80 fields; field numbers per EQEmuParticleEditor's data.h). Not integrated.
6. **Classic race animation borrowing** is naive: tracks match by bone-name suffix only. EQMV additionally fits borrowed tracks to the body's bone lengths (pose fitting) and picks the best lender race; not implemented.
7. **Armor `.lay` archives** (`<item>.eqg` with only a `.lay` + textures, e.g. `anasti_sul_cloth.eqg`) hold no geometry — the layout assigns textures to a model living in the race archive. They now reach the character loader and log that explanation (§4 item 19); Noesis then shows its standard "cannot preview" dialog. Could parse EQGL layouts to name the referenced model in the log.
8. **EQG part-bone remap fallback**: parts now use their real weights (§4 item 17), but the *walk-up* fallback for a part bone whose name has no match at all (`ROOT_BONE`, EQMV's loadParts approach) is still unverified on real outfit sets.
9. **Multi-weight vertices** are exact (model-space + `posed·bindInv`); no approximation needed — but `NoeVertWeight` weights are renormalized, which drops zero-weight slots. Fine in practice.
10. **WLD legacy fallback** (archives without actors) pre-poses verts statically with skeleton[0]; no weights/animation. Only hit on odd archives.
11. **Python 3.2 constraints** — no f-strings, no `min/max(default=)`, keep per-pixel loops out of loaders (uncompressed-DDS decode is already the slowest path).
12. **Not a git repo.** Recommend `git init` + baseline commit (the old upstream lives at `_ref_oldplugin/EQNoesisPlugins` for diffing).

## 7b. Modern zones — how the two new formats work

Both formats are documented by **quail** (`github.com/dariusuknuis/quail`: `raw/zon_read.go`, `raw/ter_read.go`, `wce/def/*.yaml`), which is the reader EQMV and the Blender add-on both descend from. Neither EQMV nor the old plugin reads them, so validation is structural rather than pixel-diff: both parsers consume their files exactly (no trailing bytes), and the `.zon` per-vertex LIT counts match the `.ter` vertex counts exactly for every zone tried (arena 6862, ashengate 88776, arginhiz 492298, akhevatwo 221113) — two independent files agreeing is the strongest check available.

- `.zon` instance records: `modelID i32` (**index into the model list**, not a string offset), `instanceID i32` (name offset), translation 3f, rotation 3f, scale f, then `litCount u32` + `litCount` × 4 bytes RGBA when version > 1. Rotations are **RZ, RY, RX** (yaw, pitch, roll) - the composite is `T · Rz(rot0) · Ry(-rot1) · Rx(rot2) · S`.
- `.ter` vertices: v≤2 = pos3 nrm3 uv2 (32 bytes) with a second uv2 array after the faces; v≥3 = pos3 nrm3 tint4 uv2 uv2 (44 bytes). Faces are `{3×u32, material i32, flags u32}`, material index −1 = "FailsafeShader".
- The zone axis map is `(-x,-y,z)`, identical to the EQG map, so `.mod` geometry, `.ter` geometry and `.zon` placements compose without a second change of basis.

Rendered from the .zon so far: **area volumes** as wireframe boxes (`AREA` centre/orientation/extents, same Rz·Ry·Rx order) and **point lights** as small octahedra tinted by `LIGHTCOLOR`; both get their own flat materials. **Baked vertex colours** come from the per-instance `LIT` arrays and the `.ter` tint, with alpha forced to 1.0 because EQ usually stores 0 there. A zone can ship several `.ter` files (`arxmentis` has `ter_am_main` + `ter_arxmentis`) - all are loaded.

Known rough edges: EQ's untextured "Failsafe" blocker planes (arena has 960 such faces) draw flat grey over the floor; the 1.5M-vertex scene budget cuts `arxmentis` off after ~2100 of its 4228 instances (load takes ~10 s there); archives with props but no `.ter`/binary `.zon` (e.g. `nektulos.eqg`) fall back to listing each `.mod`.

## 8. Debugging tips

- Harness first (fast, no GUI), then EQMV headless ground truth, then `?cmode` export, and only then ask the user for viewport screenshots (pause the animation, note which anim is selected).
- `NoeBone` construction errors and loader exceptions are swallowed — add a file-logging wrapper in `eqLoadModel`'s except blocks when chasing a real-host failure.
- Delete `__pycache__` after every deploy; a stale cache once made a fresh deploy silently export nothing.
- The Noesis title bar shows the *sub-model* name (F2 cycles sub-models) — `ahf.eqg` displays as "akf…" when viewing model 2, which once sent me hunting for a nonexistent archive.

---

*Primary sources: Everquest_Model_Viewer (`eqg_viewer.html` — readPFS/readMOD/readMDS/readANI/wldMesh/wldMesh2C/wldSkeleton/decodeTrack/wldMaterial/readPTS/readPRT), the shipped Noesis plugins (fmt_ue4/fmt_gamebryo_nif/fmt_oblivion_nif for the skinning convention), and numerical diffs against EQMV's posed output on real game data.*
