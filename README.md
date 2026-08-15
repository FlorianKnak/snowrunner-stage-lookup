# SnowRunner Build Stage Lookup

Type a model name, get the exact **build stage state names** it supports — the
strings you paste into `stagesProgress` in the Editor's *Model Building
Settings*.

No more opening `initial.pak` in 7-Zip, digging through `[media]\classes\models\`
and a dozen `_dlc` subfolders, and reading `<Subset>` tags by hand.

---

## Download

Grab **`StageLookup.exe`** from the
[latest release](../../releases/latest). One file, no installer, no Python
needed. Put it anywhere and double-click it.

> **Windows will probably warn you the first time.** The exe isn't code-signed,
> so SmartScreen shows *"Windows protected your PC"*. Click **More info** →
> **Run anyway**. If you'd rather not, run from source instead (see below).

## Using it

1. **First launch** asks for your SnowRunner folder — the one containing `en_us`.
   It tries to autodetect Steam and Epic installs first, so usually you just
   confirm what it found.
2. It indexes the archive once (under a second) and caches the result.
3. Type part of a model name. Click a result.
4. Click any state name to copy it, or **Copy all** for the whole list.
   `Ctrl+C` also copies all. `Esc` clears the search.

State names are copied **exactly** as they appear in the game files — never
re-cased, trimmed, or "cleaned up". The Editor needs them verbatim; a typo
silently breaks the build animation.

If a model appears in both the base game and a DLC, you get a dropdown to pick
which copy you mean, since their states can differ.

## What shows up in the list

By default the list shows only models that **actually define states** — 308 of
them in the current build.

This is deliberately *not* a filter on the `_objective` filename suffix, which
is the obvious approach and is wrong. Measured against the shipped archive:

- 30 usable models carry `_objective` in the *middle* of the name
  (`conveyor_objective_01`, `cube_objective_09`,
  `rus_controlbunker_02_1_part_objectives`).
- 9 more have no "objective" in the name at all, but define real build stages —
  `concrete_block_01_us_07`, `tatra_steamshop`, `railway_switch_01_ru17`,
  `race_scene_us07`, `rus_launchpad_hangar_01_doors`, and others.
- Meanwhile `rock_03_rus_objective` is named for it but defines no states.

Filtering on the name hides 39 models you can use and offers one you can't.
The tool reads the `<Subset>` tags instead, and follows `<_parent>` inheritance
so models like `rocket_broken_02_objective` still resolve to the states they
inherit.

Tick **"Also show models with no states"** to browse all 4,740 model classes.

## State name vocabulary

Naming is not consistent across models, which is the whole reason this tool
exists. What ships in the game:

| Family | Examples |
| --- | --- |
| Build stages | `build_stage_0`, `build_stage_1`, `build_stage_2`, `build_stage_complete` |
| Start/end (largest group) | `state_start`, `state_end`, `state_fin`, `state_done` |
| Numbered states | `state_00`–`state_02`, `stage_00`–`stage_03` |
| Smoke cubes | `stage_visible`, `stage_hidden` |
| Doors | `stage_opened`, `stage_closed` |
| One-offs | `cargo_carriage`, `empty_carriage`, `hide_cargo_carriage` |

Never guess these. Look them up.

## Where the data comes from

`initial.pak` in your install:

```
<game>\en_us\preload\paks\client\initial.pak
```

It's a plain zip (~28 MB — class XMLs, not assets). This is the *only* pak that
contains `classes/models/*.xml`; `shared.pak` is meshes, `editor.pak` is
prebuild data and textures, and the `level_*.pak` files are scenes and textures.
If someone tells you there's another pak or folder with more objective objects,
there isn't — they're most likely seeing models a name-based filter was hiding.

**The tool is strictly read-only.** It never writes to `initial.pak` or anything
in your game folder. Its only writes are its own config and index cache in
`%APPDATA%\snowrunner-stage-lookup\`.

The cache is keyed to the archive's size and modification time, so a game update
triggers an automatic rebuild. There's a **Rebuild index** button if you want to
force one.

## Running from source

Needs Python 3.9+ with Tkinter (both come with the python.org installer).
No third-party packages.

```
python stage_lookup.py
```

Tests, which use a synthetic archive and need no game files:

```
python -m unittest test_stage_lookup -v
```

Building the exe yourself:

```
pip install pyinstaller
pyinstaller --onefile --windowed --name StageLookup stage_lookup.py
```

## Notes

Not affiliated with Saber Interactive or Focus Entertainment. SnowRunner is
their trademark. This tool ships no game content — it reads the files already on
your disk.

Licensed under the [MIT License](LICENSE).
