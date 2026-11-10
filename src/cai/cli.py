"""Command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, stats
from .config import CONFIG_NAME, ConfigError, load_config
from .core import EXIT_CONFIG, EXIT_INTERRUPTED, Options, invoke
from .diagnostics import Diagnostic
from .report import format_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cai",
        description="Consolidate CAI directives (#defer #wait #evolve #drop #run #test) into clean source.",
    )
    p.add_argument("--version", action="version", version=f"cai {__version__}")
    mode = p.add_argument_group("modes (--run and --test may be combined)")
    mode.add_argument("--check", action="store_true", help="validate directives; never writes anything")
    mode.add_argument("--run", action="store_true", help="consolidate and execute pending #run experiments")
    mode.add_argument("--test", nargs="*", metavar="NAME", default=None,
                      help="consolidate and execute persistent #test blocks (all, or the named ones)")
    mode.add_argument("--build", action="store_true",
                      help="consolidate only; pending #run blocks stay in the source unexecuted")
    mode.add_argument("--stats", action="store_true", help="show stored operational statistics")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--root", metavar="DIR", default=".", help=f"workspace containing {CONFIG_NAME} (default: .)")
    p.add_argument("--config", metavar="FILE", help=f"explicit path to {CONFIG_NAME}")
    p.add_argument("--discard-runs", action="store_true",
                   help="with --build/--test: remove pending #run blocks instead of keeping them")
    p.add_argument("--show-waits", action="store_true", help="include #wait bodies in the report")
    p.add_argument("--full-scan", action="store_true", help="ignore the incremental-scan manifest")
    p.add_argument("--no-stats", action="store_true", help="do not append a statistics record")
    p.add_argument("--keep-snapshots", action="store_true", help="do not delete snapshot directories")
    return p


def _emit(report: dict, as_json: bool) -> None:
    if as_json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_report(report))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    opts = Options(check=args.check, run=args.run, test=args.test is not None, build=args.build,
                   test_names=list(args.test or []), discard_runs=args.discard_runs,
                   show_waits=args.show_waits, keep_snapshots=args.keep_snapshots,
                   full_scan=args.full_scan, no_stats=args.no_stats)
    modes = [args.check, args.run or opts.test or args.build, args.stats]
    if sum(bool(m) for m in modes) != 1:
        parser.print_usage(sys.stderr)
        sys.stderr.write("cai: choose --check, --stats, or any of --run/--test/--build\n")
        return EXIT_CONFIG
    try:
        cfg = load_config(Path(args.config) if args.config else Path(args.root))
    except ConfigError as exc:
        diag = Diagnostic("error", "E100", str(exc))
        _emit({"ok": False, "exit_code": EXIT_CONFIG, "mode": "config", "diagnostics": [diag.to_dict()]}, args.json)
        return EXIT_CONFIG
    if args.stats:
        summary = stats.summarize(cfg.stats_file)
        if args.json:
            _emit(summary, True)
        else:
            sys.stdout.write(stats.format_summary(summary))
        return 0
    try:
        code, report = invoke(cfg, opts)
    except KeyboardInterrupt:
        sys.stderr.write("cai: interrupted; source files were left in their pre-invocation state\n")
        return EXIT_INTERRUPTED
    _emit(report, args.json)
    return code
