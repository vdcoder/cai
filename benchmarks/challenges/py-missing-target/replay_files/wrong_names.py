class Inventory:
    """Stock levels per item name."""

    def __init__(self):
        self.stock = {}

    def restock(self, item, qty):
        """Add ``qty`` units; see NOTES.md. Returns the new level."""
        raise NotImplementedError

    def remove(self, item, qty):
        """Take ``qty`` units out; see NOTES.md. Returns the remaining level."""
        raise NotImplementedError

    def restock_item(self, item, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self.stock[item] = self.stock.get(item, 0) + qty
        return self.stock[item]

    def remove_item(self, item, qty):
        if item not in self.stock:
            raise KeyError(item)
        if qty <= 0 or qty > self.stock[item]:
            raise ValueError("invalid quantity")
        left = self.stock[item] - qty
        if left:
            self.stock[item] = left
        else:
            del self.stock[item]
        return left
