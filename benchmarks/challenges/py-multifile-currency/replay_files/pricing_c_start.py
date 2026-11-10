"""Price arithmetic and formatting."""
from shop.config import SUPPORTED_CURRENCIES


def order_total(items, tax_rate):
    """``items`` is a list of (name, unit_price, quantity)."""
    subtotal = sum(price * qty for _, price, qty in items)
    return round(subtotal * (1 + tax_rate), 2)


def format_money(amount, currency="USD"):
    # #defer money_body
    # validate, then symbol + digits (JPY has no decimals)
    # #end
