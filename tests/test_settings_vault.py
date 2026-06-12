import os
import tempfile
import unittest
from pathlib import Path

from report_worker.settings_vault import SettingsVault


class VaultTests(unittest.TestCase):
    def test_secret_is_preserved_when_blank_update_is_submitted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            vault = SettingsVault(path)
            vault.save({"telegram_bot_token": "telegram-secret"})
            vault.save({"telegram_bot_token": "", "provider": "gemini"})
            self.assertEqual(vault.load()["telegram_bot_token"], "telegram-secret")
            self.assertEqual(vault.public()["telegram_bot_token"], "محفوظ")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
