def merge_intervals(intervals):
    """Merge overlapping or touching ``[start, end]`` intervals.

    Returns a new list of lists sorted by start; the input may be in any order."""
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = end
        else:
            result.append([start, end])
    return result
