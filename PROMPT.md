# PROMPT.md — Build spec

Implementation brief for the SnowRunner Build Stage Lookup tool.
Read `CLAUDE.md` first for domain background and constraints.

---

## Goal

Build a single-file Python desktop app, `stage_lookup.py`, that lets a SnowRunner
modder look up the exact `stagesProgress` state names for a model by searching
its name, reading directly from the game's `initial.pak`.

Stdlib only: `zipfile`, `xml.etree.ElementTree`, `tkinter`, `pathlib`, `json`,
`re`. No pip installs.

---

## User flow

1. **First launch** — no game path configured. Show a setup prompt: a "Locate
   SnowRunner folder…" button plus a text field for a manual path.
   - Try autodetect first against the common install roots (Steam, Epic, and the
     same paths on drives D:–H:). If exactly one hit, prefill it.
   - Validate that `<root>\en_us\preload\paks\client\initial.pak` exists before
     accepting. Show a clear error naming the expected path if not.
2. **Indexing** — on first accept, and whenever the archive changed, scan the
   archive's namelist and build the model index. Show a progress/status line;
   keep the UI responsive (do it on a worker thread, marshal results back to the
   Tk main thread).
3. **Search** — user types in the search box. Results list filters live.
   - Default: only `*_objective` models are listed.
   - A "show all models" checkbox lifts that filter.
   - Substring match, case-insensitive. Typing `bridge` matches
     `bridge_wooden_big_02_objective`.
4. **Select** — clicking/arrowing to a result parses that model's XML on demand
   and shows, in a detail pane:
   - The list of stage state names in the order they appear in the file.
   - The full archive path of the XML it came from (e.g.
     `[media]\_dlc\us_03\classes\models\constr_wood_01_objective.xml`).
   - A note if the same model name was found in more than one location, with the
     other paths selectable.
5. **Copy** — a "Copy all" button copies the state names one per line, and
   clicking an individual state copies just that one. Show a brief "Copied"
   confirmation. Copy the string byte-for-byte as parsed.

---

## Modules to write (all in one file, but keep these boundaries clean)

### `config`
Load/save a small JSON config in the per-user config dir
(`%APPDATA%\snowrunner-stage-lookup\config.json` on Windows, XDG equivalent
elsewhere). Stores: game root path, last window geometry, "show all models" flag.

### `pak`
- `find_pak(game_root) -> Path` — resolve and validate the archive path.
- `build_index(pak_path, progress_cb) -> dict[str, list[str]]` — open the zip,
  walk `namelist()`, keep entries under any `classes/models/` directory ending in
  `.xml`. Key = model name (filename stem, lowercased); value = list of archive
  paths. Normalize `\` to `/` and lowercase for matching, but **retain the
  original archive path string** for display and for reading back.
- `read_model_xml(pak_path, archive_path) -> bytes` — read one member. Do not
  extract to disk.

### `cache`
Persist the index next to the config as JSON, together with the archive's size
and mtime. On startup, load the cache and rebuild only if size/mtime differ.
Corrupt or unreadable cache = rebuild silently, never crash.

### `parser`
`extract_stages(xml_bytes) -> list[str]`
- Parse the XML and collect the `Name` attribute of every `<Subset>` element,
  at any depth, preserving document order and dropping duplicates.
- Return names **exactly as found** — no strip-and-retype, no case changes. (If
  you want to warn about leading/trailing whitespace, surface it as a warning in
  the UI; do not silently alter the value.)
- Be tolerant: try `utf-8`, fall back to `utf-8-sig` then `latin-1`. If the
  document still won't parse, fall back to a regex over `<Subset[^>]*Name="..."`
  rather than giving up. Raise a typed `ParseError` only if both fail, and let
  the UI show it as a per-model message.

### `ui`
Tkinter window, roughly 900×600, resizable:
- Top row: search entry (focused on launch), "show all models" checkbox.
- Left: results listbox, scrollable.
- Right: detail pane — model name header, stage list, source path (selectable
  text), copy buttons.
- Bottom: status bar — index size, archive path, "Rebuild index" button.
- Keyboard: `Enter` in search jumps to first result, `Ctrl+C` copies all stages
  of the selected model, `Esc` clears search.

---

## Error handling

Every one of these must produce a readable in-window message, never a traceback
to a console the user won't see:

- Game folder not found / `initial.pak` missing at the expected subpath.
- Archive present but not a valid zip, or locked by the running game.
- Model found in the index but its XML member fails to read or parse.
- Model parses fine but contains **zero** `Subset` names — say so explicitly
  ("no build stages defined"), since that's a meaningful answer, not a failure.
- Cache read/write failure — degrade to in-memory index.

---

## Verification

Before calling it done:

1. `extract_stages` unit-tested against small inline XML fixtures covering:
   a two-state model (`build_stage_0`/`build_stage_1`), a three-state model with
   `build_stage_complete`, a smoke-cube style model (`stage_visible`/
   `stage_hidden`), a file with duplicate Subset names, and a malformed file that
   must hit the regex fallback.
2. Index build tested against a synthetic zip fixture that mimics the archive
   layout, including a `[media]/_dlc/us_03/classes/models/` entry and a
   name collision between base and DLC — no real game files needed in tests.
3. Manual smoke test against a real `initial.pak` if available: searching
   `bridge` must surface `bridge_wooden_big_02_objective`, and its stages must
   include `build_stage_0` and `build_stage_1` (per the Editor Guide, p. 204).
4. Confirm the app starts and stays responsive during a full index rebuild.

---

## Build order

1. `parser` + its tests (pure functions, no I/O — get correctness locked first).
2. `pak` indexing + zip fixture tests.
3. `config` and `cache`.
4. Tkinter UI on top of the working core.
5. Autodetect and first-run setup flow.
6. Polish: keyboard shortcuts, geometry persistence, status bar.

---

## Explicitly not now

Writing back to any game file, a bundled model database shipped with the app,
`.exe` packaging, model previews, and support for `shared_sound.pak`.
Keep the door open for packaging later by staying single-file and dependency-free.
