def count_pairs(nums, target):
    """Number of index pairs i < j with nums[i] + nums[j] == target."""
    count = 0
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                count += 1
    return count
