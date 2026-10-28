"""#390 Stage 2: the audited surfaces meet the operator-message bar."""
import unittest

from print_handy.core import spoolman_client


class SpoolmanNoticeTests(unittest.TestCase):
    def test_notice_says_what_failed_that_the_print_continues_and_what_to_check(self):
        notice = spoolman_client.UNAVAILABLE_NOTICE
        self.assertIn("Spoolman unavailable", notice)          # what failed
        self.assertIn("the print continues", notice)           # degradation stated
        self.assertIn("services.spoolman_url", notice)         # what to check
        self.assertIn("PB_SPOOLMAN_", notice)                  # where the marker lives


if __name__ == "__main__":
    unittest.main()
