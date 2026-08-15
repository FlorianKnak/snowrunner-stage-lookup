"""Tests for stage_lookup: parser fixtures, zip-fixture indexing, cache, config.

Run:  python -m unittest test_stage_lookup -v
No game files needed.
"""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

import stage_lookup as sl


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

TWO_STATE = b"""<?xml version="1.0" encoding="utf-8"?>
<ModelBrand DynamicModel="true">
    <PhysicsModel><Body Collisions="Dynamic" ModelFrame="base" /></PhysicsModel>
    <Subset Name="build_stage_0" IsDefault="true"><Mesh Name="base" /></Subset>
    <Subset Name="build_stage_1"><Mesh Name="stage_1" /></Subset>
    <AnimSubset Name="build_animation_0"><Mesh Name="base" /></AnimSubset>
</ModelBrand>
"""

THREE_STATE = b"""<ModelBrand>
    <Subset Name="build_stage_0" />
    <Subset Name="build_stage_1" />
    <Subset Name="build_stage_complete" />
</ModelBrand>
"""

SMOKE_CUBE = b"""<ModelBrand>
    <Subset Name="stage_hidden" IsDefault="true" />
    <Subset Name="stage_visible" />
</ModelBrand>
"""

DUPLICATES = b"""<ModelBrand>
    <Subset Name="build_stage_0" />
    <Group><Subset Name="build_stage_1" /></Group>
    <Subset Name="build_stage_0" />
    <Subset Name="build_stage_1" />
</ModelBrand>
"""

MALFORMED = b"""<ModelBrand>
    <Subset Name="build_stage_0" IsDefault="true">
    <Subset Name='build_stage_1'>
    <Mesh Name="stage_1" & unescaped>
</ModelBrand
"""

NO_SUBSETS = b"""<ModelBrand><Mesh Name="base" /></ModelBrand>"""

# Real archives contain files with two top-level elements like this one.
MULTI_ROOT = b"""<_parent File="rocket_broken_01_objective" />
<ModelBrand>
    <!--<Landmark Mesh="models/_missing_model" />-->
</ModelBrand>
"""

MULTI_ROOT_WITH_STAGES = b"""<_parent File="base_model" />
<ModelBrand>
    <Subset Name="state_start" />
    <Subset Name="state_end" />
</ModelBrand>
"""

PARENT_MODEL = b"""<ModelBrand>
    <Subset Name="state_start" />
    <Subset Name="state_end" />
</ModelBrand>
"""


class TestExtractStages(unittest.TestCase):
    def test_two_state_model(self):
        self.assertEqual(sl.extract_stages(TWO_STATE), ["build_stage_0", "build_stage_1"])

    def test_ignores_animsubset(self):
        self.assertNotIn("build_animation_0", sl.extract_stages(TWO_STATE))

    def test_three_state_with_complete(self):
        self.assertEqual(
            sl.extract_stages(THREE_STATE),
            ["build_stage_0", "build_stage_1", "build_stage_complete"],
        )

    def test_smoke_cube_names_kept_in_document_order(self):
        self.assertEqual(sl.extract_stages(SMOKE_CUBE), ["stage_hidden", "stage_visible"])

    def test_duplicates_dropped_order_preserved(self):
        self.assertEqual(sl.extract_stages(DUPLICATES), ["build_stage_0", "build_stage_1"])

    def test_nested_subset_at_any_depth(self):
        xml = b"<A><B><C><Subset Name='deep_stage'/></C></B></A>"
        self.assertEqual(sl.extract_stages(xml), ["deep_stage"])

    def test_malformed_file_hits_regex_fallback(self):
        self.assertEqual(sl.extract_stages(MALFORMED), ["build_stage_0", "build_stage_1"])

    def test_zero_subsets_is_empty_not_error(self):
        self.assertEqual(sl.extract_stages(NO_SUBSETS), [])

    def test_unparseable_and_no_subsets_raises(self):
        with self.assertRaises(sl.ParseError):
            sl.extract_stages(b"\x00\x01 not xml at all <<<")

    def test_names_returned_verbatim(self):
        xml = b'<M><Subset Name=" Build_Stage_0 " /><Subset Name="BUILD_stage_1"/></M>'
        self.assertEqual(sl.extract_stages(xml), [" Build_Stage_0 ", "BUILD_stage_1"])

    def test_utf8_bom(self):
        self.assertEqual(
            sl.extract_stages(b"\xef\xbb\xbf" + THREE_STATE)[0], "build_stage_0"
        )

    def test_latin1_fallback(self):
        xml = '<M><!-- caf\xe9 --><Subset Name="build_stage_0" /></M>'.encode("latin-1")
        self.assertEqual(sl.extract_stages(xml), ["build_stage_0"])

    def test_namespaced_document(self):
        xml = b'<M xmlns="urn:sr"><Subset Name="build_stage_0" /></M>'
        self.assertEqual(sl.extract_stages(xml), ["build_stage_0"])

    def test_multi_root_document_parses_as_empty_not_error(self):
        self.assertEqual(sl.extract_stages(MULTI_ROOT), [])

    def test_multi_root_document_with_stages(self):
        self.assertEqual(sl.extract_stages(MULTI_ROOT_WITH_STAGES),
                         ["state_start", "state_end"])


