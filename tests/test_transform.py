from tests.helpers import WorkspaceCase

C_DEFER = """\
#include <stddef.h>

    /* #defer process_data
    Validate the buffer, then process the data.
    #end */

int main(void) { return 0; }
"""


class TransformTests(WorkspaceCase):
    def test_wait_is_removed_and_source_preserved(self):
        self.write("src/a.c", "int a;\n\n/* #wait\nmaybe reuse the buffer\n#end */\n\nint b;\n")
        code, rep = self.cai("--build")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("src/a.c"), "int a;\n\nint b;\n")
        self.assertEqual(rep["files_modified"], ["src/a.c"])
        self.assertNotIn("waits", rep)

    def test_show_waits(self):
        self.write("src/a.c", "/* #wait\nreconsider\n#end */\n")
        _, rep = self.cai("--check", "--show-waits")
        self.assertEqual(rep["waits"][0]["text"], "reconsider")

    def test_defer_stays_until_evolved(self):
        self.write("src/a.c", C_DEFER)
        code, rep = self.cai("--build")
        self.assertEqual((code, rep["files_modified"]), (0, []))
        self.assertEqual(self.read("src/a.c"), C_DEFER)
        self.assertEqual(rep["pending"]["defers"][0]["name"], "process_data")

    def test_evolve_materializes_at_placeholder_with_its_indent(self):
        self.write("src/a.c", C_DEFER + "\n/* #evolve process_data\nvoid process_data(void* b) {\n"
                   "    if (!b) return;\n}\n#end */\n")
        code, _ = self.cai("--build")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("src/a.c"), "#include <stddef.h>\n\n    void process_data(void* b) {\n"
                         "        if (!b) return;\n    }\n\nint main(void) { return 0; }\n")

    def test_python_evolve(self):
        self.write("src/m.py", "def f(x):\n    # #defer body\n    # compute the answer\n    # #end\n\n"
                   "# #evolve body\n# if x:\n#     return 42\n#\n# return 0\n# #end\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/m.py"), "def f(x):\n    if x:\n        return 42\n\n    return 0\n")

    def test_html_and_bare(self):
        self.write("docs/d.md", "# T\n\n<!-- #defer intro\nwrite intro\n#end -->\n\n## Next\n\n"
                   "<!-- #evolve intro\nHello *world*.\n#end -->\n")
        self.write("notes/n.txt", "#defer a\ntodo\n#end\ntail\n#evolve a\ndone\n#end\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("docs/d.md"), "# T\n\nHello *world*.\n\n## Next\n")
        self.assertEqual(self.read("notes/n.txt"), "done\ntail\n")

    def test_drop(self):
        self.write("src/a.c", "int a;\n/* #defer x\nlater\n#end */\nint b;\n/* #drop x\n#end */\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "int a;\nint b;\n")

    def test_multiple_evolutions_in_one_invocation(self):
        self.write("src/a.c", "/* #defer a\n#end */\n/* #defer b\n#end */\nint z;\n"
                   "/* #evolve b\nint b;\n#end */\n/* #evolve a\nint a;\n#end */\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "int a;\nint b;\nint z;\n")

    def test_sequential_reuse_of_identifier(self):
        self.write("src/a.c", "/* #defer v\n#end */\n/* #evolve v\nint one;\n#end */\n"
                   "/* #defer v\n#end */\n/* #evolve v\nint two;\n#end */\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "int one;\nint two;\n")

    def test_cross_file_evolve_follows_path_order(self):
        self.write("src/a.c", "/* #defer shared\n#end */\n")
        self.write("src/b.c", "/* #evolve shared\nint shared;\n#end */\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual((self.read("src/a.c"), self.read("src/b.c")), ("int shared;\n", ""))

    def test_cross_file_wrong_order_is_missing_target_with_hint(self):
        self.write("src/a.c", "/* #evolve shared\nint shared;\n#end */\n")
        self.write("src/b.c", "/* #defer shared\n#end */\n")
        code, rep = self.cai("--build")
        self.assertEqual((code, self.codes(rep)), (2, ["E301"]))
        self.assertIn("src/b.c:1", rep["diagnostics"][0]["message"])


class DiagnosticTests(WorkspaceCase):
    def assert_rejected(self, text, expected):
        self.write("src/a.c", text)
        self.write("src/ok.c", "/* #wait\nx\n#end */\nint ok;\n")
        code, rep = self.cai("--build")
        self.assertEqual(code, 2)
        self.assertEqual(self.codes(rep), expected)
        self.assertEqual(rep["files_modified"], [])
        self.assertEqual(self.read("src/a.c"), text)
        self.assertIn("#wait", self.read("src/ok.c"))  # nothing is partially applied
        return rep

    def test_missing_target(self):
        rep = self.assert_rejected("/* #evolve ghost\nint x;\n#end */\n", ["E301"])
        d = rep["diagnostics"][0]
        self.assertEqual((d["file"], d["line"], d["directive"], d["name"]), ("src/a.c", 1, "evolve", "ghost"))

    def test_missing_drop_target(self):
        self.assert_rejected("/* #drop ghost\n#end */\n", ["E301"])

    def test_already_consumed(self):
        rep = self.assert_rejected("/* #defer a\n#end */\n/* #evolve a\nint a;\n#end */\n"
                                   "/* #evolve a\nint b;\n#end */\n", ["E302"])
        self.assertIn("src/a.c:3", rep["diagnostics"][0]["message"])
        self.assert_rejected("/* #defer a\n#end */\n/* #drop a\n#end */\n/* #drop a\n#end */\n", ["E302"])

    def test_duplicate_active_identifier(self):
        self.assert_rejected("/* #defer a\n#end */\n/* #defer a\n#end */\n", ["E303"])
        self.assert_rejected("/* #defer a\n#end */\n/* #test a\n#end */\n", ["E303"])

    def test_malformed_blocks_reject_everything(self):
        self.assert_rejected("int a;\n/* #wait\nnever closed\n", ["E201"])
        self.assert_rejected("/* #defer a\n/* #wait\n#end */\n#end */\n", ["E202", "E203"])

    def test_check_never_writes(self):
        text = "/* #wait\nx\n#end */\nint a;\n"
        self.write("src/a.c", text)
        code, rep = self.cai("--check")
        self.assertEqual((code, rep["would_modify"], rep["files_modified"]), (0, ["src/a.c"], []))
        self.assertEqual(self.read("src/a.c"), text)
        self.assertFalse((self.root / ".cai").exists())


class PreservationTests(WorkspaceCase):
    def test_idempotent_and_repeatable(self):
        self.write("src/a.c", C_DEFER + "/* #evolve process_data\nvoid process_data(void);\n#end */\n")
        self.assertEqual(self.cai("--build")[1]["files_modified"], ["src/a.c"])
        once = self.read("src/a.c")
        for _ in range(2):
            code, rep = self.cai("--build")
            self.assertEqual((code, rep["files_modified"]), (0, []))
        self.assertEqual(self.read("src/a.c"), once)

    def test_untouched_files_keep_bytes_and_mtime(self):
        raw = b"\xef\xbb\xbfint a;\r\n\t \r\n// tr\xc3\xa4iling  \r\nno newline"
        p = self.write("src/keep.c", raw)
        before = p.stat().st_mtime_ns
        self.write("src/z.c", "/* #wait\nx\n#end */\n")
        self.assertEqual(self.cai("--build")[1]["files_modified"], ["src/z.c"])
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), (raw, before))

    def test_crlf_bom_and_unicode(self):
        raw = ("\ufeffint a; // \u65e5\u672c\u8a9e \U0001f642\r\n/* #defer f\r\n#end */\r\nint z;\r\n"
               "/* #evolve f\r\nint f(void) {\r\n  return 1; // \u00e9\r\n}\r\n#end */\r\n")
        self.write("src/a.c", raw)
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "\ufeffint a; // \u65e5\u672c\u8a9e \U0001f642\r\n"
                         "int f(void) {\r\n  return 1; // \u00e9\r\n}\r\nint z;\r\n")

    def test_lf_body_evolved_into_crlf_file(self):
        self.write("src/a.c", "/* #defer f\r\n#end */\r\n")
        self.write("src/b.c", "/* #evolve f\nint f;\nint g;\n#end */\n")
        self.assertEqual(self.cai("--build")[0], 0)
        self.assertEqual(self.read("src/a.c"), "int f;\r\nint g;\r\n")

    def test_blank_line_policy(self):
        self.write("src/a.c", "a;\n/* #wait\n#end */\nb;\n\n/* #wait\n#end */\n\n/* #wait\n#end */\n\nc;\n\n"
                   "/* #wait\n#end */\n")
        self.cai("--build")
        self.assertEqual(self.read("src/a.c"), "a;\nb;\n\nc;\n")

    def test_invalid_utf8_is_reported_not_modified(self):
        self.write("src/a.c", b"int a = '\xff';\n")
        code, rep = self.cai("--build")
        self.assertEqual((code, self.codes(rep)), (2, ["E502"]))
