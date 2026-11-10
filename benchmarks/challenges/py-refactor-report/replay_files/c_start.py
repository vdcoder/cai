"""Plain-text financial report rendering."""

# #defer format_row_impl
# the single place that knows the row layout
# #end


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
