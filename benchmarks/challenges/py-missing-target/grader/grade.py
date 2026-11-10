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

from inventory import Inventory


@case
def restock():
    inv = Inventory()
    assert inv.restock("bolt", 5) == 5 and inv.restock("bolt", 2) == 7
    assert raises(ValueError, inv.restock, "bolt", 0) and raises(ValueError, inv.restock, "nut", -1)
    assert inv.stock == {"bolt": 7}


@case
def remove():
    inv = Inventory()
    inv.restock("bolt", 5)
    assert inv.remove("bolt", 2) == 3
    assert raises(KeyError, inv.remove, "nut", 1)
    assert raises(ValueError, inv.remove, "bolt", 4) and raises(ValueError, inv.remove, "bolt", 0)
    assert inv.remove("bolt", 3) == 0 and "bolt" not in inv.stock


@case
def authoritative_names_only():
    assert not hasattr(Inventory, "restock_item") and not hasattr(Inventory, "remove_item")


finish()
