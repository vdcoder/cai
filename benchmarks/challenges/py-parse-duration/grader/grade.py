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

from durations import parse_duration


@case
def valid():
    for text, seconds in {"1h30m": 5400, "45s": 45, "2h": 7200, "1h 5m 10s": 3910, " 10M ": 600,
                          "0s": 0, "1H1S": 3601, "90m": 5400}.items():
        assert parse_duration(text) == seconds, text


@case
def rejects_malformed():
    for text in ["", "   ", "5", "m5", "-5m", "1.5h", "1h30", "abc", "1d", "h"]:
        assert raises(ValueError, parse_duration, text), text


@case
def rejects_order_and_repeats():
    for text in ["1m1h", "1h1h", "5s 1m", "1s1h", "1m 2m"]:
        assert raises(ValueError, parse_duration, text), text


finish()
