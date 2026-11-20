# ###########################################################################
# ####   LEGACY-1.9.5   Delete this whole file together with legacy.py.  ####
# ###########################################################################
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import legacy
import toastfit
import toasts

VALUES = {"min_version": "10.10.10", "reason_max": 200, "per_day": 1000}
OLD_ADDON_TITLES = ("Auth Failed", "Report failed")


class LegacyTests(unittest.TestCase):
    def test_legacy_errors_fit_old_addons(self):
        for key in legacy.ERRORS:
            body = {}
            legacy.add_error(body, key, **VALUES)
            for title in OLD_ADDON_TITLES:
                with self.subTest(key=key, title=title):
                    self.assertEqual(toastfit.problems(title, f"000: {body['error']}"), [])

    def test_legacy_keys_exist(self):
        self.assertEqual(set(legacy.ERRORS) - set(toasts.TOASTS), set())


if __name__ == "__main__":
    unittest.main()
