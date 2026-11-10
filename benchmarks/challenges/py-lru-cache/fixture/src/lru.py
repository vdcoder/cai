class LRUCache:
    """Mapping with a fixed capacity that evicts the least recently used key.

    ``get`` and ``put`` both count as a use. ``capacity`` must be >= 1
    (``ValueError`` otherwise). ``len(cache)`` is the number of stored keys."""

    def __init__(self, capacity):
        raise NotImplementedError

    def get(self, key, default=None):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
