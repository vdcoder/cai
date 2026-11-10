from collections import OrderedDict


class LRUCache:
    """Mapping with a fixed capacity that evicts the least recently used key.

    ``get`` and ``put`` both count as a use. ``capacity`` must be >= 1
    (``ValueError`` otherwise). ``len(cache)`` is the number of stored keys."""

    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._data = OrderedDict()

    def get(self, key, default=None):
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value):
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __len__(self):
        return len(self._data)