class TestParentModelName(unittest.TestCase):
    def test_reads_parent_file_attribute(self):
        self.assertEqual(sl.parent_model_name(MULTI_ROOT), "rocket_broken_01_objective")

    def test_strips_path_extension_and_case(self):
        xml = b'<_parent File="models\\\\Base_Model.xml" /><ModelBrand />'
        self.assertEqual(sl.parent_model_name(xml), "base_model")

    def test_none_when_absent(self):
        self.assertIsNone(sl.parent_model_name(TWO_STATE))


# --------------------------------------------------------------------------
# pak indexing against a synthetic archive
# --------------------------------------------------------------------------

FIXTURE_ENTRIES = {
    "[media]/classes/models/bridge_wooden_big_02_objective.xml": TWO_STATE,
    "[media]/classes/models/constr_wood_01_objective.xml": THREE_STATE,
    "[media]/_dlc/us_03/classes/models/constr_wood_01_objective.xml": SMOKE_CUBE,
    "[media]/_dlc/ru_08/classes/models/Smoke_Cube_01_Objective.xml": SMOKE_CUBE,
    "[media]\\_dlc\\dlc_11\\classes\\models\\backslash_model_objective.xml": THREE_STATE,
    "[media]/classes/models/plain_tree_01.xml": NO_SUBSETS,
    # Real archives have both of these shapes: "_objective" in the middle of the
    # name, and a staged model with no "objective" in the name at all.
    "[media]/_dlc/us_07/classes/models/conveyor_objective_01.xml": SMOKE_CUBE,
    "[media]/_dlc/us_07/classes/models/concrete_block_01_us_07.xml": SMOKE_CUBE,
    "[media]/classes/models/base_model.xml": PARENT_MODEL,
    "[media]/_dlc/ru_04/classes/models/child_no_stages_objective.xml":
        b'<_parent File="base_model" />\n<ModelBrand />\n',
    "[media]/classes/models/orphan_child_objective.xml":
        b'<_parent File="model_that_does_not_exist" />\n<ModelBrand />\n',
    "[media]/classes/models/cycle_a_objective.xml":
        b'<_parent File="cycle_b_objective" />\n<ModelBrand />\n',
    "[media]/classes/models/cycle_b_objective.xml":
        b'<_parent File="cycle_a_objective" />\n<ModelBrand />\n',
    "[media]/classes/trucks/truck_01.xml": TWO_STATE,
    "[media]/classes/models/readme.txt": b"not xml",
}


def make_fixture_pak(directory):
    root = Path(directory) / "SnowRunner"
    pak = root / sl.PAK_SUBPATH
    pak.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pak, "w") as zf:
        for name, data in FIXTURE_ENTRIES.items():
            zf.writestr(name, data)
    return root, pak


