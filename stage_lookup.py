#!/usr/bin/env python3
"""SnowRunner Baustufen-Suche.

Modellnamen suchen und die exakten `stagesProgress`-Statusnamen erhalten, die
in die Model Building Settings des Editors gehören. Liest initial.pak direkt.

Die Oberfläche ist deutsch; Code und Kommentare bleiben englisch.
Statusnamen aus dem Spiel werden niemals übersetzt — sie sind Daten und müssen
wortwörtlich erhalten bleiben.

Nur Standardbibliothek. Start mit:  python stage_lookup.py
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

APP_NAME = "snowrunner-stage-lookup"
PAK_SUBPATH = Path("en_us") / "preload" / "paks" / "client" / "initial.pak"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "game_root": "",
    "geometry": "900x600",
    "show_stateless_models": False,
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key in DEFAULT_CONFIG:
                if key in stored:
                    cfg[key] = stored[key]
    except (OSError, ValueError):
        pass  # missing or corrupt config -> defaults
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# pak
# --------------------------------------------------------------------------


class PakError(Exception):
    """Anything wrong with locating or reading the archive."""


def find_pak(game_root) -> Path:
    """Resolve <game_root>/en_us/preload/paks/client/initial.pak, or raise."""
    if not game_root or not str(game_root).strip():
        raise PakError("Kein SnowRunner-Ordner festgelegt.")
    root = Path(str(game_root).strip().strip('"'))
    if root.name.lower() == "initial.pak":  # user pointed straight at the file
        pak = root
    else:
        pak = root / PAK_SUBPATH
    if not pak.is_file():
        raise PakError(
            "initial.pak wurde nicht gefunden.\nErwartet unter:\n"
            f"{pak}\n\nBitte den SnowRunner-Installationsordner selbst auswählen "
            "(den Ordner, der 'en_us' enthält)."
        )
    return pak


def _is_model_entry(normalized: str) -> bool:
    return normalized.endswith(".xml") and (
        "/classes/models/" in normalized or normalized.startswith("classes/models/")
    )


INDEX_VERSION = 2


def build_index(pak_path, progress_cb=None) -> dict:
    """Index every model XML in the archive.

    Returns a JSON-serialisable dict:

        {
          "version": INDEX_VERSION,
          "paths":   {model name (lowercased stem): [archive path, ...]},
          "subsets": {archive path: [Subset Name, ...]},   # verbatim, in order
          "parents": {archive path: parent model name or None},
        }

    Archive paths are kept exactly as stored so they can be read back. Every
    model file is parsed here rather than at search time: which models are
    actually usable is decided by whether they define <Subset> tags, not by
    their filename. The whole pass is cheap (a few hundred ms over ~4,700
    files) because initial.pak's class XMLs are tiny.
    """
    pak_path = Path(pak_path)
    paths: dict[str, list[str]] = {}
    subsets: dict[str, list[str]] = {}
    parents: dict[str, str | None] = {}
    try:
        with zipfile.ZipFile(pak_path) as zf:
            entries = [
                name for name in zf.namelist()
                if _is_model_entry(name.replace("\\", "/").lower())
            ]
            total = len(entries)
            for i, name in enumerate(entries):
                normalized = name.replace("\\", "/").lower()
                model = normalized.rsplit("/", 1)[-1][: -len(".xml")]
                paths.setdefault(model, []).append(name)
                # A single unreadable or unparseable member must not abort the
                # build; it just indexes as "no states".
                try:
                    raw = zf.read(name)
                except (KeyError, zipfile.BadZipFile, OSError, RuntimeError):
                    subsets[name] = []
                    parents[name] = None
                    continue
                try:
                    subsets[name] = extract_stages(raw)
                except ParseError:
                    subsets[name] = []
                parents[name] = parent_model_name(raw)
                if progress_cb is not None and (i % 250 == 0 or i == total - 1):
                    progress_cb(i + 1, total)
    except zipfile.BadZipFile as exc:
        raise PakError(
            f"{pak_path.name} ist kein lesbares ZIP-Archiv: {exc}"
        ) from exc
    except OSError as exc:
        raise PakError(
            f"{pak_path} konnte nicht geöffnet werden.\n{exc}\n"
            "Falls SnowRunner oder der Editor läuft, bitte schließen und erneut versuchen."
        ) from exc

    return {
        "version": INDEX_VERSION,
        "paths": paths,
        "subsets": subsets,
        "parents": parents,
    }


def models_with_states(index, max_depth=4) -> set:
    """Model names that resolve to at least one state name.

    Mirrors what `stages_for` will find, including states inherited through
    <_parent>, but answers from the index alone — no archive reads.
    """
    paths = index["paths"]
    subsets = index["subsets"]
    parents = index["parents"]

    def resolves(archive_path):
        seen = set()
        for _ in range(max_depth):
            if subsets.get(archive_path):
                return True
            parent = parents.get(archive_path)
            if not parent or parent in seen or parent not in paths:
                return False
            seen.add(parent)
            archive_path = paths[parent][0]
        return False

    return {
        model for model, locations in paths.items()
        if any(resolves(path) for path in locations)
    }


def read_model_xml(pak_path, archive_path) -> bytes:
    """Read a single member. Never extracts to disk."""
    try:
        with zipfile.ZipFile(Path(pak_path)) as zf:
            return zf.read(archive_path)
    except KeyError as exc:
        raise PakError(
            f"{archive_path} ist nicht mehr im Archiv enthalten "
            "(bitte Index neu aufbauen)."
        ) from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise PakError(f"{archive_path} konnte nicht gelesen werden: {exc}") from exc


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def cache_path() -> Path:
    return config_dir() / "index_cache.json"


def _pak_stamp(pak_path) -> dict:
    stat = Path(pak_path).stat()
    return {"path": str(pak_path), "size": stat.st_size, "mtime": stat.st_mtime}


def load_cache(pak_path):
    """Return the cached index if it matches this archive, else None."""
    try:
        stamp = _pak_stamp(pak_path)
        with open(cache_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if (
            data.get("path") != stamp["path"]
            or data.get("size") != stamp["size"]
            or data.get("mtime") != stamp["mtime"]
        ):
            return None
        index = data.get("index")
        if not isinstance(index, dict) or index.get("version") != INDEX_VERSION:
            return None  # missing, or written by an older layout -> rebuild
        if not all(isinstance(index.get(k), dict) for k in ("paths", "subsets", "parents")):
            return None
        return {
            "version": INDEX_VERSION,
            "paths": {k: list(v) for k, v in index["paths"].items()
                      if isinstance(v, list)},
            "subsets": {k: list(v) for k, v in index["subsets"].items()
                        if isinstance(v, list)},
            "parents": dict(index["parents"]),
        }
    except (OSError, ValueError, TypeError, AttributeError):
        return None  # corrupt or unreadable -> rebuild silently


def save_cache(pak_path, index) -> bool:
    try:
        payload = _pak_stamp(pak_path)
        payload["index"] = index
        config_dir().mkdir(parents=True, exist_ok=True)
        with open(cache_path(), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return True
    except (OSError, ValueError):
        return False  # degrade to in-memory index


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


class ParseError(Exception):
    """The model XML could not be understood at all."""


_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>")
_SUBSET_RE = re.compile(
    r"""<\s*Subset\b[^>]*?\bName\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE | re.DOTALL,
)


