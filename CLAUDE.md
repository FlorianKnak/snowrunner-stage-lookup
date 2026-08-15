# CLAUDE.md — SnowRunner Build Stage Lookup

Project context for anyone (human or AI) working on this repo.

## What this tool is

A small desktop helper for SnowRunner map modders. You type a model name
(e.g. `bridge_wooden_big_02_objective`), and it shows every **build stage state
name** that model supports — the exact strings you must type into the
`stagesProgress` list in the Editor's *Model Building Settings*.

The problem it solves: those names are only discoverable by manually opening
`initial.pak` with 7-Zip, hunting through `[media]\classes\models\` and a dozen
`_dlc` subfolders, opening an XML, and reading `Subset` tags. This tool does that
in one search box.

## Domain background (SnowRunner Editor)

Source of truth: *SnowRunner Editor Guide*, sections 5.16.3 (Model Building
Settings, p. 203–209) and 4.1 (initial.pak location, p. 30).

- Each model has an XML class file. Inside it, each build state is the `Name`
  attribute of a `<Subset>` tag — e.g. `build_stage_0`, `build_stage_1`,
  `build_stage_complete`. **Having `<Subset>` tags is what makes a model
  usable**, and it is the only reliable test.
- The `_objective` suffix is a naming convention, not the rule. Measured against
  the shipped archive (308 usable models): 39 usable models do not end in
  `_objective` — some carry it mid-name (`conveyor_objective_01`,
  `cube_objective_09`, `rus_controlbunker_02_1_part_objectives`), and 9 have no
  "objective" in the name at all (`concrete_block_01_us_07`, `tatra_steamshop`,
  `railway_switch_01_ru17`, …). Conversely `rock_03_rus_objective` is named for
  it but defines no states. **Never filter on the filename.**
- A model with no `<Subset>` of its own may inherit states through
  `<_parent File="..."/>` (e.g. `rocket_broken_02_objective` →
  `rocket_broken_01_objective`). Resolve the chain before calling it stateless.
- Naming is **not** consistent across models. Some have 2 states, some 3+.
  Beyond `build_stage_N`, the shipped vocabulary includes `state_start` /
  `state_end` (the largest group, 85 models), `state_fin`, `state_done`,
  `state_00`–`state_02`, `stage_00`–`stage_03`, `stage_visible` /
  `stage_hidden` (smoke cubes), `stage_opened` / `stage_closed`, and
  one-offs like `cargo_carriage` / `empty_carriage` / `hide_cargo_carriage`.
  This is exactly why lookup must be data-driven, never guessed or hardcoded.
- The Editor requires these strings **verbatim, without spaces**. A typo silently
  breaks the build animation. Copy-to-clipboard accuracy is the core value of
  this tool — never "clean up", re-case, or normalize a state name.
- Two consumption scenarios, both using the same names:
  - *Depend On Cargo* — map states to delivery status (0 = not delivered, 1 = delivered).
  - *Depend On Stages* — map states to the count of accomplished objective stages.

## Where the data lives

`initial.pak` is a plain zip archive in the installed game folder:

```
<game>\en_us\preload\paks\client\initial.pak
```

Typical roots:

- Steam: `C:\Program Files\Steam\steamapps\common\SnowRunner\`
- Epic:  `C:\Program Files\Epic Games\SnowRunner\`

Relevant paths *inside* the archive:

```
[media]\classes\models\<model>.xml                       base game
[media]\_dlc\<dlc_id>\classes\models\<model>.xml          DLC models
```

Note the literal square brackets in `[media]` — they are part of the path inside
the archive, not placeholders. DLC ids look like `us_03`, `ru_08`, `dlc_11`.

## Design decisions (already made, don't relitigate)

- **Reads `initial.pak` directly.** Open it with `zipfile`; no manual extraction
  step for the user. The path is configured once and remembered.
- **Small GUI window** (Tkinter, stdlib only) — search box on top, results list
  below, click a result to copy it. Modders want to paste into the Editor, so
  clipboard support is not optional.
- **Read-only.** The tool never writes to `initial.pak` or the game folder.
  Its only writes are its own config and cache files in the user config dir.
- **The UI is German; the code is English.** Every user-facing string — window
  titles, buttons, status lines, `PakError`/`ParseError` messages — is German,
  and new ones must be too. Numbers go through `de_num()` for `4.740`-style
  grouping. Identifiers, comments, docstrings, tests, and `CLAUDE.md`/`PROMPT.md`
  stay English. **State names from the game are data and are never translated,
  re-cased, or trimmed** — not in the UI, not in the clipboard, not in docs.
- **No third-party dependencies.** `zipfile`, `xml.etree`, and `tkinter` are all
  stdlib. This has to be runnable by a modder who doesn't manage Python
  environments — ideally a single file, ideally freezable to a .exe later.

## Constraints and gotchas

- `initial.pak` is the *only* pak holding `classes/models/*.xml`. Verified across
  all 84 paks of a full install: `shared.pak` is meshes, `editor.pak` is
  `[prebuild]`/textures, `level_*.pak` are scene + textures. There is no second
  archive or loose folder of objective models to find.
- `initial.pak` is small (~28 MB — it is class XMLs, not assets). Indexing reads
  and parses all ~4,700 model files in under a second, so the index records each
  file's `<Subset>` names up front. Never re-scan on a keystroke: build the index
  once and cache it to disk.
- Not every `_dlc/<id>` folder has models. The ~25 that don't are truck DLCs
  (`classes/trucks`, `engines`, `wheels`); map regions (`us_*`, `ru_*`) are the
  ones carrying objective models. Nothing is missing when they are absent.
- Archive paths use backslashes and inconsistent casing. Match case-insensitively
  and normalize separators when indexing.
- The XML files may not be well-formed by strict standards, and may have unusual
  encodings. Parsing must fail soft: a bad file surfaces an error for that one
  model, it does not crash the app or abort the index build.
- The same model name can appear in both base game and a DLC folder. Show all
  hits with their source, rather than silently picking one.
- Game updates change `initial.pak`. Cache must be invalidated on archive
  mtime/size change.
- Windows is the primary target. Don't assume POSIX paths.

## Definition of done for v1

A modder can: launch the app, point it at their game folder once, type
"bridge", see matching models that actually define states, click one, and get a
copyable list of its exact stage state names with the source XML path shown.

## Out of scope for v1

Editing XMLs, writing Editor config, previewing models, `shared_sound.pak`,
models that define no states (they are hidden behind a checkbox, not indexed
away), and anything involving the Editor's own UI automation.
