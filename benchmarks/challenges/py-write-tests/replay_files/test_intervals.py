import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from intervals import merge_intervals


class MergeIntervalsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])

    def test_unsorted_input(self):
        self.assertEqual(merge_intervals([[5, 6], [1, 2]]), [[1, 2], [5, 6]])

    def test_touching_intervals_merge(self):
        self.assertEqual(merge_intervals([[1, 3], [3, 5]]), [[1, 5]])

    def test_contained_interval(self):
        self.assertEqual(merge_intervals([[1, 10], [2, 3]]), [[1, 10]])


if __name__ == "__main__":
    unittest.main()
