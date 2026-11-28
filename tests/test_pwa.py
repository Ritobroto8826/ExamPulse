"""PWA polish: manifest, icons, static serving and the head-injection markup."""
import json
import unittest
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


class ManifestTests(unittest.TestCase):
    def test_manifest_fields_and_icons_exist(self):
        data = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "BrightSteps Tuition")
        self.assertEqual(data["short_name"], "BrightSteps")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["theme_color"], "#7C3AED")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        purposes = {icon.get("purpose", "any") for icon in data["icons"]}
        self.assertIn("maskable", purposes)
        for icon in data["icons"]:
            self.assertTrue(icon["src"].startswith("/app/static/"), icon["src"])
            rel = icon["src"].removeprefix("/app/static/")
            self.assertTrue((STATIC / rel).is_file(), icon["src"])

    def test_icon_sizes_and_ios_icon_is_opaque(self):
        expected = {
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "icon-maskable-512.png": (512, 512),
            "apple-touch-icon.png": (180, 180),
        }
        for name, size in expected.items():
            with Image.open(STATIC / name) as img:
                self.assertEqual(img.size, size, name)
        # iOS fills transparent pixels with black — the touch icon must be opaque.
        with Image.open(STATIC / "apple-touch-icon.png") as img:
            self.assertEqual(img.getpixel((0, 0))[3], 255)

    def test_static_serving_enabled(self):
        config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("enableStaticServing = true", config)


class InjectionTests(unittest.TestCase):
    def test_app_declares_manifest_and_touch_icon(self):
        # Module-level injection runs before the settings gate, so no cloud patch needed.
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(at.exception, str(at.exception))
        markup = " ".join(str(m.value) for m in at.markdown)
        self.assertIn('rel="manifest"', markup)
        self.assertIn('rel="apple-touch-icon"', markup)
        self.assertIn("apple-mobile-web-app-capable", markup)
        # Chromium only honours <head> links — the guarded append must ship too.
        self.assertIn("document.head", markup)
        self.assertIn("/app/static/manifest.json", markup)


if __name__ == "__main__":
    unittest.main()
