import json
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (adds src to sys.path)

from cai.adapters import ADAPTERS
from cai.config import ConfigError, load_config
from cai.discovery import discover
from cai.parser import dedent, parse_text


def parse(text, style="c_block"):
    return parse_text(text, "f", ADAPTERS[style])


def roundtrip(pf):
    return "".join(s if isinstance(s, str) else s.raw for s in pf.segments)


class AdapterTests(unittest.TestCase):
    def test_c_block(self):
        src = "int a;\n  /* #defer process_data\n  Validate the buffer.\n  #end */\nint b;\n"
        pf = parse(src)
        self.assertEqual(pf.diagnostics, [])
        (d,) = pf.directives
        self.assertEqual((d.command, d.name, d.line, d.end_line, d.indent), ("defer", "process_data", 2, 4, "  "))
        self.assertEqual(d.body, ["  Validate the buffer."])
        self.assertEqual(roundtrip(pf), src)

    def test_python_comment(self):
        src = "x = 1\n    # #test t1\n    # assert f() == 1\n    #\n    #   indented\n    # #end\n"
        pf = parse(src, "python_comment")
        (d,) = pf.directives
        self.assertEqual(d.body, ["assert f() == 1", "", "  indented"])
        self.assertEqual(roundtrip(pf), src)

    def test_html_comment(self):
        pf = parse("# Title\n<!-- #wait\nthinking\n#end -->\ntext\n", "html_comment")
        (d,) = pf.directives
        self.assertEqual((d.command, d.name, d.body), ("wait", None, ["thinking"]))

    def test_bare(self):
        pf = parse("#run probe\nprint(1)\n#end\n", "bare")
        (d,) = pf.directives
        self.assertEqual((d.command, d.name, d.body), ("run", "probe", ["print(1)"]))

    def test_single_line_forms(self):
        pf = parse("/* #drop old #end */\n/* #wait rethink this #end */\n")
        a, b = pf.directives
        self.assertEqual((a.command, a.name, a.body), ("drop", "old", []))
        self.assertEqual((b.command, b.body), ("wait", ["rethink this"]))
        pf = parse("# #drop old #end\n", "python_comment")
        self.assertEqual(pf.directives[0].name, "old")

    def test_wait_header_text_becomes_body(self):
        pf = parse("/* #wait hmm\nmore\n#end */\n")
        self.assertEqual(pf.directives[0].body, ["hmm", "more"])

    def test_body_may_contain_comment_closers(self):
        pf = parse("/* #evolve f\nint f(void) { /* inner */ return 1; }\n#end */\n")
        self.assertEqual(pf.diagnostics, [])
        self.assertEqual(pf.directives[0].body, ["int f(void) { /* inner */ return 1; }"])


class NonDirectiveTests(unittest.TestCase):
    def test_lookalikes_are_ordinary_text(self):
        src = ('s = "/* #run x"\nprintf("#end */ %d", 1);\n// /* #defer y\n/* #deferred z */\n'
               "/* #include */\n#define X 1\n")
        pf = parse(src)
        self.assertEqual(pf.diagnostics, [])
        self.assertEqual(pf.directives, [])
        self.assertEqual(pf.segments, [src])

    def test_python_plain_comments_and_strings(self):
        src = '# test of things\n#run fast\nx = "# #run a"\ndoc = """\n text # #wait\n"""\n'
        pf = parse(src, "python_comment")
        self.assertEqual((pf.diagnostics, pf.directives), ([], []))


