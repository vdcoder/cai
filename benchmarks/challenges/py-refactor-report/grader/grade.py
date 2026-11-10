"""Hidden grader. Never copied into the agent's workspace."""
import json
import os
import sys
import traceback

WS = os.environ["CAI_BENCH_WORKSPACE"]
sys.path.insert(0, os.path.join(WS, "src"))
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    return False


def finish(**extra):
    passed = 0
    for fn in CASES:
        try:
            fn()
            passed += 1
        except Exception:
            print("FAIL", fn.__name__)
            traceback.print_exc(file=sys.stdout)
    print("CAI_BENCH_RESULT " + json.dumps({"tests_passed": passed, "tests_total": len(CASES), **extra}))
    sys.exit(0 if passed == len(CASES) else 1)

import ast

import report

SALES = [("  widget ", 1234.5), ("a very long product name", 0.125), ("x", 1e6)]
COSTS = [("rent", 800), ("power", 99.999)]
EXPECTED_SALES = "Widget       |   1,234.50\nA Very Long  |       0.12\nX            | 1,000,000.00"
EXPECTED_COSTS = "Rent         |    -800.00\nPower        |    -100.00"
EXPECTED_SUMMARY = "Total Sales  | 1,001,234.62\nTotal Costs  |    -900.00\nNet          | 1,000,334.63"
TREE = ast.parse(open(os.path.join(WS, "src", "report.py"), encoding="utf-8").read())


@case
def behaviour_unchanged():
    assert report.render_sales(SALES) == EXPECTED_SALES
    assert report.render_costs(COSTS) == EXPECTED_COSTS
    assert report.render_summary(SALES, COSTS) == EXPECTED_SUMMARY


@case
def helper_behaviour():
    assert report.format_row(" net ", 2) == "Net          |       2.00"


@case
def helper_used_by_all_three():
    funcs = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}
    for name in ("render_sales", "render_costs", "render_summary"):
        calls = [c for c in ast.walk(funcs[name]) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "format_row"]
        assert calls, name


@case
def duplication_removed():
    ljust = [c for c in ast.walk(TREE) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "ljust"]
    assert len(ljust) == 1, len(ljust)


finish()