def _local_name(tag) -> str:
    if isinstance(tag, str):
        return tag.rsplit("}", 1)[-1]
    return ""


def _decode_attempts(raw: bytes):
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            yield raw.decode(enc)
        except UnicodeDecodeError:
            continue


def _dedupe(names):
    seen = set()
    out = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extract_stages(xml_bytes: bytes):
    """Subset names in document order, duplicates dropped, values untouched."""
    candidates = [xml_bytes]
    for text in _decode_attempts(xml_bytes):
        body = _XML_DECL_RE.sub("", text, count=1)
        candidates.append(body)
        # Some model files have two top-level elements (a <_parent> line followed
        # by <ModelBrand>), which is not well-formed XML on its own.
        candidates.append(f"<_stagelookup_root_>{body}</_stagelookup_root_>")

    for candidate in candidates:
        try:
            root = ET.fromstring(candidate)
        except (ET.ParseError, ValueError):
            continue
        return _dedupe(
            el.get("Name")
            for el in root.iter()
            if _local_name(el.tag) == "Subset" and el.get("Name") is not None
        )

    # Malformed document: salvage what we can.
    for text in _decode_attempts(xml_bytes):
        found = [m.group(1) if m.group(1) is not None else m.group(2)
                 for m in _SUBSET_RE.finditer(text)]
        if found:
            return _dedupe(found)

    raise ParseError(
        "Diese XML-Datei konnte nicht gelesen werden und enthält keine "
        "<Subset Name=...>-Tags."
    )


