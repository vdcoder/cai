"""Plain-text financial report rendering."""


def render_sales(rows):
    lines = []
    for name, amount in rows:
        lines.append(name.strip().title().ljust(12)[:12] + " | " + f"{amount:>10,.2f}")
    return "\n".join(lines)


def render_costs(rows):
    lines = []
    for name, amount in rows:
        lines.append(name.strip().title().ljust(12)[:12] + " | " + f"{-amount:>10,.2f}")
    return "\n".join(lines)


def render_summary(sales, costs):
    total_sales = sum(amount for _, amount in sales)
    total_costs = sum(amount for _, amount in costs)
    lines = [
        "total sales".strip().title().ljust(12)[:12] + " | " + f"{total_sales:>10,.2f}",
        "total costs".strip().title().ljust(12)[:12] + " | " + f"{-total_costs:>10,.2f}",
        "net".strip().title().ljust(12)[:12] + " | " + f"{total_sales - total_costs:>10,.2f}",
    ]
    return "\n".join(lines)