class MalformedTests(unittest.TestCase):
    def codes(self, text, style="c_block"):
        pf = parse(text, style)
        self.assertEqual(roundtrip(pf), text)
        return [(d.code, d.line) for d in pf.diagnostics]

    def test_unterminated(self):
        self.assertEqual(self.codes("a\n/* #wait\nforever\n"), [("E201", 2)])

    def test_closed_without_end(self):
        self.assertEqual(self.codes("/* #wait hmm */\nint x;\n"), [("E201", 1)])

    def test_python_unterminated_stops_at_code(self):
        self.assertEqual(self.codes("# #defer a\n# text\nx = 1\n", "python_comment"), [("E201", 1)])

    def test_nested(self):
        codes = self.codes("/* #defer a\n/* #wait\n#end */\n#end */\n")
        self.assertEqual(codes[0], ("E202", 2))

    def test_stray_end(self):
        self.assertEqual(self.codes("int x;\n#end */\n"), [("E203", 2)])

    def test_missing_or_bad_name(self):
        self.assertEqual(self.codes("/* #defer\nx\n#end */\n"), [("E204", 1)])
        self.assertEqual(self.codes("/* #run 9lives\n#end */\n"), [("E204", 1)])
        self.assertEqual(self.codes("/* #run a b c\n#end */\n"), [("E204", 1)])

    def test_diagnostic_fields(self):
        d = parse("\n/* #evolve thing\n").diagnostics[0]
        self.assertEqual((d.file, d.line, d.directive, d.severity), ("f", 2, "evolve", "error"))
        self.assertIn("unterminated", d.message)


class TextHandlingTests(unittest.TestCase):
    def test_crlf(self):
        src = "a;\r\n/* #wait\r\nx\r\n#end */\r\nb;\r\n"
        pf = parse(src)
        self.assertEqual(pf.newline, "\r\n")
        self.assertEqual(pf.directives[0].body, ["x"])
        self.assertEqual(roundtrip(pf), src)

    def test_unicode_and_odd_separators(self):
        src = "s = 'héllo   wörld \x0c 日本'\n/* #defer 名\n#end */\n/* #wait\n思考 🙂\n#end */\n"
        pf = parse(src)
        self.assertEqual([d.code for d in pf.diagnostics], ["E204"])  # names are ASCII identifiers
        self.assertEqual(pf.directives[0].body, ["思考 🙂"])
        self.assertEqual(pf.directives[0].line, 4)
        self.assertEqual(roundtrip(pf), src)

    def test_no_trailing_newline(self):
        src = "x\n/* #drop a\n#end */"
        pf = parse(src)
        self.assertEqual(pf.directives[0].raw, "/* #drop a\n#end */")

    def test_dedent(self):
        self.assertEqual(dedent(["    a", "", "      b"]), ["a", "", "  b"])

    def test_render_roundtrip(self):
        for style in ADAPTERS:
            ad = ADAPTERS[style]
            text = ad.render("test", "t", ["a = 1", "", "  b"], "  ", "\n")
            (d,) = parse_text(text, "f", ad).directives
            self.assertEqual((d.command, d.name, dedent(d.body)), ("test", "t", ["a = 1", "", "  b"]), style)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_cfg(self, data):
        (self.root / "cai.json").write_text(json.dumps(data))

    def test_load_and_discover_order(self):
        self.write_cfg({"version": 1, "project": {"include": [
            {"pattern": "src/**/*.py", "style": "python_comment"},
            {"pattern": "src/**/*", "style": "bare"}], "exclude": ["src/skip/*"]}})
        for rel in ("src/b.py", "src/a/z.py", "src/a.txt", "src/skip/x.py", "other/y.py", ".cai/x.py"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")
        cfg = load_config(self.root)
        self.assertEqual([(r, s) for r, _, s in discover(cfg)],
                         [("src/a.txt", "bare"), ("src/a/z.py", "python_comment"), ("src/b.py", "python_comment")])

    def test_invalid(self):
        for bad in ({"version": 2, "project": {"include": [{"pattern": "a", "style": "bare"}]}},
                    {"version": 1, "project": {"include": [{"pattern": "a", "style": "docstring"}]}},
                    {"version": 1, "project": {"include": [{"pattern": "../a", "style": "bare"}]}},
                    {"version": 1, "project": {"include": [{"pattern": "a", "style": "bare"}]},
                     "runner": {"run_command": "python x.py"}}):
            self.write_cfg(bad)
            with self.assertRaises(ConfigError):
                load_config(self.root)

    def test_missing(self):
        with self.assertRaises(ConfigError):
            load_config(self.root)


if __name__ == "__main__":
    unittest.main()
