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

from shop import config
from shop.pricing import format_money, order_total
from shop.receipt import render_receipt

ITEMS = [("tea", 2.5, 2), ("pot", 1200, 1)]


@case
def config_lists_currencies():
    assert set(config.SUPPORTED_CURRENCIES) == {"USD", "EUR", "JPY"}


@case
def format_money_currencies():
    assert format_money(1234.5) == "$1,234.50" and format_money(1234.5, "USD") == "$1,234.50"
    assert format_money(1234.5, "EUR") == "\u20ac1,234.50"
    assert format_money(1234.5, currency="JPY") == "\u00a51,234" and format_money(1234.6, "JPY") == "\u00a51,235"
    assert raises(ValueError, format_money, 1, "GBP")


@case
def receipt_default_unchanged():
    assert order_total(ITEMS, 0.1) == 1325.5
    assert render_receipt(ITEMS, 0.1) == "tea x2: $5.00\npot x1: $1,200.00\nTOTAL: $1,325.50"


@case
def receipt_threads_currency():
    assert render_receipt(ITEMS, 0.1, currency="EUR") == "tea x2: \u20ac5.00\npot x1: \u20ac1,200.00\nTOTAL: \u20ac1,325.50"
    assert render_receipt(ITEMS, 0.1, "JPY").endswith("TOTAL: \u00a51,326")
    assert raises(ValueError, render_receipt, ITEMS, 0.1, "GBP")


finish()
