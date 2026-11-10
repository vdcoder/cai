import json

from tests.helpers import WorkspaceCase

ORDERED = """\
VALUE = 0
# #defer value
# decide the real value
# #end

# #run before
# import m
# print("before", m.VALUE, hasattr(m, "REAL"))
# #end

# #evolve value
# REAL = 42
# #end

# #run after
# import m
# print("after", m.REAL)
# #end
"""


def by_name(report, kind="runs"):
    return {r["name"]: r for r in report[kind]}


class RunTests(WorkspaceCase):
    def test_source_order_checkpoints(self):
        self.write("src/m.py", ORDERED)
        code, rep = self.cai("--run")
        self.assertEqual(code, 0)
        runs = by_name(rep)
        self.assertEqual(list(runs), ["before", "after"])
        self.assertEqual(runs["before"]["stdout"], "before 0 False\n")
        self.assertEqual(runs["after"]["stdout"], "after 42\n")
        self.assertEqual((runs["before"]["checkpoint"], runs["after"]["checkpoint"]), (1, 2))
        self.assertEqual(rep["checkpoints"], 2)
        self.assertEqual(self.read("src/m.py"), "VALUE = 0\nREAL = 42\n")  # runs are consumed

    def test_result_shape(self):
        self.write("src/m.py", "# #run allocation_probe\n# print('allocation probe')\n# #end\n")
        _, rep = self.cai("--run")
        r = rep["runs"][0]
        self.assertEqual({k: r[k] for k in ("name", "status", "exit_code", "stdout", "stderr", "checkpoint")},
                         {"name": "allocation_probe", "status": "passed", "exit_code": 0,
                          "stdout": "allocation probe\n", "stderr": "", "checkpoint": 0})
        self.assertIsInstance(r["duration_ms"], float)

    def test_three_sequential_checkpoints_across_files(self):
        self.write("src/a.py", "# #defer one\n# #end\n# #run r0\n# import a, b; print(sorted(set(dir(a)+dir(b)) & {'A','B'}))\n# #end\n"
                   "# #evolve one\n# A = 1\n# #end\n# #run r1\n# import a, b; print(sorted(set(dir(a)+dir(b)) & {'A','B'}))\n# #end\n")
        self.write("src/b.py", "# #defer two\n# #end\n# #evolve two\n# B = 2\n# #end\n"
                   "# #run r2\n# import a, b; print(sorted(set(dir(a)+dir(b)) & {'A','B'}))\n# #end\n")
        code, rep = self.cai("--run")
        self.assertEqual(code, 0, rep)
        self.assertEqual([(r["name"], r["stdout"].strip()) for r in rep["runs"]],
                         [("r0", "[]"), ("r1", "['A']"), ("r2", "['A', 'B']")])

    def test_runner_receives_protocol(self):
        self.write("src/m.py", "x = 1\n# #run probe\n# import os, json, sys\n"
                   "# meta = json.load(open(os.environ['CAI_META_FILE']))\n"
                   "# print(os.environ['CAI_KIND'], os.environ['CAI_NAME'], os.environ['CAI_SOURCE_FILE'],\n"
                   "#       os.environ['CAI_SOURCE_LINE'], os.environ['CAI_CHECKPOINT'], meta['name'])\n"
                   "# print(os.path.samefile(os.getcwd(), os.environ['CAI_SNAPSHOT_DIR']))\n"
                   "# print(open(os.environ['CAI_BODY_FILE']).read() == open('src/m.py').read())\n"
                   "# print(os.path.exists('.cai'), '#run' in open('src/m.py').read())\n# #end\n")
        _, rep = self.cai("--run")
        self.assertEqual(rep["runs"][0]["stdout"], "run probe src/m.py 2 0 probe\nTrue\nFalse\nFalse False\n")

    def test_snapshot_is_isolated_from_workspace(self):
        self.write("src/m.py", "# #run vandal\n# open('src/m.py', 'w').write('ruined')\n# open('new.txt', 'w').write('x')\n# #end\nKEEP = 1\n")
        code, _ = self.cai("--run")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("src/m.py"), "KEEP = 1\n")
        self.assertFalse((self.root / "new.txt").exists())

    def test_failed_experiment_still_consolidates(self):
        self.write("src/m.py", "# #run boom\n# import sys\n# print('partial'); sys.exit(3)\n# #end\n"
                   "# #run fine\n# print('ok')\n# #end\nX = 1\n")
        code, rep = self.cai("--run")
        runs = by_name(rep)
        self.assertEqual(code, 1)
        self.assertEqual((runs["boom"]["status"], runs["boom"]["exit_code"], runs["boom"]["stdout"]),
                         ("failed", 3, "partial\n"))
        self.assertEqual(runs["fine"]["status"], "passed")
        self.assertEqual(self.read("src/m.py"), "X = 1\n")
        self.assertEqual(self.cai("--run")[0], 0)  # consumed: nothing to repeat

    def test_timeout(self):
        self.config(runner={"timeout_seconds": 0.5})
        self.write("src/m.py", "# #run slow\n# import time\n# print('start', flush=True)\n# time.sleep(30)\n# #end\n")
        code, rep = self.cai("--run")
        r = rep["runs"][0]
        self.assertEqual((code, r["status"], r["exit_code"], r["stdout"]), (1, "timeout", None, "start\n"))
        self.assertLess(r["duration_ms"], 10000)

    def test_launch_failure(self):
        self.config(runner={"run_command": ["definitely-not-a-real-binary-cai"]})
        self.write("src/m.py", "# #run r\n# pass\n# #end\n")
        code, rep = self.cai("--run")
        self.assertEqual((code, rep["runs"][0]["status"]), (1, "launch_error"))
        self.assertIn("failed to launch", rep["runs"][0]["stderr"])

    def test_output_limit(self):
        self.config(runner={"max_output_bytes": 100})
        self.write("src/m.py", "# #run loud\n# import sys\n# print('x' * 100000)\n# sys.stderr.write('e' * 50)\n# #end\n")
        _, rep = self.cai("--run")
        r = rep["runs"][0]
        self.assertEqual((r["status"], len(r["stdout"]), r["stdout_truncated"], r["stderr_truncated"]),
                         ("passed", 100, True, False))

    def test_body_is_never_shell_interpolated(self):
        self.write("src/m.py", "# #run inj\n# print('$(echo pwned) `id` ; rm -rf / && {python} %s')\n# #end\n")
        _, rep = self.cai("--run")
        self.assertEqual(rep["runs"][0]["stdout"], "$(echo pwned) `id` ; rm -rf / && {python} %s\n")

    def test_validation_error_skips_runs(self):
        text = "# #run r\n# print(1)\n# #end\n# #evolve ghost\n# x\n# #end\n"
        self.write("src/m.py", text)
        code, rep = self.cai("--run")
        self.assertEqual((code, rep["runs"][0]["status"]), (2, "skipped"))
        self.assertEqual(self.read("src/m.py"), text)

    def test_missing_run_command(self):
        (self.root / "cai.json").write_text(json.dumps({"version": 1, "project": {"include": [
            {"pattern": "src/**/*.py", "style": "python_comment"}]}}))
        text = "# #run r\n# print(1)\n# #end\n"
        self.write("src/m.py", text)
        code, rep = self.cai("--run")
        self.assertEqual((code, self.codes(rep)), (3, ["E101"]))
        self.assertEqual(self.read("src/m.py"), text)


