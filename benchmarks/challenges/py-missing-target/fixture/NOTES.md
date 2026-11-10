# Inventory notes (older draft)

- `restock_item(item, qty)`: `qty` must be > 0, otherwise `ValueError`. Adds to the level (unknown items start at 0) and returns the new level.
- `remove_item(item, qty)`: unknown item -> `KeyError`; `qty` <= 0 or more than is in stock -> `ValueError`. Returns the remaining level; an item whose level reaches 0 is deleted from `stock`.
