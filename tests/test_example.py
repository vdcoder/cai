import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import WorkspaceCase

REPO = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(REPO / "src"))


def cli(root, *args):
    return subprocess.run([sys.executable, "-m", "cai", "--root", str(root), *args], env=ENV, capture_output=True, text=True)


class ExampleProjectTests(unittest.TestCase):
    def test_documented_demo_is_reproducible(self):
        tmp = Path(tempfile.mkdtemp(prefix="cai-demo-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        demo = tmp / "demo"
        shutil.copytree(REPO / "examples" / "demo", demo)
        check = cli(demo, "--check")
        self.assertEqual(check.returncode, 0, check.stdout)
        self.assertFalse((demo / ".cai").exists())
        out = cli(demo, "--run", "--test")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)  # empty_input fails by design
        for expected in ("[run] before: passed  exit=0", "median defined: False", "[run] after: passed",
                         "median([5, 1, 4, 2]) -> 3.0", "[run] empty_input: failed  exit=1",
                         "ValueError: median of an empty sequence", "runs: 2/3 passed",
                         "[test] mean_and_median: passed", "modified: src/metrics.py", "result: FAILED (exit 1)"):
            self.assertIn(expected, out.stdout)
        metrics = (demo / "src/metrics.py").read_text()
        self.assertIn("def median(values):", metrics)
        self.assertIn("# #test mean_and_median", metrics)
        for gone in ("#defer", "#wait", "#evolve", "#drop", "#run", "mode"):
            self.assertNotIn(gone, metrics)
        self.assertNotIn("#", (demo / "src/buffer.cpp").read_text().replace("#include", ""))
        self.assertEqual((demo / "docs/notes.md").read_text(),
                         "# Metrics notes\n\n`mean` and `median` raise `ValueError` for an empty sequence.\n")
        again = cli(demo, "--test")
        self.assertEqual(again.returncode, 0)
        self.assertNotIn("modified:", again.stdout)
        self.assertIn("invocations: 2", cli(demo, "--stats").stdout)


class CliBehaviourTests(WorkspaceCase):
    def test_usage_and_config_errors(self):
        self.assertEqual(cli(self.root).returncode, 3)
        self.assertEqual(cli(self.root, "--check", "--build").returncode, 3)
        (self.root / "cai.json").write_text("{not json")
        out = cli(self.root, "--check")
        self.assertEqual(out.returncode, 3)
        self.assertIn("E100", out.stdout)

    def test_human_readable_diagnostic(self):
        self.write("src/a.c", "int a;\n/* #evolve ghost\n#end */\n")
        out = cli(self.root, "--build")
        self.assertEqual(out.returncode, 2)
        self.assertIn("src/a.c:2: error E301 [#evolve ghost]: no active block named 'ghost'", out.stdout)

    @unittest.skipUnless(os.name == "posix", "POSIX signals")
    def test_interrupt_leaves_sources_and_lock_clean(self):
        text = "# #wait\n# x\n# #end\n# #run slow\n# import time\n# time.sleep(60)\n# #end\n"
        self.write("src/m.py", text)
        proc = subprocess.Popen([sys.executable, "-m", "cai", "--root", str(self.root), "--run"], env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1.5)
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(timeout=20), 130)
        proc.stdout.close(), proc.stderr.close()
        self.assertEqual(self.read("src/m.py"), text)
        self.assertFalse((self.root / ".cai/lock").exists())
        self.assertFalse((self.root / ".cai/txn").exists())
