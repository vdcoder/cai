from tests.helpers import WorkspaceCase

SRC = """\
def process_data(buf):
    if buf is None:
        return None
    return len(buf)

# #test empty_buffer
# from m import process_data
# assert process_data(None) is None
# #end

# #test length
# from m import process_data
# assert process_data(b"abc") == 3, "length mismatch"
# #end
"""


def names(report):
    return [(t["name"], t["status"]) for t in report["tests"]]


class PersistentTestTests(WorkspaceCase):
    def test_suite_runs_and_definitions_survive(self):
        self.write("src/m.py", SRC)
        for _ in range(3):  # repeatable without duplicating or altering anything
            code, rep = self.cai("--test")
            self.assertEqual((code, names(rep)), (0, [("empty_buffer", "passed"), ("length", "passed")]))
            self.assertEqual(rep["files_modified"], [])
        self.assertEqual(self.read("src/m.py"), SRC)
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name != ".cai"), ["cai.json", "src", "tools"])
        self.assertIsNone(rep["tests"][0]["checkpoint"])

    def test_tests_survive_build_and_run(self):
        self.write("src/m.py", SRC + "# #wait\n# x\n# #end\n")
        self.cai("--build")
        self.cai("--run")
        self.assertEqual(self.read("src/m.py"), SRC)

    def test_selective_execution(self):
        self.write("src/m.py", SRC)
        code, rep = self.cai("--test", "length")
        self.assertEqual((code, names(rep)), (0, [("length", "passed")]))
        code, rep = self.cai("--test", "nope")
        self.assertEqual((code, self.codes(rep), rep["tests"]), (2, ["E305"], []))

    def test_failing_test_reports_and_exit_code(self):
        self.write("src/m.py", SRC.replace("== 3", "== 4"))
        code, rep = self.cai("--test")
        self.assertEqual((code, names(rep)), (1, [("empty_buffer", "passed"), ("length", "failed")]))
        self.assertIn("length mismatch", rep["tests"][1]["stderr"])

    def test_evolve_test_keeps_identity_and_position(self):
        self.write("src/m.py", SRC + "\n# #evolve length\n# from m import process_data\n# assert process_data(b'') == 0\n# #end\n")
        code, rep = self.cai("--test")
        self.assertEqual((code, names(rep)), (0, [("empty_buffer", "passed"), ("length", "passed")]))
        expected = SRC.replace('# assert process_data(b"abc") == 3, "length mismatch"', "# assert process_data(b'') == 0")
        self.assertEqual(self.read("src/m.py"), expected)
        self.write("src/m.py", expected + "# #evolve length\n# assert False, 'second evolution'\n# #end\n")
        code, rep = self.cai("--test", "length")  # a test stays evolvable
        self.assertEqual(code, 1)
        self.assertIn("second evolution", rep["tests"][0]["stderr"])

    def test_test_evolved_twice_in_one_invocation(self):
        self.write("src/m.py", "# #test t\n# assert False\n# #end\n# #evolve t\n# assert 0\n# #end\n# #evolve t\n# assert True\n# #end\n")
        self.assertEqual(self.cai("--test")[0], 0)
        self.assertEqual(self.read("src/m.py"), "# #test t\n# assert True\n# #end\n")

    def test_drop_test(self):
        self.write("src/m.py", SRC + "# #drop length\n# #end\n")
        code, rep = self.cai("--test")
        self.assertEqual((code, names(rep)), (0, [("empty_buffer", "passed")]))
        self.assertNotIn("length", self.read("src/m.py"))

    def test_tests_see_final_state_and_are_excluded_from_runs(self):
        self.write("src/m.py", "# #defer impl\n# #end\n# #test t\n# import m\n# assert m.f() == 1\n# #end\n"
                   "# #run probe\n# import m\n# print(hasattr(m, 'f'))\n# #end\n# #evolve impl\n# def f():\n#     return 1\n# #end\n")
        code, rep = self.cai("--run", "--test")
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["runs"][0]["stdout"], "False\n")
        self.assertEqual(names(rep), [("t", "passed")])
        code, rep = self.cai("--run")  # --run alone never executes tests
        self.assertNotIn("tests", rep)

    def test_discovery_order_is_path_then_line(self):
        self.write("src/b.py", "# #test b1\n# pass\n# #end\n")
        self.write("src/a.py", "# #test a2\n# pass\n# #end\n# #test a1\n# pass\n# #end\n")
        self.write("src/x.c", "/* #test c_style\npass\n#end */\n")
        _, rep = self.cai("--test")
        self.assertEqual([t["name"] for t in rep["tests"]], ["a2", "a1", "b1", "c_style"])

    def test_c_block_test_evolution_rerenders_in_style(self):
        self.write("src/x.c", "int a;\n  /* #test t\n  assert False\n  #end */\n/* #evolve t\nx = 1\nassert x\n#end */\n")
        self.assertEqual(self.cai("--test")[0], 0)
        self.assertEqual(self.read("src/x.c"), "int a;\n  /* #test t\n  x = 1\n  assert x\n  #end */\n")

    def test_no_tests(self):
        self.write("src/m.py", "X = 1\n")
        code, rep = self.cai("--test")
        self.assertEqual((code, rep["tests"]), (0, []))
