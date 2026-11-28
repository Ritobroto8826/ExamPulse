"""PWA polish: manifest, icons, static serving and the head-injection markup."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from settings import Settings

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CONFIG = Settings("https://project.example.test", "sb_publishable_unit_tests_only", "https://app.example.test")


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

    def test_install_page_links_manifest_from_real_head(self):
        # Chromium only reads <link rel=manifest> from a parsed <head> — the
        # install page ships one natively (the app itself can't touch its head).
        html = (STATIC / "install.html").read_text(encoding="utf-8")
        self.assertTrue(html.lower().startswith("<!doctype html>"))
        head = html.split("</head>")[0]
        self.assertIn('<link rel="manifest" href="/app/static/manifest.json">', head)
        self.assertIn('<link rel="apple-touch-icon" href="/app/static/apple-touch-icon.png">', head)
        self.assertIn('name="apple-mobile-web-app-capable"', head)
        self.assertIn('name="theme-color"', head)


class InjectionTests(unittest.TestCase):
    def test_page_icon_is_served_from_static(self):
        # A file-path page_icon depends on the media manager; the static URL
        # resolves directly and gives Chrome one stable href to cache.
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('page_icon="/app/static/icon-192.png"', source)

    def test_login_page_offers_install_link(self):
        # The login hero (with the install CTA) only renders past the
        # settings gate — patch it exactly like test_ui_cloud does.
        with patch("settings.load_settings", return_value=CONFIG), patch(
            "auth.load_settings", return_value=CONFIG
        ):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(at.exception, str(at.exception))
        markup = " ".join(str(m.value) for m in at.markdown)
        self.assertIn('href="/app/static/install.html"', markup)
        self.assertIn("Install as app", markup)

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
