def count_pairs(nums, target):
    """Number of index pairs i < j with nums[i] + nums[j] == target."""
    seen = set()
    count = 0
    for n in nums:
        if target - n in seen:
            count += 1
        seen.add(n)
    return count
