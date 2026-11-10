"""Tiny statistics helpers: the "before" state of the CAI demo.

Everything below the first function was written top to bottom, append-only.
Run `cai --run --test` in this directory to consolidate it.
"""


def mean(values):
    if not values:
        raise ValueError("mean of an empty sequence")
    return sum(values) / len(values)


# #defer median_fn
# median(values): middle element, or mean of the two middle elements
# #end


# #defer mode_fn
# mode(values): most common element -- maybe
# #end

# #run before
# import metrics
# print("median defined:", hasattr(metrics, "median"))
# #end

# #wait
# Should median([]) raise or return None? mean() raises ValueError, so stay
# consistent and raise. mode() is not needed by anyone yet: drop it.
# #end

# #evolve median_fn
# def median(values):
#     if not values:
#         raise ValueError("median of an empty sequence")
#     ordered = sorted(values)
#     mid = len(ordered) // 2
#     if len(ordered) % 2:
#         return ordered[mid]
#     return mean(ordered[mid - 1:mid + 1])
# #end

# #drop mode_fn
# #end

# #run after
# import metrics
# print("median defined:", hasattr(metrics, "median"))
# print("median([5, 1, 4, 2]) ->", metrics.median([5, 1, 4, 2]))
# #end

# #run empty_input
# import metrics
# metrics.median([])
# #end

# #test mean_and_median
# import metrics
# assert metrics.mean([1, 2, 3]) == 2
# assert metrics.median([5, 1, 4]) == 4 and metrics.median([5, 1, 4, 2]) == 3.0
# for fn in (metrics.mean, metrics.median):
#     try:
#         fn([])
#     except ValueError:
#         continue
#     raise AssertionError(fn.__name__ + " accepted an empty list")
# #end
