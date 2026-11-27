"""Dark-mode floating layers (tooltips, date calendar) must carry our tokens.

These elements portal outside the styled containers; without explicit
background/colour rules they render light-on-light in dark mode — the exact
bug behind the invisible exam-date calendar and help popups.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")


class PopupCssTests(unittest.TestCase):
    def test_calendar_container_sets_background(self):
        match = re.search(
            r'\[data-testid="stDateInputCalendar"\]\s*\{([^}]*)\}', CSS)
        self.assertIsNotNone(match, "calendar container rule missing")
        self.assertIn("background", match.group(1),
                      "calendar renders white-on-white without a background")
        self.assertIn("color", match.group(1))

    def test_tooltip_outer_and_inner_layers_forced_visible(self):
        # Both the role=tooltip shell and Streamlit's inner content layer.
        self.assertIn('[data-testid="stTooltipContent"]', CSS)
        match = re.search(r'\[role="tooltip"\][^{]*\{([^}]*)\}', CSS)
        self.assertIsNotNone(match, "tooltip rule missing")
        self.assertIn("background", match.group(1))
        self.assertIn("!important", match.group(1),
                      "inner tooltip layer paints over non-!important rules")

    def test_expander_header_forced_onto_theme_tokens(self):
        # The expander header keeps Streamlit's light-theme white background
        # (config.toml base="light") and hides its label in dark mode.
        match = re.search(
            r'\[data-testid="stExpander"\][^{]*div\[role="button"\][^{]*\{([^}]*)\}',
            CSS)
        self.assertIsNotNone(match, "expander header rule missing")
        self.assertIn("background", match.group(1))
        self.assertIn("!important", match.group(1))
        self.assertIn("color", match.group(1))


if __name__ == "__main__":
    unittest.main()
