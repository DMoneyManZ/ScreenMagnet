"""Release dialogs must not expose the development payment/copyright stubs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QLabel
from screenmagnet.settings_window import SettingsWindow

class ReleaseUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_has_real_license_without_fake_payment_or_copyright(self):
        window = SettingsWindow()
        try:
            text = '\n'.join(label.text() for label in window.findChildren(QLabel))
            self.assertIn('GPL-3.0-or-later', text)
            self.assertNotIn('Magnetic Cyber Chameleon', text)
            self.assertNotIn('placeholder donation', text)
        finally:
            window.close()

    def test_frozen_update_button_opens_release_downloads(self):
        with patch('sys.frozen', True, create=True):
            window = SettingsWindow()
            try:
                with patch('screenmagnet.settings_window.QDesktopServices.openUrl') as open_url:
                    window.check_updates_btn.click()
                self.assertEqual(open_url.call_count, 1)
                self.assertEqual(open_url.call_args.args[0].toString(),
                                 'https://github.com/DMoneyManZ/ScreenMagnet/releases')
            finally:
                window.close()

    def test_frozen_tray_check_does_not_start_git_worker(self):
        from types import SimpleNamespace
        from screenmagnet.tray import ScreenMagnetTray
        with patch('sys.frozen', True, create=True):
            window = SettingsWindow()
            subject = SimpleNamespace(settings_window=window, _update_check_worker=None)
            try:
                with patch('screenmagnet.tray.updater.CallWorker', side_effect=AssertionError('Frozen app tried Git update')):
                    ScreenMagnetTray.check_for_updates(subject)
                self.assertIn('Releases', window.update_status_label.text())
            finally:
                window.close()

    def test_support_button_opens_the_official_paypal_recipient(self):
        from urllib.parse import urlsplit, parse_qs
        window = SettingsWindow()
        try:
            with patch('screenmagnet.settings_window.QDesktopServices.openUrl') as open_url:
                window.support_btn.click()
            parsed = urlsplit(open_url.call_args.args[0].toString())
            self.assertEqual(parsed.hostname, 'www.paypal.com')
            query = parse_qs(parsed.query)
            self.assertEqual(query['business'], ['demurphy242@gmail.com'])
            self.assertEqual(query['cmd'], ['_donations'])
            self.assertNotIn('amount', query)
        finally:
            window.close()