class PendingRunTests(WorkspaceCase):
    def test_evolve_pending_run_before_execution(self):
        self.write("src/m.py", "# #run r\n# print('old')\n# #end\n# #wait\n# hmm\n# #end\n# #evolve r\n# print('new')\n# #end\n")
        _, rep = self.cai("--run")
        self.assertEqual([r["stdout"] for r in rep["runs"]], ["new\n"])

    def test_evolve_run_after_checkpoint_is_rejected(self):
        self.write("src/m.py", "# #defer d\n# #end\n# #run r\n# print('old')\n# #end\n"
                   "# #evolve d\n# D = 1\n# #end\n# #evolve r\n# print('new')\n# #end\n")
        code, rep = self.cai("--run")
        self.assertEqual((code, self.codes(rep)), (2, ["E304"]))
        self.assertIn("src/m.py:6", rep["diagnostics"][0]["message"])

    def test_drop_pending_run(self):
        self.write("src/m.py", "# #run r\n# print('never')\n# #end\n# #drop r\n# #end\nX = 1\n")
        code, rep = self.cai("--run")
        self.assertEqual((code, rep["runs"], self.read("src/m.py")), (0, [], "X = 1\n"))

    def test_build_keeps_runs_pending(self):
        self.write("src/m.py", "# #wait\n# x\n# #end\n# #run r\n# print('later')\n# #end\n# #evolve r\n# print('evolved')\n# #end\n")
        code, rep = self.cai("--build")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("src/m.py"), "# #run r\n# print('evolved')\n# #end\n")
        self.assertEqual([b["name"] for b in rep["pending"]["runs"]], ["r"])
        self.assertNotIn("runs", rep)
        _, rep = self.cai("--run")
        self.assertEqual(rep["runs"][0]["stdout"], "evolved\n")
        self.assertEqual(self.read("src/m.py"), "")

    def test_build_discard_runs(self):
        self.write("src/m.py", "X = 1\n# #run r\n# print('later')\n# #end\n")
        self.cai("--build", "--discard-runs")
        self.assertEqual(self.read("src/m.py"), "X = 1\n")

    def test_run_name_reusable_after_consumption_and_duplicates_rejected(self):
        self.write("src/m.py", "# #run r\n# print(1)\n# #end\n# #run r\n# print(2)\n# #end\n")
        self.assertEqual(self.codes(self.cai("--run")[1]), ["E303"])
        self.write("src/m.py", "# #run r\n# print(1)\n# #end\n")
        self.cai("--run")
        self.write("src/m.py", "# #run r\n# print(2)\n# #end\n")
        self.assertEqual(self.cai("--run")[1]["runs"][0]["stdout"], "2\n")

    def test_c_block_run(self):
        self.write("src/a.c", "int x;\n/* #run probe\n    print(open('src/a.c').read().strip())\n#end */\n")
        _, rep = self.cai("--run")
        self.assertEqual(rep["runs"][0]["stdout"], "int x;\n")
