"""Receipt rendering."""
from shop.pricing import format_money, order_total


def render_receipt(items, tax_rate, currency="USD"):
    lines = [f"{name} x{qty}: {format_money(price * qty, currency)}" for name, price, qty in items]
    lines.append(f"TOTAL: {format_money(order_total(items, tax_rate), currency)}")
    return "\n".join(lines)
