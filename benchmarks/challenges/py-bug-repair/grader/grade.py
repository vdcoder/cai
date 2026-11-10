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

from search import find_index


@case
def finds_every_element():
    for n in range(0, 40):
        items = [3 * i + 1 for i in range(n)]
        for i, value in enumerate(items):
            assert find_index(items, value) == i, (n, value)


@case
def absent_values():
    items = [1, 4, 7, 10]
    for value in (0, 2, 5, 8, 11):
        assert find_index(items, value) == -1


@case
def still_logarithmic():
    class Counting(list):
        reads = 0

        def __getitem__(self, i):
            Counting.reads += 1
            return list.__getitem__(self, i)

    items = Counting(range(1 << 16))
    assert find_index(items, 12345) == 12345
    assert Counting.reads <= 80, Counting.reads


finish()
