import tempfile
import unittest
from pathlib import Path

from report_worker.user_profiles import UserProfileStore, infer_asset_role


class UserProfileTests(unittest.TestCase):
    def test_infers_asset_roles_from_arabic_and_english_text(self):
        self.assertEqual(infer_asset_role("هذا ختم الجهة"), "stamp")
        self.assertEqual(infer_asset_role("صورة الغلاف cover"), "cover")
        self.assertEqual(infer_asset_role("خلفية خفيفة"), "background")
        self.assertEqual(infer_asset_role("شعار المؤسسة"), "logo")

    def test_saves_profile_and_persistent_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "logo.jpg"
            image.write_bytes(b"jpg")
            store = UserProfileStore(root)
            store.save(123, {"preferred_theme_id": "official-formal"})
            asset = store.add_asset(123, image, "logo.jpg", "logo")
            profile = store.get(123)
            self.assertEqual(profile["preferred_theme_id"], "official-formal")
            self.assertEqual(profile["assets"], [asset])
            self.assertTrue(Path(asset["path"]).exists())


if __name__ == "__main__":
    unittest.main()
