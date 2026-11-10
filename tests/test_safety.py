import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tests.helpers import WorkspaceCase

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
A0 = "/* #wait\nx\n#end */\nint a;\n"
B0 = "int b;\n/* #wait\ny\n#end */\n"


class RecoveryTests(WorkspaceCase):
    def crash(self, point: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONPATH=SRC_DIR, CAI_FAULT_POINT=point)
        return subprocess.run([sys.executable, "-m", "cai", "--root", str(self.root), "--build", "--json"],
                              env=env, capture_output=True, text=True)

    def two_files(self):
        self.write("src/a.c", A0)
        self.write("src/b.c", B0)

    def test_interrupted_between_file_replacements_rolls_back(self):
        self.two_files()
        self.assertEqual(self.crash("before_replace:1").returncode, 97)
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), ("int a;\n", B0))  # torn state on disk
        self.assertTrue((self.root / ".cai/txn/journal.json").exists())
        code, rep = self.cai("--check")
        self.assertEqual((code, self.codes(rep)), (0, ["W520"]))
        self.assertEqual(self.read("src/a.c"), "int a;\n")  # --check never repairs
        (self.root / ".cai/lock").unlink()  # hard kill left the lock; here the pid is dead anyway
        code, rep = self.cai("--build")
        self.assertEqual(code, 0)
        self.assertEqual(self.codes(rep), ["W522"])
        self.assertEqual(rep["stats"]["recovery_operations"], 1)
        # rolled back, then the still-unprocessed directives were consolidated in the same invocation
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), ("int a;\n", "int b;\n"))
        self.assertFalse((self.root / ".cai/txn").exists())

    def test_interrupted_before_commit_point_restores_all_files(self):
        self.two_files()
        self.assertEqual(self.crash("before_commit").returncode, 97)
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), ("int a;\n", "int b;\n"))
        from cai import txn
        restored = txn.recover(self.root, self.root / ".cai")
        self.assertEqual(sorted(restored), ["src/a.c", "src/b.c"])
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), (A0, B0))

    def test_crash_after_commit_point_is_committed(self):
        self.two_files()
        self.assertEqual(self.crash("after_commit").returncode, 97)
        code, rep = self.cai("--build")
        self.assertEqual((code, rep["files_modified"], rep["stats"]["recovery_operations"]), (0, [], 0))
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), ("int a;\n", "int b;\n"))

    def test_stale_lock_of_dead_process_is_taken_over(self):
        self.two_files()
        self.crash("before_replace:0")
        self.assertTrue((self.root / ".cai/lock").exists())
        code, rep = self.cai("--build")
        if os.name == "posix":
            self.assertEqual(code, 0)
            self.assertIn("W521", self.codes(rep))
        else:
            self.assertEqual((code, self.codes(rep)), (4, ["E510"]))

    def test_live_lock_blocks_second_writer(self):
        self.two_files()
        (self.root / ".cai").mkdir()
        (self.root / ".cai/lock").write_text(str(os.getpid()))
        code, rep = self.cai("--build")
        self.assertEqual((code, self.codes(rep)), (4, ["E510"]))
        self.assertEqual(self.read("src/a.c"), A0)
        self.assertEqual(self.cai("--check")[0], 0)  # read-only check needs no lock

    def test_recovery_refuses_to_overwrite_external_edits(self):
        self.two_files()
        self.crash("before_replace:1")
        (self.root / ".cai/lock").unlink()
        self.write("src/a.c", "int edited_by_someone;\n")
        code, rep = self.cai("--build")
        self.assertEqual((code, self.codes(rep)), (4, ["E512"]))
        self.assertEqual(self.read("src/a.c"), "int edited_by_someone;\n")
        self.assertEqual((self.root / ".cai/txn/orig/00000").read_text(), A0)  # backup kept for manual repair

    def test_external_modification_during_invocation_aborts_commit(self):
        self.write("src/m.py", "# #run sneaky\n# import os\n# p = os.path.join(os.environ['CAI_WORKSPACE'], 'src', 'z.py')\n"
                   "# open(p, 'a').write('EXTERNAL = 1\\n')\n# #end\n")
        self.write("src/z.py", "# #wait\n# x\n# #end\nZ = 1\n")
        code, rep = self.cai("--run")
        self.assertEqual((code, self.codes(rep), rep["files_modified"]), (4, ["E511"], []))
        self.assertIn("#run sneaky", self.read("src/m.py"))  # all-or-nothing: m.py untouched too
        self.assertTrue(self.read("src/z.py").endswith("EXTERNAL = 1\n"))

    def test_failed_consolidation_then_repair(self):
        text = "/* #defer f\n#end */\n/* #evolve g\nint g;\n#end */\n"
        self.write("src/a.c", text)
        self.assertEqual(self.cai("--build")[0], 2)
        self.assertEqual(self.read("src/a.c"), text)
        self.write("src/a.c", text.replace("#evolve g", "#evolve f"))
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "int g;\n")

    def test_file_mode_is_preserved(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions")
        p = self.write("src/a.c", A0)
        p.chmod(0o750)
        self.cai("--build")
        self.assertEqual(p.stat().st_mode & 0o777, 0o750)


class StatsTests(WorkspaceCase):
    def test_records_and_summary(self):
        self.write("src/m.py", "# #defer d\n# #end\n# #wait\n# x\n# #end\n# #run ok\n# print(1)\n# #end\n"
                   "# #run bad\n# raise SystemExit(1)\n# #end\n# #evolve d\n# D = 1\n# #end\n"
                   "# #test t\n# import m; assert m.D == 1\n# #end\n")
        code, rep = self.cai("--run", "--test")
        self.assertEqual(code, 1)
        rec = json.loads((self.root / ".cai/stats.jsonl").read_text().splitlines()[-1])
        self.assertEqual(rec, rep["stats"])
        expect = {"mode": "run+test", "files_scanned": 1, "evolutions": 1, "drops": 0, "experiments": 2,
                  "experiment_failures": 1, "persistent_tests": 1, "tests_executed": 1, "test_failures": 0,
                  "transformation_errors": 0, "files_modified": 1, "checkpoints": 1, "recovery_operations": 0,
                  "directives": {"defer": 1, "wait": 1, "evolve": 1, "drop": 0, "run": 2, "test": 1}}
        self.assertEqual({k: rec[k] for k in expect}, expect)
        self.assertGreater(rec["bytes_read"], 0)
        self.assertEqual(rec["bytes_written"], len(self.read("src/m.py").encode()))
        for key in ("parse_ms", "transform_ms", "runner_ms", "total_ms"):
            self.assertGreaterEqual(rec[key], 0)
        self.cai("--build")
        self.cai("--check")  # not recorded
        code, summary = self.cai("--stats")
        self.assertEqual((code, summary["invocations"], summary["by_mode"]), (0, 2, {"run+test": 1, "build": 1}))
        self.assertEqual(summary["totals"]["experiments"], 2)
        self.assertEqual(json.loads((self.root / ".cai/last_report.json").read_text())["mode"], "build")

    def test_errors_are_counted_and_stats_location_is_configurable(self):
        self.config(stats={"path": "out/telemetry.jsonl"})
        self.write("src/a.c", "/* #drop ghost\n#end */\n")
        self.cai("--build")
        rec = json.loads((self.root / "out/telemetry.jsonl").read_text())
        self.assertEqual((rec["transformation_errors"], rec["exit_code"]), (1, 2))
        self.assertFalse((self.root / ".cai/stats.jsonl").exists())


class IncrementalScanTests(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.config(scan={"incremental": True})

    def age(self, rel):
        old = time.time() - 60
        os.utime(self.root / rel, (old, old))

    def test_clean_files_are_skipped_and_edits_are_seen(self):
        self.write("src/a.c", "int a;\n")
        self.write("src/b.c", "int b;\n/* #defer later\n#end */\n")
        self.age("src/a.c"), self.age("src/b.c")
        _, rep = self.cai("--build")
        self.assertEqual((rep["stats"]["files_scanned"], rep["stats"]["files_skipped"]), (2, 0))
        _, rep = self.cai("--build")
        self.assertEqual((rep["stats"]["files_scanned"], rep["stats"]["files_skipped"]), (1, 1))  # b.c has a directive
        _, rep = self.cai("--build", "--full-scan")
        self.assertEqual(rep["stats"]["files_skipped"], 0)
        self.write("src/a.c", "int a;\n/* #wait\nedited after being marked clean\n#end */\n")
        self.write("src/c.c", "/* #evolve later\nint later;\n#end */\n")
        code, rep = self.cai("--build")
        self.assertEqual((code, rep["files_modified"]), (0, ["src/a.c", "src/b.c", "src/c.c"]))
        self.assertEqual(self.read("src/b.c"), "int b;\nint later;\n")

    def test_recent_files_are_never_marked_clean(self):
        self.write("src/a.c", "int a;\n")
        self.cai("--build")
        _, rep = self.cai("--build")
        self.assertEqual(rep["stats"]["files_skipped"], 0)

    def test_interrupted_invocation_does_not_hide_directives(self):
        self.write("src/a.c", A0)
        self.age("src/a.c")
        env = dict(os.environ, PYTHONPATH=SRC_DIR, CAI_FAULT_POINT="before_replace:0")
        subprocess.run([sys.executable, "-m", "cai", "--root", str(self.root), "--build"], env=env, capture_output=True)
        (self.root / ".cai/lock").unlink(missing_ok=True)
        code, rep = self.cai("--build")
        self.assertEqual((code, rep["files_modified"]), (0, ["src/a.c"]))
