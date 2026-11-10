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

from textutil import slugify


@case
def basic():
    assert slugify("Hello, World!") == "hello-world"


@case
def trims():
    assert slugify("  --Already--Slugged--  ") == "already-slugged"


@case
def digits_and_empty():
    assert slugify("Version 2.0 (beta)") == "version-2-0-beta"
    assert slugify("") == "" and slugify("!!!") == ""


finish()
