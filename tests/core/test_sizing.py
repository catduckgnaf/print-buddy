"""Scale and copy-count choices offered in Discord. No slicer: fit checks are stubbed."""
import unittest

from print_buddy.core import orca_adapter as oa
from print_buddy.core import quantity_selection as qs


class ScaleLabelTests(unittest.TestCase):
    def test_whole_and_fractional_percent(self):
        self.assertEqual(oa.scale_label(1), "100%")
        self.assertEqual(oa.scale_label(0.75), "75%")
        self.assertEqual(oa.scale_label(0.986), "98.6%")


class ScaleLadderTests(unittest.TestCase):
    def test_too_small_to_offer(self):
        self.assertEqual(oa._scale_ladder(0.51), [])

    def test_large_maximum_offers_75_and_50(self):
        self.assertEqual(oa._scale_ladder(0.9), [0.9, 0.75, 0.5])

    def test_medium_sits_between_max_and_half(self):
        self.assertEqual(oa._scale_ladder(0.7), [0.7, 0.6, 0.5])

    def test_choices_never_repeat(self):
        ladder = oa._scale_ladder(0.52)
        self.assertEqual(len(set(ladder)), 3)


class ConfirmScaleTests(unittest.TestCase):
    def test_finds_largest_fitting_tenth_of_a_percent(self):
        self.assertEqual(oa._confirm_scale(lambda s: s <= 0.873, 0.95), 0.873)

    def test_bound_that_fits_is_returned_without_search(self):
        calls = []
        self.assertEqual(oa._confirm_scale(lambda s: calls.append(s) or True, 0.9), 0.9)
        self.assertEqual(calls, [0.9])

    def test_bound_under_half_size_gives_up(self):
        self.assertIsNone(oa._confirm_scale(lambda s: True, 0.4))

    def test_one_orca_crash_is_retried(self):
        seen = set()

        def flaky(scale):
            if scale not in seen:
                seen.add(scale)
                raise RuntimeError("bad_rational")
            return True
        self.assertEqual(oa._confirm_scale(flaky, 0.8), 0.8)

    def test_broken_orca_is_not_reported_as_does_not_fit(self):
        def broken(scale):
            raise RuntimeError("orca died")
        with self.assertRaises(RuntimeError):
            oa._confirm_scale(broken, 0.9)


class QuantityTests(unittest.TestCase):
    def test_buttons(self):
        self.assertEqual(oa.quantity_buttons(0), [1])
        self.assertEqual(oa.quantity_buttons(2), [1, 2])
        self.assertEqual(oa.quantity_buttons(6), [1, 2, 6])

    def test_options(self):
        self.assertEqual(qs.quantity_options(1), [("One copy", 1)])
        self.assertEqual(qs.quantity_options(5)[-1], ("Max (5 copies)", 5))

    def test_parse_accepts_plain_phrasing(self):
        self.assertEqual(qs.parse_quantity("3", 4), 3)
        self.assertEqual(qs.parse_quantity("Print 2 copies", 4), 2)

    def test_parse_rejects_vague_or_too_many(self):
        with self.assertRaises(ValueError):
            qs.parse_quantity("a few", 4)
        with self.assertRaisesRegex(ValueError, "will not fit"):
            qs.parse_quantity("9", 4)
