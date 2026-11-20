import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import toastfit
import toasts

VALUES = {"min_version": "10.10.10", "reason_max": 200, "per_day": 1000}
OLD_ADDON_TITLES = ("Auth Failed", "Report failed")
WEBSOCKET_CLOSE_REASON_MAX = 123


class ToastTests(unittest.TestCase):
    def test_every_toast_fits(self):
        for key in toasts.TOASTS:
            toast = toasts.fields(key, **VALUES)
            with self.subTest(key=key):
                self.assertEqual(toastfit.problems(toast["title"], toast["message"]), [])

    def test_every_toast_uses_known_glyphs(self):
        for key in toasts.TOASTS:
            toast = toasts.fields(key, **VALUES)
            with self.subTest(key=key):
                self.assertTrue(toastfit.is_exact(toast["title"] + toast["message"]))

    def test_every_toast_type_is_known(self):
        for key in toasts.TOASTS:
            with self.subTest(key=key):
                self.assertIn(toasts.fields(key, **VALUES)["type"], toasts.TYPE_IDS)

    def test_outdated_client_error_fits_every_old_addon(self):
        for title in OLD_ADDON_TITLES:
            with self.subTest(title=title):
                self.assertEqual(toastfit.problems(title, f"426: {toasts.OUTDATED_CLIENT_ERROR}"), [])

    def test_ban_close_reason_fits_websocket_limit(self):
        self.assertLessEqual(len(toasts.close_reason("banned", **VALUES)), WEBSOCKET_CLOSE_REASON_MAX)


if __name__ == "__main__":
    unittest.main()
