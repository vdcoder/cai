def find_index(items, target):
    """Return the index of ``target`` in the sorted list ``items``, or -1."""
    lo, hi = 0, len(items)
    while lo < hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
