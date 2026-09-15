"""Resumable depot install — the _goginstall_state.json marker."""
import os, sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class DepotState(unittest.TestCase):
    def test_roundtrip_same_build(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            app._write_depot_state(p, "build-1", {"a/b.bin", "c.exe"})
            self.assertEqual(app._read_depot_state(p, "build-1"), {"a/b.bin", "c.exe"})

    def test_build_mismatch_resets(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            app._write_depot_state(p, "build-1", {"a"})
            self.assertEqual(app._read_depot_state(p, "build-2"), set())

    def test_missing_state_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(app._read_depot_state(Path(d), "x"), set())

    def test_marker_written_up_front(self):
        # Regression (1.4.2): the marker must be creatable with an empty done-set
        # so an install interrupted before the first file completes is still seen
        # as 'in progress' (resumable) rather than 'finished'.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            app._write_depot_state(p, "b", set())
            self.assertTrue((p / app._DEPOT_STATE_NAME).exists())
            self.assertEqual(app._read_depot_state(p, "b"), set())


if __name__ == "__main__":
    unittest.main()