class TestPak(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root, self.pak = make_fixture_pak(self.tmp.name)
        self.index = sl.build_index(self.pak)
        self.paths = self.index["paths"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_pak_resolves_subpath(self):
        self.assertEqual(sl.find_pak(self.root), self.pak)

    def test_find_pak_accepts_the_file_itself(self):
        self.assertEqual(sl.find_pak(self.pak), self.pak)

    def test_find_pak_missing_names_expected_path(self):
        with self.assertRaises(sl.PakError) as ctx:
            sl.find_pak(Path(self.tmp.name) / "nope")
        self.assertIn("initial.pak", str(ctx.exception))

    def test_find_pak_empty_root(self):
        with self.assertRaises(sl.PakError):
            sl.find_pak("")

    def test_only_model_xmls_indexed(self):
        self.assertIn("bridge_wooden_big_02_objective", self.paths)
        self.assertNotIn("truck_01", self.paths)      # not under classes/models
        self.assertNotIn("readme", self.paths)        # not .xml

    def test_keys_are_lowercased_stems(self):
        self.assertIn("smoke_cube_01_objective", self.paths)

    def test_backslash_paths_indexed(self):
        self.assertIn("backslash_model_objective", self.paths)

    def test_name_collision_keeps_both_sources(self):
        paths = self.paths["constr_wood_01_objective"]
        self.assertEqual(len(paths), 2)
        self.assertTrue(any("_dlc/us_03" in p for p in paths))
        self.assertTrue(any(p == "[media]/classes/models/constr_wood_01_objective.xml"
                            for p in paths))

    def test_original_archive_path_is_readable_back(self):
        for paths in self.paths.values():
            for path in paths:
                self.assertIsInstance(sl.read_model_xml(self.pak, path), bytes)

    def test_dlc_and_base_copies_differ(self):
        base, dlc = sorted(self.paths["constr_wood_01_objective"], key=len)
        self.assertEqual(sl.extract_stages(sl.read_model_xml(self.pak, base)),
                         ["build_stage_0", "build_stage_1", "build_stage_complete"])
        self.assertEqual(sl.extract_stages(sl.read_model_xml(self.pak, dlc)),
                         ["stage_hidden", "stage_visible"])

    def test_subsets_recorded_per_archive_path(self):
        subsets = self.index["subsets"]
        self.assertEqual(
            subsets["[media]/classes/models/bridge_wooden_big_02_objective.xml"],
            ["build_stage_0", "build_stage_1"],
        )
        self.assertEqual(
            subsets["[media]/_dlc/us_03/classes/models/constr_wood_01_objective.xml"],
            ["stage_hidden", "stage_visible"],
        )
        self.assertEqual(subsets["[media]/classes/models/plain_tree_01.xml"], [])

    def test_parents_recorded_per_archive_path(self):
        parents = self.index["parents"]
        self.assertEqual(
            parents["[media]/_dlc/ru_04/classes/models/child_no_stages_objective.xml"],
            "base_model",
        )
        self.assertIsNone(parents["[media]/classes/models/plain_tree_01.xml"])

    def test_progress_callback_reaches_total(self):
        seen = []
        sl.build_index(self.pak, lambda done, total: seen.append((done, total)))
        self.assertTrue(seen)
        self.assertEqual(seen[-1][0], seen[-1][1])

    def test_read_missing_member_raises_pak_error(self):
        with self.assertRaises(sl.PakError):
            sl.read_model_xml(self.pak, "[media]/classes/models/ghost.xml")

    def test_bad_zip_raises_pak_error(self):
        broken = Path(self.tmp.name) / "broken.pak"
        broken.write_bytes(b"definitely not a zip")
        with self.assertRaises(sl.PakError):
            sl.build_index(broken)


# --------------------------------------------------------------------------
# config + cache (redirected to a temp config dir)
# --------------------------------------------------------------------------


class TestModelsWithStates(unittest.TestCase):
    """The usable-model filter is driven by <Subset> tags, not by filename."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root, self.pak = make_fixture_pak(self.tmp.name)
        self.states = sl.models_with_states(sl.build_index(self.pak))

    def tearDown(self):
        self.tmp.cleanup()

    def test_model_with_own_subsets_included(self):
        self.assertIn("bridge_wooden_big_02_objective", self.states)

    def test_staged_model_without_objective_in_name_included(self):
        self.assertIn("base_model", self.states)
        self.assertIn("concrete_block_01_us_07", self.states)

    def test_objective_in_the_middle_of_the_name_included(self):
        self.assertIn("conveyor_objective_01", self.states)

    def test_inherited_states_included(self):
        self.assertIn("child_no_stages_objective", self.states)

    def test_model_without_subsets_excluded(self):
        self.assertNotIn("plain_tree_01", self.states)

    def test_objective_named_model_without_states_excluded(self):
        self.assertNotIn("orphan_child_objective", self.states)
        self.assertNotIn("cycle_a_objective", self.states)

    def test_agrees_with_stages_for(self):
        index = sl.build_index(self.pak)
        for model, paths in index["paths"].items():
            found = any(sl.stages_for(self.pak, index, p)[0] for p in paths)
            self.assertEqual(found, model in self.states, model)


class TestStagesFor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root, self.pak = make_fixture_pak(self.tmp.name)
        self.index = sl.build_index(self.pak)

    def tearDown(self):
        self.tmp.cleanup()

    def _stages_for(self, model):
        return sl.stages_for(self.pak, self.index, self.index["paths"][model][0])

    def test_own_stages_report_no_inheritance(self):
        stages, origin, chain = self._stages_for("bridge_wooden_big_02_objective")
        self.assertEqual(stages, ["build_stage_0", "build_stage_1"])
        self.assertEqual(origin, "[media]/classes/models/bridge_wooden_big_02_objective.xml")
        self.assertEqual(chain, [])

    def test_inherited_stages_report_the_parent_and_its_path(self):
        stages, origin, chain = self._stages_for("child_no_stages_objective")
        self.assertEqual(stages, ["state_start", "state_end"])
        self.assertEqual(origin, "[media]/classes/models/base_model.xml")
        self.assertEqual(chain, ["base_model"])

    def test_missing_parent_yields_no_stages(self):
        stages, _origin, chain = self._stages_for("orphan_child_objective")
        self.assertEqual(stages, [])
        self.assertEqual(chain, [])

    def test_parent_cycle_terminates(self):
        stages, _origin, _chain = self._stages_for("cycle_a_objective")
        self.assertEqual(stages, [])

    def test_model_with_no_subsets_and_no_parent(self):
        stages, _origin, chain = sl.stages_for(
            self.pak, self.index, "[media]/classes/models/plain_tree_01.xml"
        )
        self.assertEqual((stages, chain), ([], []))


class TestConfigAndCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = sl.config_dir
        sl.config_dir = lambda: Path(self.tmp.name) / "cfg"
        self.root, self.pak = make_fixture_pak(self.tmp.name)

    def tearDown(self):
        sl.config_dir = self._orig
        self.tmp.cleanup()

    def test_config_roundtrip(self):
        cfg = sl.load_config()
        self.assertEqual(cfg["game_root"], "")
        cfg["game_root"] = str(self.root)
        cfg["show_stateless_models"] = True
        self.assertTrue(sl.save_config(cfg))
        self.assertEqual(sl.load_config()["game_root"], str(self.root))
        self.assertTrue(sl.load_config()["show_stateless_models"])

    def test_corrupt_config_falls_back_to_defaults(self):
        sl.config_dir().mkdir(parents=True, exist_ok=True)
        sl.config_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(sl.load_config(), sl.DEFAULT_CONFIG)

    def test_cache_roundtrip(self):
        index = sl.build_index(self.pak)
        self.assertTrue(sl.save_cache(self.pak, index))
        self.assertEqual(sl.load_cache(self.pak), index)

    def test_cache_invalidated_when_archive_changes(self):
        sl.save_cache(self.pak, sl.build_index(self.pak))
        stat = self.pak.stat()
        os.utime(self.pak, (stat.st_atime, stat.st_mtime + 120))
        self.assertIsNone(sl.load_cache(self.pak))

    def test_cache_invalidated_for_a_different_archive(self):
        sl.save_cache(self.pak, sl.build_index(self.pak))
        other_root, other_pak = make_fixture_pak(Path(self.tmp.name) / "other")
        self.assertIsNone(sl.load_cache(other_pak))

    def test_corrupt_cache_rebuilds_silently(self):
        sl.config_dir().mkdir(parents=True, exist_ok=True)
        sl.cache_path().write_text("[[[", encoding="utf-8")
        self.assertIsNone(sl.load_cache(self.pak))

    def test_cache_with_wrong_shape_is_rejected(self):
        sl.config_dir().mkdir(parents=True, exist_ok=True)
        payload = sl._pak_stamp(self.pak)
        payload["index"] = "not a dict"
        sl.cache_path().write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(sl.load_cache(self.pak))

    def test_cache_from_an_older_index_layout_is_rejected(self):
        """A v1 cache was name -> [paths] with no subset data; it must rebuild."""
        sl.config_dir().mkdir(parents=True, exist_ok=True)
        payload = sl._pak_stamp(self.pak)
        payload["index"] = {"plain_tree_01": ["[media]/classes/models/plain_tree_01.xml"]}
        sl.cache_path().write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(sl.load_cache(self.pak))

    def test_missing_cache_returns_none(self):
        self.assertIsNone(sl.load_cache(self.pak))


class TestAutodetect(unittest.TestCase):
    def test_candidates_include_steam_epic_and_drives_d_to_h(self):
        candidates = [str(p).lower() for p in sl.candidate_game_roots()]
        joined = "\n".join(candidates)
        self.assertIn("steamapps", joined)
        self.assertIn("epic games", joined)
        if os.name == "nt":
            for drive in "defgh":
                self.assertTrue(any(c.startswith(drive + ":") for c in candidates))

    def test_autodetect_returns_only_real_installs(self):
        for hit in sl.autodetect_game_roots():
            self.assertTrue((Path(hit) / sl.PAK_SUBPATH).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
