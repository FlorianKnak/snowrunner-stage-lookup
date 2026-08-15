# SnowRunner Baustufen-Suche

Modellnamen eintippen und die exakten **Statusnamen der Baustufen** erhalten —
also genau die Zeichenketten, die in der `stagesProgress`-Liste in den *Model
Building Settings* des Editors stehen müssen.

Kein Öffnen von `initial.pak` in 7-Zip mehr, kein Durchsuchen von
`[media]\classes\models\` und einem Dutzend `_dlc`-Unterordnern, kein manuelles
Auslesen von `<Subset>`-Tags.

---

## Download

**`snowrunner_helper.exe`** aus dem
[neuesten Release](../../releases/latest) herunterladen. Eine einzige Datei,
kein Installer, kein Python nötig. Irgendwo hinlegen und doppelklicken.

> **Windows warnt beim ersten Start.** Die EXE ist nicht signiert, deshalb zeigt
> SmartScreen *„Der Computer wurde durch Windows geschützt“*. Auf **Weitere
> Informationen** → **Trotzdem ausführen** klicken. Wer das nicht möchte, kann
> das Programm stattdessen aus dem Quellcode starten (siehe unten).

## Bedienung

1. **Beim ersten Start** wird nach dem SnowRunner-Ordner gefragt — dem Ordner,
   der `en_us` enthält. Steam- und Epic-Installationen werden automatisch
   gesucht, meist muss man den Fund nur bestätigen.
2. Das Archiv wird einmal indiziert (unter einer Sekunde) und zwischengespeichert.
3. Einen Teil des Modellnamens eintippen. Auf ein Ergebnis klicken.
4. Auf einen Statusnamen klicken, um ihn zu kopieren, oder **Alle kopieren** für
   die komplette Liste. `Strg+C` kopiert ebenfalls alle, `Esc` leert die Suche.

Statusnamen werden **exakt** so kopiert, wie sie in den Spieldateien stehen —
niemals umbenannt, umformatiert oder „bereinigt“. Der Editor braucht sie
wortwörtlich; ein Tippfehler zerstört die Bau-Animation stillschweigend.

Kommt ein Modell sowohl im Grundspiel als auch in einem DLC vor, erscheint ein
Auswahlfeld, denn die Statusnamen können sich zwischen den Fassungen
unterscheiden.

## Was in der Liste erscheint

Standardmäßig zeigt die Liste nur Modelle, die **tatsächlich Status definieren** —
im aktuellen Build sind das 308 Stück.

Bewusst wird dabei **nicht** nach der Namensendung `_objective` gefiltert. Das
wäre der naheliegende Weg und er ist falsch. Gemessen am ausgelieferten Archiv:

- 30 nutzbare Modelle tragen `_objective` *mitten* im Namen
  (`conveyor_objective_01`, `cube_objective_09`,
  `rus_controlbunker_02_1_part_objectives`).
- 9 weitere haben überhaupt kein „objective“ im Namen, definieren aber echte
  Baustufen — `concrete_block_01_us_07`, `tatra_steamshop`,
  `railway_switch_01_ru17`, `race_scene_us07`, `rus_launchpad_hangar_01_doors`
  und andere.
- Umgekehrt heißt `rock_03_rus_objective` zwar so, definiert aber keinen Status.

Ein Filter über den Dateinamen versteckt also 39 nutzbare Modelle und bietet
eines an, das nicht funktioniert. Dieses Programm liest stattdessen die
`<Subset>`-Tags und folgt der Vererbung über `<_parent>`, sodass Modelle wie
`rocket_broken_02_objective` weiterhin die geerbten Status anzeigen.

Mit dem Häkchen **„Auch Modelle ohne Status anzeigen“** lassen sich alle 4.740
Modellklassen durchsuchen.

## Vorkommende Statusnamen

Die Benennung ist zwischen den Modellen **nicht** einheitlich — genau deshalb
gibt es dieses Programm. Was im Spiel vorkommt:

| Familie | Beispiele |
| --- | --- |
| Baustufen | `build_stage_0`, `build_stage_1`, `build_stage_2`, `build_stage_complete` |
| Start/Ende (größte Gruppe) | `state_start`, `state_end`, `state_fin`, `state_done` |
| Nummerierte Status | `state_00`–`state_02`, `stage_00`–`stage_03` |
| Rauchwürfel | `stage_visible`, `stage_hidden` |
| Tore | `stage_opened`, `stage_closed` |
| Einzelfälle | `cargo_carriage`, `empty_carriage`, `hide_cargo_carriage` |

Niemals raten. Immer nachschlagen.

## Woher die Daten kommen

Aus `initial.pak` in der Installation:

```
<Spiel>\en_us\preload\paks\client\initial.pak
```

Das ist ein gewöhnliches ZIP-Archiv (~28 MB — Klassen-XMLs, keine Assets) und
das **einzige** Pak, das `classes/models/*.xml` enthält. `shared.pak` enthält
Meshes, `editor.pak` Prebuild-Daten und Texturen, die `level_*.pak`-Dateien
Szenen und Texturen. Wenn jemand behauptet, es gäbe noch ein weiteres Pak oder
einen weiteren Ordner mit zusätzlichen Objective-Objekten: gibt es nicht. Sehr
wahrscheinlich sieht diese Person Modelle, die ein namensbasierter Filter
versteckt hat.

**Das Programm arbeitet ausschließlich lesend.** Es schreibt niemals in
`initial.pak` oder sonst etwas im Spielordner. Geschrieben werden nur die eigene
Konfiguration und der Index-Cache unter
`%APPDATA%\snowrunner-stage-lookup\`.

Der Cache ist an Größe und Änderungsdatum des Archivs gekoppelt, ein
Spiel-Update löst also automatisch einen Neuaufbau aus. Die Schaltfläche
**Index neu aufbauen** erzwingt ihn manuell.

## Aus dem Quellcode starten

Benötigt Python 3.9+ mit Tkinter (beides im Installer von python.org enthalten).
Keine Pakete von Drittanbietern.

```
python stage_lookup.py
```

Die Tests laufen gegen ein synthetisches Archiv und brauchen keine Spieldateien:

```
python -m unittest test_stage_lookup -v
```

Die EXE selbst bauen:

```
pip install pyinstaller
pyinstaller --onefile --windowed --name snowrunner_helper stage_lookup.py
```

## Hinweise

Die Oberfläche ist deutsch. Quellcode, Kommentare und die Entwicklerdokumentation
(`CLAUDE.md`, `PROMPT.md`) sind englisch. Statusnamen aus dem Spiel werden
grundsätzlich nicht übersetzt — sie sind Daten.

Nicht mit Saber Interactive oder Focus Entertainment verbunden. SnowRunner ist
deren Marke. Dieses Programm liefert keinerlei Spielinhalte mit — es liest nur
die Dateien, die ohnehin schon auf der Festplatte liegen.

Veröffentlicht unter der [MIT-Lizenz](LICENSE).
