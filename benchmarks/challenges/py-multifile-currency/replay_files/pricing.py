"""Price arithmetic and formatting."""
from shop.config import SUPPORTED_CURRENCIES


def order_total(items, tax_rate):
    """``items`` is a list of (name, unit_price, quantity)."""
    subtotal = sum(price * qty for _, price, qty in items)
    return round(subtotal * (1 + tax_rate), 2)


def format_money(amount, currency="USD"):
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency}")
    if currency == "JPY":
        return f"\u00a5{amount:,.0f}"
    symbol = {"USD": "$", "EUR": "\u20ac"}[currency]
    return f"{symbol}{amount:,.2f}"
