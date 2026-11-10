import contextlib
import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401

from cai_bench import analysis
from cai_bench.agents import CommandAgent, ReplayAgent
from cai_bench.challenge import CATEGORIES, ManifestError, load_challenge, load_suite, tree_digest
from cai_bench.cli import main as _bench_main
from cai_bench.conditions import CONDITIONS, build_prompt
from cai_bench.trace import TraceError, corrective_cycles, derive_metrics, empty_trace, validate
from cai_bench.trial import grade, run_matrix, run_trial

def bench_main(argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return _bench_main(argv)


SUITE = Path(__file__).resolve().parents[1] / "benchmarks" / "challenges"


def ev(kind, ok=None):
    return {"type": kind} if ok is None else {"type": kind, "ok": ok}


class TraceTests(unittest.TestCase):
    def test_corrective_cycle_definition(self):
        fail, ok, edit = ev("validation", False), ev("validation", True), ev("edit")
        self.assertEqual(corrective_cycles([edit, ok]), 0)                       # nothing failed
        self.assertEqual(corrective_cycles([fail, edit, ok]), 1)                 # fail -> revise -> resubmit
        self.assertEqual(corrective_cycles([fail, edit, edit, fail, edit, ok]), 2)
        self.assertEqual(corrective_cycles([fail, fail, ok]), 0)                 # re-running without an edit
        self.assertEqual(corrective_cycles([fail, edit]), 0)                     # never resubmitted
        self.assertEqual(corrective_cycles([ev("experiment", False), edit, ev("test", True)]), 1)  # same rule for CAI events

    def test_unavailable_metrics_are_none_not_zero(self):
        m = derive_metrics(empty_trace("x", synthetic=False, events=None))
        self.assertTrue(all(m[k] is None for k in ("input_tokens", "total_tokens", "tool_calls", "corrective_cycles")))
        trace = empty_trace("x", synthetic=False, events=[ev("turn"), ev("tool_call", False), {"type": "edit", "source_changes": 3}])
        trace["usage"].update(input_tokens=100, output_tokens=20)
        m = derive_metrics(trace)
        self.assertEqual((m["total_tokens"], m["agent_turns"], m["failed_tool_calls"], m["edit_operations"],
                          m["source_changes"], m["cache_read_tokens"]), (120, 1, 1, 1, 3, None))

    def test_validation(self):
        validate(empty_trace("x", synthetic=True, events=[]))
        for bad in ({}, {"schema_version": 1, "synthetic": "no", "agent": {}},
                    {"schema_version": 1, "synthetic": False, "agent": {}, "usage": {"input_tokens": -1}},
                    {"schema_version": 1, "synthetic": False, "agent": {}, "events": [{"type": "validation"}]},
                    {"schema_version": 1, "synthetic": False, "agent": {}, "events": [{"type": "magic"}]}):
            with self.assertRaises(TraceError):
                validate(bad)


class SuiteTests(unittest.TestCase):
    def test_ten_challenges_cover_required_categories(self):
        suite = load_suite(SUITE)
        self.assertGreaterEqual(len(suite), 10)
        self.assertEqual({c.category for c in suite}, set(CATEGORIES) - {"other"})
        for ch in suite:
            self.assertTrue(ch.replay.is_file() and ch.description and ch.success_criteria)
            self.assertNotIn("grader", [p.name for p in ch.fixture.iterdir()])

    def test_graders_reject_the_unsolved_fixture(self):
        for ch in load_suite(SUITE):
            if ch.missing_requirements():
                continue
            self.assertFalse(grade(ch, ch.fixture)["success"], ch.id)

    def test_manifest_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "c1"
            (d / "fixture" / "grader").mkdir(parents=True)
            base = {"schema_version": 1, "id": "c1", "title": "t", "category": "other", "description": "d",
                    "success_criteria": "s", "grader": {"dir": "fixture/grader", "command": ["x"]}}
            for patch in ({}, {"id": "other"}, {"category": "nope"}, {"schema_version": 9}):
                (d / "challenge.json").write_text(json.dumps({**base, **patch}))
                with self.assertRaises(ManifestError):  # first case: grader hidden inside the fixture
                    load_challenge(d)

    def test_prompts_differ_only_by_workflow_section(self):
        a, b, c = (build_prompt("Do X.", CONDITIONS[k]) for k in "ABC")
        self.assertEqual(a.split("# Workflow")[0], c.split("# Workflow")[0])
        self.assertIn("#evolve", c)
        self.assertNotIn("#evolve", a + b)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cai-bench-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_replay_matrix_is_isolated_ordered_and_synthetic(self):
        suite = load_suite(SUITE, ["py-small-function", "py-missing-target", "py-bug-repair"])
        before = {c.id: tree_digest(c.fixture) for c in suite}
        out = self.tmp / "r1"
        records = run_matrix(suite, ["A", "B", "C"], ReplayAgent(), out, repetitions=2, seed=5)
        self.assertEqual(len(records), 18)
        self.assertTrue(all(r["success"] and r["synthetic"] and r["status"] == "completed" for r in records))
        self.assertEqual(before, {c.id: tree_digest(c.fixture) for c in suite})  # fixtures untouched
        self.assertTrue(all(r["fixture_digest"] == before[r["challenge"]] for r in records))
        self.assertTrue(all(r["input_tokens"] is None and r["cost_usd"] is None for r in records))
        order = json.loads((out / "run.json").read_text())["order"]
        self.assertNotEqual(order, sorted(order))  # randomized
        records2 = run_matrix(suite, ["A", "B", "C"], ReplayAgent(), self.tmp / "r2", repetitions=2, seed=5)
        self.assertEqual([r["trial_id"] for r in records], [r["trial_id"] for r in records2])  # seed-reproducible
        with self.assertRaises(FileExistsError):
            run_matrix(suite, ["A"], ReplayAgent(), out, repetitions=1, seed=0)
        cell = {(r["challenge"], r["condition"]): r for r in records}
        self.assertEqual(cell["py-missing-target", "C"]["corrective_cycles"], 1)   # E301 -> fix -> pass
        self.assertEqual(cell["py-missing-target", "A"]["corrective_cycles"], 1)
        self.assertEqual(cell["py-bug-repair", "C"]["experiment_executions"], 1)
        self.assertEqual(cell["py-small-function", "A"]["experiment_executions"], 0)
        summary = analysis.write_reports(out)
        self.assertEqual(summary["evidence"], "synthetic")
        self.assertIn("SYNTHETIC HARNESS VALIDATION", (out / "report.md").read_text())
        self.assertEqual(summary["aggregate"]["C"]["all_attempts"]["total_tokens"]["n"], 0)
        rows = list(csv.DictReader((out / "trials.csv").read_text().splitlines()))
        self.assertEqual((len(rows), rows[0]["input_tokens"]), (18, ""))  # unavailable -> empty cell
        self.assertTrue((out / "summary.csv").read_text().startswith("scope,condition,evidence"))

    def fake_agent(self, body: str) -> CommandAgent:
        script = self.tmp / "agent.py"
        script.write_text(body)
        return CommandAgent({"adapter": "command", "argv": [sys.executable, str(script), "{trace_file}", "{prompt_file}"],
                             "provider": "test", "model": "fake-1", "model_version": "v0", "reasoning": "none"})

    def test_command_agent_with_and_without_trace(self):
        ch = load_challenge(SUITE / "py-small-function")
        solution = (ch.root / "replay_files/solution.py").read_text()
        writes = f"import sys, json\nopen('src/textutil.py', 'w').write({solution!r})\nassert 'slugify' in open(sys.argv[2]).read()\n"
        trace = {"schema_version": 1, "synthetic": False, "agent": {}, "usage": {"input_tokens": 900, "output_tokens": 100, "cost_usd": 0.01},
                 "events": [{"type": "turn"}, {"type": "tool_call", "tool": "edit", "ok": True}, {"type": "edit"}]}
        rec = run_trial(ch, CONDITIONS["A"], self.fake_agent(writes + f"json.dump({trace!r}, open(sys.argv[1], 'w'))\n"),
                        self.tmp / "w1", "t1")
        self.assertEqual((rec["success"], rec["synthetic"], rec["total_tokens"], rec["tool_calls"], rec["agent_model"],
                          rec["reasoning_tokens"]), (True, False, 1000, 1, "fake-1", None))
        self.assertEqual((rec["tests_passed"], rec["tests_total"], rec["pass_rate"]), (3, 3, 1.0))
        self.assertGreater(rec["diff_lines_added"], 0)
        rec = run_trial(ch, CONDITIONS["B"], self.fake_agent(writes), self.tmp / "w2", "t2")
        self.assertEqual((rec["success"], rec["tool_calls"], rec["total_tokens"], rec["agent_turns"]), (True, None, None, None))
        self.assertIsNotNone(rec["wall_seconds"])  # measured by the harness itself

    def test_agent_failures_are_categorised(self):
        ch = load_challenge(SUITE / "py-small-function")
        rec = run_trial(ch, CONDITIONS["A"], self.fake_agent("pass\n"), self.tmp / "w1", "t1")
        self.assertEqual((rec["status"], rec["success"], rec["failure_category"]), ("completed", False, "grader_failed"))
        rec = run_trial(ch, CONDITIONS["A"], self.fake_agent("raise SystemExit(3)\n"), self.tmp / "w2", "t2")
        self.assertEqual((rec["status"], rec["failure_category"]), ("agent_error", "agent_error"))
        ch.trial_timeout = 0.5
        rec = run_trial(ch, CONDITIONS["A"], self.fake_agent("import time; time.sleep(20)\n"), self.tmp / "w3", "t3")
        self.assertEqual((rec["status"], rec["failure_category"]), ("timeout", "timeout"))
        ch.requires = ["no-such-compiler-xyz"]
        rec = run_trial(ch, CONDITIONS["A"], ReplayAgent(), self.tmp / "w4", "t4")
        self.assertEqual((rec["status"], rec["success"]), ("skipped", None))

    def test_manual_prepare_and_grade_workflow(self):
        trial, results = self.tmp / "manual", self.tmp / "results"
        self.assertEqual(bench_main(["--suite", str(SUITE), "prepare", "py-small-function", "C", "--out", str(trial)]), 0)
        self.assertTrue((trial / "workspace/cai.json").exists())  # CAI overlay only in condition C
        self.assertIn("#evolve", (trial / "prompt.md").read_text())
        shutil.copyfile(SUITE / "py-small-function/replay_files/solution.py", trial / "workspace/src/textutil.py")
        self.assertEqual(bench_main(["grade", str(trial), "--results", str(results)]), 0)
        rec = json.loads((results / "trials.jsonl").read_text())
        self.assertEqual((rec["success"], rec["synthetic"], rec["tool_calls"], rec["wall_seconds"]), (True, False, None, None))
        self.assertEqual(bench_main(["report", str(results)]), 0)
        self.assertEqual(json.loads((results / "summary.json").read_text())["evidence"], "agent")
        other = self.tmp / "manualA"
        bench_main(["--suite", str(SUITE), "prepare", "py-small-function", "A", "--out", str(other)])
        self.assertFalse((other / "workspace/cai.json").exists())


def trial(cond, challenge, success, wall, tokens=None, tools=None, synthetic=False, status="completed"):
    return {"condition": cond, "challenge": challenge, "status": status, "success": success, "synthetic": synthetic,
            "failure_category": None if success else "grader_failed", "wall_seconds": wall, "total_tokens": tokens,
            "tool_calls": tools, "pass_rate": 1.0 if success else 0.5}


class AnalysisTests(unittest.TestCase):
    def test_correctness_is_separate_from_efficiency(self):
        # C is cheap only because it fails the expensive task.
        trials = [trial("A", "easy", True, 10, 100, 4), trial("A", "hard", True, 90, 900, 20),
                  trial("C", "easy", True, 8, 80, 3), trial("C", "hard", False, 200, 2000, 40)]
        s = analysis.summarize(trials)
        a, c = s["aggregate"]["A"], s["aggregate"]["C"]
        self.assertEqual((a["success_rate"], c["success_rate"]), (1.0, 0.5))
        self.assertEqual(c["failure_categories"], {"grader_failed": 1})
        self.assertEqual(c["successful_only"]["total_tokens"]["mean"], 80)      # looks cheaper...
        self.assertEqual(c["all_attempts"]["total_tokens"]["mean"], 1040)       # ...but is not
        red = s["comparisons_vs_A"]["C"]["total_tokens"]
        self.assertEqual((red["tasks_compared"], red["relative_reduction"]), (2, -1.08))
        md = analysis.markdown(s)
        self.assertIn("selection bias", md)
        self.assertIn("Agent trials", md)

    def test_missing_metrics_and_small_samples(self):
        trials = [trial("A", "t", True, 1.0), trial("A", "t", True, 3.0), trial("C", "t", True, 2.0, tokens=50)]
        s = analysis.summarize(trials)
        tok = s["aggregate"]["A"]["all_attempts"]["total_tokens"]
        self.assertEqual((tok["n"], tok["mean"]), (0, None))
        self.assertIsNone(s["comparisons_vs_A"]["C"]["total_tokens"])           # A never measured tokens
        wall = s["aggregate"]["A"]["all_attempts"]["wall_seconds"]
        self.assertEqual((wall["mean"], wall["median"], wall["ci95"]), (2.0, 2.0, None))  # n < 5: no interval
        self.assertIsNotNone(analysis.bootstrap_ci([1, 2, 3, 4, 5, 6]))
        lo, hi = analysis.wilson(5, 10)
        self.assertTrue(0.2 < lo < 0.5 < hi < 0.8)
        self.assertIsNone(analysis.wilson(0, 0))

    def test_evidence_labels_and_skips(self):
        trials = [trial("A", "t", True, 1, synthetic=True), trial("A", "t", True, 1),
                  trial("A", "u", None, None, status="skipped")]
        s = analysis.summarize(trials)
        self.assertEqual(s["evidence"], "mixed")
        self.assertEqual((s["aggregate"]["A"]["attempted"], s["aggregate"]["A"]["skipped"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
