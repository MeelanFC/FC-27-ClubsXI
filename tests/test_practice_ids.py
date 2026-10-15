import testenv  # noqa: F401  (test settings, must come first)
import unittest

from clubsxi import strength


class IsPracticeTests(unittest.TestCase):
    def test_single_id(self):
        self.assertTrue(strength.is_practice("100002", "100002"))
        self.assertFalse(strength.is_practice("100001", "100002"))

    def test_both_game_years_count_as_practice(self):
        setting = "100004, 100002"
        self.assertTrue(strength.is_practice("100004", setting))
        self.assertTrue(strength.is_practice("100002", setting))
        self.assertFalse(strength.is_practice("100001", setting))
        self.assertFalse(strength.is_practice("100003", setting))

    def test_empty_setting_means_no_practice_club(self):
        self.assertFalse(strength.is_practice("100002", None))
        self.assertFalse(strength.is_practice("100002", ""))


if __name__ == "__main__":
    unittest.main()