_PARENT_RE = re.compile(
    r"""<\s*_parent\b[^>]*?\bFile\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE | re.DOTALL,
)


def parent_model_name(xml_bytes: bytes):
    """The model this one inherits from via <_parent File="..."/>, if any."""
    for text in _decode_attempts(xml_bytes):
        match = _PARENT_RE.search(text)
        if match:
            value = (match.group(1) if match.group(1) is not None else match.group(2))
            name = value.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
            if name.endswith(".xml"):
                name = name[: -len(".xml")]
            return name or None
    return None


def stages_for(pak_path, index, archive_path, max_depth=4):
    """Stages for one model, following <_parent> when it defines none itself.

    Returns (stages, origin_archive_path, inheritance_chain). The chain is
    empty when the stages came from the file the user actually picked.
    """
    paths = index["paths"]
    chain = []
    path = archive_path
    seen = set()
    for _ in range(max_depth):
        raw = read_model_xml(pak_path, path)
        try:
            stages = extract_stages(raw)
        except ParseError:
            if not chain:
                raise
            break
        if stages:
            return stages, path, chain
        parent = parent_model_name(raw)
        if not parent or parent in seen or parent not in paths:
            break
        seen.add(parent)
        chain.append(parent)
        path = paths[parent][0]
    return [], archive_path, chain


# --------------------------------------------------------------------------
# autodetect
# --------------------------------------------------------------------------

_RELATIVE_ROOTS = [
    Path("Program Files") / "Steam" / "steamapps" / "common" / "SnowRunner",
    Path("Program Files (x86)") / "Steam" / "steamapps" / "common" / "SnowRunner",
    Path("Steam") / "steamapps" / "common" / "SnowRunner",
    Path("SteamLibrary") / "steamapps" / "common" / "SnowRunner",
    Path("Games") / "Steam" / "steamapps" / "common" / "SnowRunner",
    Path("Program Files") / "Epic Games" / "SnowRunner",
    Path("Epic Games") / "SnowRunner",
    Path("Games") / "Epic Games" / "SnowRunner",
    Path("SnowRunner"),
    Path("Games") / "SnowRunner",
]


def candidate_game_roots():
    if sys.platform == "win32":
        drives = ["C:\\", "D:\\", "E:\\", "F:\\", "G:\\", "H:\\"]
    else:
        drives = [str(Path.home()) + os.sep, os.sep]
    for drive in drives:
        for rel in _RELATIVE_ROOTS:
            yield Path(drive) / rel


def autodetect_game_roots():
    """Every candidate root that actually holds an initial.pak."""
    hits = []
    for root in candidate_game_roots():
        try:
            if (root / PAK_SUBPATH).is_file():
                resolved = str(root)
                if resolved not in hits:
                    hits.append(resolved)
        except OSError:
            continue
    return hits


# --------------------------------------------------------------------------
# ui
# --------------------------------------------------------------------------


def de_num(value) -> str:
    """Group thousands the German way: 4740 -> '4.740'."""
    return f"{value:,}".replace(",", ".")


def _run_ui(hook=None):
    """Start the GUI. `hook` is a test seam: called with the App once it is up."""
    import tkinter as tk
    from tkinter import filedialog, ttk

    class SetupDialog(tk.Toplevel):
        """First-run / change-folder prompt. Returns a validated game root."""

        def __init__(self, master, initial=""):
            super().__init__(master)
            self.title("SnowRunner finden")
            self.result = None
            self.transient(master)
            self.resizable(False, False)

            frame = ttk.Frame(self, padding=14)
            frame.pack(fill="both", expand=True)

            ttk.Label(
                frame,
                text="Bitte den SnowRunner-Installationsordner auswählen\n"
                     "(den Ordner, der 'en_us' enthält).",
                justify="left",
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

            self.var_path = tk.StringVar(value=initial)
            entry = ttk.Entry(frame, textvariable=self.var_path, width=64)
            entry.grid(row=1, column=0, sticky="we")
            ttk.Button(frame, text="SnowRunner-Ordner suchen…", command=self._browse).grid(
                row=1, column=1, padx=(8, 0)
            )

            self.lbl_error = ttk.Label(frame, text="", foreground="#b00020", justify="left")
            self.lbl_error.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

            buttons = ttk.Frame(frame)
            buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
            ttk.Button(buttons, text="Abbrechen", command=self._cancel).pack(side="right")
            ttk.Button(buttons, text="Diesen Ordner verwenden", command=self._accept).pack(
                side="right", padx=(0, 8)
            )

            detected = autodetect_game_roots()
            if not initial and len(detected) == 1:
                self.var_path.set(detected[0])
                self.lbl_error.configure(
                    text=f"Installation gefunden unter {detected[0]}", foreground="#0a7d33"
                )
            elif not initial and len(detected) > 1:
                self.lbl_error.configure(
                    text="Mehrere Installationen gefunden:\n  " + "\n  ".join(detected),
                    foreground="#555555",
                )

            entry.focus_set()
            self.bind("<Return>", lambda _e: self._accept())
            self.bind("<Escape>", lambda _e: self._cancel())
            self.protocol("WM_DELETE_WINDOW", self._cancel)
            self.grab_set()

        def _browse(self):
            chosen = filedialog.askdirectory(title="SnowRunner-Ordner auswählen", parent=self)
            if chosen:
                self.var_path.set(os.path.normpath(chosen))

        def _accept(self):
            try:
                find_pak(self.var_path.get())
            except PakError as exc:
                self.lbl_error.configure(text=str(exc), foreground="#b00020")
                return
            self.result = self.var_path.get().strip().strip('"')
            self.destroy()

        def _cancel(self):
            self.result = None
            self.destroy()

    class App:
        def __init__(self, root):
            self.root = root
            self.cfg = load_config()
            self.index = {}
            self.paths = {}
            self.state_models = set()
            self.model_names = []
            self.shown = []
            self.pak_path = None
            self.current_model = None
            self.current_stages = []
            self.events = queue.Queue()
            self.busy = False
            self._status_token = 0

            root.title("SnowRunner Baustufen-Suche")
            try:
                root.geometry(self.cfg.get("geometry") or "900x600")
            except tk.TclError:
                root.geometry("900x600")
            root.minsize(700, 420)
            root.protocol("WM_DELETE_WINDOW", self._on_close)

            self._build_widgets()
            self._bind_keys()
            self.root.after(80, self._pump_events)
            self.root.after(120, self._startup)
            if hook is not None:
                self.root.after(160, lambda: hook(self))

        # -- widgets ----------------------------------------------------
        def _build_widgets(self):
            root = self.root
            root.columnconfigure(0, weight=1)
            root.rowconfigure(1, weight=1)

            top = ttk.Frame(root, padding=(10, 10, 10, 6))
            top.grid(row=0, column=0, sticky="we")
            top.columnconfigure(1, weight=1)

            ttk.Label(top, text="Suche").grid(row=0, column=0, padx=(0, 8))
            self.var_search = tk.StringVar()
            self.var_search.trace_add("write", lambda *_a: self._refresh_results())
            self.entry_search = ttk.Entry(top, textvariable=self.var_search)
            self.entry_search.grid(row=0, column=1, sticky="we")

            self.var_show_all = tk.BooleanVar(
                value=bool(self.cfg.get("show_stateless_models"))
            )
            ttk.Checkbutton(
                top,
                text="Auch Modelle ohne Status anzeigen",
                variable=self.var_show_all,
                command=self._refresh_results,
            ).grid(row=0, column=2, padx=(10, 0))

            panes = ttk.PanedWindow(root, orient="horizontal")
            panes.grid(row=1, column=0, sticky="nsew", padx=10)

            left = ttk.Frame(panes)
            left.rowconfigure(1, weight=1)
            left.columnconfigure(0, weight=1)
            self.lbl_results = ttk.Label(left, text="Modelle")
            self.lbl_results.grid(row=0, column=0, sticky="w", pady=(0, 4))
            self.list_results = tk.Listbox(left, exportselection=False, activestyle="dotbox")
            self.list_results.grid(row=1, column=0, sticky="nsew")
            scroll_results = ttk.Scrollbar(left, orient="vertical",
                                           command=self.list_results.yview)
            scroll_results.grid(row=1, column=1, sticky="ns")
            self.list_results.configure(yscrollcommand=scroll_results.set)
            self.list_results.bind("<<ListboxSelect>>", lambda _e: self._on_pick_model())
            panes.add(left, weight=1)

            right = ttk.Frame(panes, padding=(12, 0, 0, 0))
            right.columnconfigure(0, weight=1)
            right.rowconfigure(4, weight=1)

            self.lbl_model = ttk.Label(right, text="Modell auswählen",
                                       font=("Segoe UI", 12, "bold"))
            self.lbl_model.grid(row=0, column=0, sticky="w", pady=(0, 6))

            self.frame_sources = ttk.Frame(right)
            self.frame_sources.grid(row=1, column=0, sticky="we")
            self.frame_sources.columnconfigure(0, weight=1)
            self.var_source = tk.StringVar()
            self.combo_sources = ttk.Combobox(
                self.frame_sources, textvariable=self.var_source, state="readonly"
            )
            self.combo_sources.bind("<<ComboboxSelected>>", lambda _e: self._on_pick_source())
            self.lbl_multi = ttk.Label(self.frame_sources, text="", foreground="#8a5a00")

            path_row = ttk.Frame(right)
            path_row.grid(row=2, column=0, sticky="we", pady=(6, 0))
            path_row.columnconfigure(0, weight=1)
            self.entry_path = ttk.Entry(path_row, state="readonly")
            self.entry_path.grid(row=0, column=0, sticky="we")
            ttk.Button(path_row, text="Pfad kopieren", command=self._copy_path).grid(
                row=0, column=1, padx=(8, 0)
            )

            self.lbl_message = ttk.Label(right, text="", foreground="#b00020",
                                         wraplength=420, justify="left")
            self.lbl_message.grid(row=3, column=0, sticky="we", pady=(6, 0))

            stages = ttk.Frame(right)
            stages.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
            stages.rowconfigure(1, weight=1)
            stages.columnconfigure(0, weight=1)
            ttk.Label(stages, text="Statusnamen der Baustufen (zum Kopieren anklicken)").grid(
                row=0, column=0, sticky="w", pady=(0, 4)
            )
            self.list_stages = tk.Listbox(stages, exportselection=False, activestyle="dotbox")
            self.list_stages.grid(row=1, column=0, sticky="nsew")
            scroll_stages = ttk.Scrollbar(stages, orient="vertical",
                                          command=self.list_stages.yview)
            scroll_stages.grid(row=1, column=1, sticky="ns")
            self.list_stages.configure(yscrollcommand=scroll_stages.set)
            self.list_stages.bind("<Button-1>", self._on_click_stage)

            actions = ttk.Frame(right)
            actions.grid(row=5, column=0, sticky="we", pady=(8, 0))
            self.btn_copy_all = ttk.Button(actions, text="Alle kopieren",
                                           command=self._copy_all, state="disabled")
            self.btn_copy_all.pack(side="left")
            self.lbl_copied = ttk.Label(actions, text="", foreground="#0a7d33")
            self.lbl_copied.pack(side="left", padx=(10, 0))

            panes.add(right, weight=2)

            status = ttk.Frame(root, padding=(10, 8))
            status.grid(row=2, column=0, sticky="we")
            status.columnconfigure(0, weight=1)
            self.lbl_status = ttk.Label(status, text="Startet…", anchor="w")
            self.lbl_status.grid(row=0, column=0, sticky="we")
            self.btn_rebuild = ttk.Button(status, text="Index neu aufbauen",
                                          command=self._rebuild_index)
            self.btn_rebuild.grid(row=0, column=1, padx=(8, 0))
            ttk.Button(status, text="Ordner ändern…", command=self._change_folder).grid(
                row=0, column=2, padx=(8, 0)
            )

        def _bind_keys(self):
            self.entry_search.bind("<Return>", self._on_enter)
            self.root.bind("<Escape>", self._on_escape)
            self.root.bind("<Control-c>", self._on_ctrl_c)
            self.root.bind("<Control-C>", self._on_ctrl_c)
            self.entry_search.focus_set()

        # -- lifecycle --------------------------------------------------
        def _startup(self):
            root_path = self.cfg.get("game_root", "")
            try:
                find_pak(root_path)
            except PakError:
                root_path = ""
            if not root_path:
                if not self._change_folder(first_run=True):
                    self._set_status(
                        "Kein SnowRunner-Ordner festgelegt. "
                        "Mit 'Ordner ändern…' einen auswählen."
                    )
                    return
            else:
                self._use_game_root(root_path)

        def _change_folder(self, first_run=False):
            initial = "" if first_run else self.cfg.get("game_root", "")
            dialog = SetupDialog(self.root, initial=initial)
            self.root.wait_window(dialog)
            if not dialog.result:
                return False
            self._use_game_root(dialog.result)
            return True

        def _use_game_root(self, game_root):
            try:
                self.pak_path = find_pak(game_root)
            except PakError as exc:
                self._set_status(str(exc).splitlines()[0])
                self.lbl_message.configure(text=str(exc))
                return
            self.cfg["game_root"] = str(game_root)
            save_config(self.cfg)
            cached = load_cache(self.pak_path)
            if cached is not None:
                self._install_index(cached, from_cache=True)
            else:
                self._start_index_build()

        def _rebuild_index(self):
            if self.pak_path is None:
                self._change_folder()
                return
            self._start_index_build()

        def _start_index_build(self):
            if self.busy:
                return
            self.busy = True
            self.btn_rebuild.configure(state="disabled")
            self._set_status("Archiv wird indiziert…")
            pak_path = self.pak_path
            events = self.events

            def worker():
                last = [0.0]

                def progress(done, total):
                    now = time.monotonic()
                    if now - last[0] > 0.1 or done == total:
                        last[0] = now
                        events.put(("progress", done, total))

                try:
                    index = build_index(pak_path, progress)
                except PakError as exc:
                    events.put(("index_error", str(exc)))
                    return
                except Exception as exc:  # never lose the UI to a surprise
                    events.put((
                        "index_error",
                        f"Unerwarteter Fehler beim Indizieren: {exc}",
                    ))
                    return
                events.put(("index_done", index))

            threading.Thread(target=worker, daemon=True).start()

        def _pump_events(self):
            try:
                while True:
                    event = self.events.get_nowait()
                    kind = event[0]
                    if kind == "progress":
                        done, total = event[1], event[2]
                        self._set_status(
                            f"Archiv wird indiziert… {de_num(done)} / "
                            f"{de_num(total)} Einträge"
                        )
                    elif kind == "index_done":
                        self.busy = False
                        self.btn_rebuild.configure(state="normal")
                        self._install_index(event[1], from_cache=False)
                    elif kind == "index_error":
                        self.busy = False
                        self.btn_rebuild.configure(state="normal")
                        self._set_status("Indizierung fehlgeschlagen.")
                        self.lbl_message.configure(text=event[1])
            except queue.Empty:
                pass
            self.root.after(80, self._pump_events)

        def _install_index(self, index, from_cache):
            self.index = index
            self.paths = index["paths"]
            self.state_models = models_with_states(index)
            self.model_names = sorted(self.paths)
            if not from_cache:
                if not save_cache(self.pak_path, index):
                    self._flash(
                        "Index-Cache konnte nicht geschrieben werden — "
                        "nur im Arbeitsspeicher."
                    )
            self._refresh_results()
            self.lbl_message.configure(text="")
            source = "Index aus Cache" if from_cache else "Index neu aufgebaut"
            self._set_status(
                f"{de_num(len(self.model_names))} Modelle "
                f"({de_num(len(self.state_models))} mit Baustufen) — "
                f"{source} — {self.pak_path}"
            )

        # -- search / results -------------------------------------------
        def _visible_models(self):
            needle = self.var_search.get().strip().lower()
            show_all = self.var_show_all.get()
            out = []
            for name in self.model_names:
                if not show_all and name not in self.state_models:
                    continue
                if needle and needle not in name:
                    continue
                out.append(name)
            return out

        def _refresh_results(self):
            if self.var_show_all.get() != bool(self.cfg.get("show_stateless_models")):
                self.cfg["show_stateless_models"] = bool(self.var_show_all.get())
                save_config(self.cfg)
            self.shown = self._visible_models()
            self.list_results.delete(0, "end")
            for name in self.shown:
                self.list_results.insert("end", name)
            scope = "Modelle" if self.var_show_all.get() else "Modelle mit Status"
            self.lbl_results.configure(text=f"{de_num(len(self.shown))} {scope}")

        def _on_pick_model(self):
            selection = self.list_results.curselection()
            if not selection:
                return
            self._show_model(self.shown[selection[0]])

        def _show_model(self, model):
            self.current_model = model
            paths = self.paths.get(model, [])
            self.lbl_model.configure(text=model)
            self.combo_sources.configure(values=paths)
            if len(paths) > 1:
                self.combo_sources.grid(row=0, column=0, sticky="we")
                self.lbl_multi.grid(row=1, column=0, sticky="w", pady=(4, 0))
                self.lbl_multi.configure(
                    text=f"An {len(paths)} Orten gefunden — bitte oben auswählen."
                )
            else:
                self.combo_sources.grid_forget()
                self.lbl_multi.grid_forget()
            if paths:
                self.var_source.set(paths[0])
                self._load_stages(paths[0])
            else:
                self._set_stages(
                    [],
                    "Dieses Modell ist nicht mehr im Index. Bitte Index neu aufbauen.",
                )

        def _on_pick_source(self):
            path = self.var_source.get()
            if path:
                self._load_stages(path)

        def _load_stages(self, archive_path):
            self.entry_path.configure(state="normal")
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, archive_path)
            self.entry_path.configure(state="readonly")
            try:
                stages, origin, chain = stages_for(self.pak_path, self.index, archive_path)
            except PakError as exc:
                self._set_stages([], str(exc))
                return
            except ParseError as exc:
                self._set_stages([], str(exc))
                return
            if not stages:
                self._set_stages(
                    [], "In diesem Modell sind keine Baustufen definiert.", error=False
                )
                return
            notes = []
            if chain:
                notes.append(
                    f"Über <_parent> geerbt von {chain[-1]}\n{origin}"
                )
            if any(s != s.strip() for s in stages):
                notes.append("Achtung: Einige Namen haben Leerzeichen am Anfang oder Ende. "
                             "Sie werden exakt so angezeigt und kopiert, wie sie "
                             "gespeichert sind.")
            self._set_stages(stages, "\n".join(notes), error=False)

        def _set_stages(self, stages, message="", error=True):
            self.current_stages = stages
            self.list_stages.delete(0, "end")
            for stage in stages:
                self.list_stages.insert("end", stage)
            self.btn_copy_all.configure(state="normal" if stages else "disabled")
            self.lbl_message.configure(
                text=message, foreground="#b00020" if error else "#8a5a00"
            )

        # -- clipboard --------------------------------------------------
        def _copy(self, text, label):
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            self._flash_copied(f"{label} kopiert")

        def _copy_all(self):
            if not self.current_stages:
                return
            count = len(self.current_stages)
            label = "1 Statusname" if count == 1 else f"{count} Statusnamen"
            self._copy("\n".join(self.current_stages), label)

        def _copy_path(self):
            path = self.entry_path.get()
            if path:
                self._copy(path, "Archivpfad")

        def _on_click_stage(self, event):
            index = self.list_stages.nearest(event.y)
            if index < 0 or index >= len(self.current_stages):
                return
            bbox = self.list_stages.bbox(index)
            if bbox and not (bbox[1] <= event.y <= bbox[1] + bbox[3]):
                return
            self.list_stages.selection_clear(0, "end")
            self.list_stages.selection_set(index)
            self._copy(self.current_stages[index], f'"{self.current_stages[index]}"')

        def _flash_copied(self, text):
            self._status_token += 1
            token = self._status_token
            self.lbl_copied.configure(text=text)
            self.root.after(
                1600,
                lambda: self.lbl_copied.configure(text="")
                if token == self._status_token
                else None,
            )

        def _flash(self, text):
            self._set_status(text)

        def _set_status(self, text):
            self.lbl_status.configure(text=text)

        # -- keys -------------------------------------------------------
        def _on_enter(self, _event):
            if not self.shown:
                return "break"
            self.list_results.selection_clear(0, "end")
            self.list_results.selection_set(0)
            self.list_results.see(0)
            self._show_model(self.shown[0])
            return "break"

        def _on_escape(self, _event):
            self.var_search.set("")
            self.entry_search.focus_set()
            return "break"

        def _on_ctrl_c(self, _event):
            widget = self.root.focus_get()
            if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
                return None  # let the native copy happen
            if self.current_stages:
                self._copy_all()
            return "break"

        def _on_close(self):
            try:
                self.cfg["geometry"] = self.root.winfo_geometry()
                save_config(self.cfg)
            finally:
                self.root.destroy()

    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


def main(hook=None):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Dieses Programm benötigt Python mit Tkinter "
              "(im Installer von python.org standardmäßig enthalten).")
        return 1
    _run_ui(hook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
