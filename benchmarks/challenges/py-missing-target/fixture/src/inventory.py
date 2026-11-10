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
