"""Receipt rendering."""
from shop.pricing import format_money, order_total


def render_receipt(items, tax_rate):
    lines = [f"{name} x{qty}: {format_money(price * qty)}" for name, price, qty in items]
    lines.append(f"TOTAL: {format_money(order_total(items, tax_rate))}")
    return "\n".join(lines)
