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

import random
import threading
import time

from pairs import count_pairs

RUNTIME = {}


def brute(nums, target):
    return sum(nums[i] + nums[j] == target for i in range(len(nums)) for j in range(i + 1, len(nums)))


@case
def matches_reference():
    rng = random.Random(7)
    for _ in range(200):
        nums = [rng.randint(-5, 5) for _ in range(rng.randint(0, 30))]
        target = rng.randint(-6, 6)
        assert count_pairs(nums, target) == brute(nums, target), (nums, target)


@case
def does_not_mutate_input():
    nums = [3, 1, 2]
    count_pairs(nums, 4)
    assert nums == [3, 1, 2]


@case
def scales():
    rng = random.Random(11)
    nums = [rng.randint(0, 1000) for _ in range(200000)]

    def work():
        start = time.perf_counter()
        count_pairs(nums, 1000)
        RUNTIME["ms"] = round((time.perf_counter() - start) * 1000, 1)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(8)
    assert "ms" in RUNTIME, "did not finish within 8 seconds"
    assert RUNTIME["ms"] < 2000, RUNTIME


# Same loop as finish(), with the measured runtime added to the result line.
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

import random
import threading
import time

from pairs import count_pairs

RUNTIME = {}


def brute(nums, target):
    return sum(nums[i] + nums[j] == target for i in range(len(nums)) for j in range(i + 1, len(nums)))


@case
def matches_reference():
    rng = random.Random(7)
    for _ in range(200):
        nums = [rng.randint(-5, 5) for _ in range(rng.randint(0, 30))]
        target = rng.randint(-6, 6)
        assert count_pairs(nums, target) == brute(nums, target), (nums, target)


@case
def does_not_mutate_input():
    nums = [3, 1, 2]
    count_pairs(nums, 4)
    assert nums == [3, 1, 2]


@case
def scales():
    rng = random.Random(11)
    nums = [rng.randint(0, 1000) for _ in range(200000)]

    def work():
        start = time.perf_counter()
        count_pairs(nums, 1000)
        RUNTIME["ms"] = round((time.perf_counter() - start) * 1000, 1)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(8)
    assert "ms" in RUNTIME, "did not finish within 8 seconds"
    assert RUNTIME["ms"] < 2000, RUNTIME


CASES_RUN = finish  # runtime is reported only if the scaling case ran
try:
    for fn in list(CASES):
        pass
finally:
    pass
import atexit  # noqa: E402


def _report():
    pass


passed = 0
for fn in CASES:
    try:
        fn()
        passed += 1
    except Exception:
        print("FAIL", fn.__name__)
        traceback.print_exc(file=sys.stdout)
print("CAI_BENCH_RESULT " + json.dumps({"tests_passed": passed, "tests_total": len(CASES), "runtime_ms": RUNTIME.get("ms")}))
sys.exit(0 if passed == len(CASES) else 1)
