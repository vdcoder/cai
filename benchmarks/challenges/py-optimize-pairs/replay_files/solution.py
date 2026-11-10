from collections import Counter


def count_pairs(nums, target):
    """Number of index pairs i < j with nums[i] + nums[j] == target."""
    seen = Counter()
    count = 0
    for n in nums:
        count += seen[target - n]
        seen[n] += 1
    return count
