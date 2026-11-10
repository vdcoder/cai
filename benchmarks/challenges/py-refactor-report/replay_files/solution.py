"""Plain-text financial report rendering."""

def format_row(name, amount):
    return name.strip().title().ljust(12)[:12] + " | " + f"{amount:>10,.2f}"


def render_sales(rows):
    lines = []
    for name, amount in rows:
        lines.append(format_row(name, amount))
    return "\n".join(lines)


def render_costs(rows):
    lines = []
    for name, amount in rows:
        lines.append(format_row(name, -amount))
    return "\n".join(lines)


def render_summary(sales, costs):
    total_sales = sum(amount for _, amount in sales)
    total_costs = sum(amount for _, amount in costs)
    lines = [
        format_row("total sales", total_sales),
        format_row("total costs", -total_costs),
        format_row("net", total_sales - total_costs),
    ]
    return "\n".join(lines)
