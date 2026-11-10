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

from lru import LRUCache


@case
def evicts_least_recent():
    c = LRUCache(2)
    c.put("a", 1), c.put("b", 2), c.put("c", 3)
    assert c.get("a") is None and c.get("b") == 2 and c.get("c") == 3 and len(c) == 2


@case
def get_refreshes():
    c = LRUCache(2)
    c.put("a", 1), c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b", "gone") == "gone" and c.get("a") == 1


@case
def put_updates_and_refreshes():
    c = LRUCache(2)
    c.put("a", 1), c.put("b", 2), c.put("a", 10), c.put("c", 3)
    assert c.get("a") == 10 and c.get("b") is None and len(c) == 2


@case
def capacity_validation():
    assert raises(ValueError, LRUCache, 0) and raises(ValueError, LRUCache, -3)
    c = LRUCache(1)
    c.put(1, None)
    assert c.get(1, "d") is None and len(c) == 1


finish()
