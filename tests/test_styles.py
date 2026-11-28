"""Dark-mode floating layers and the lively palette.

These elements portal outside the styled containers; without explicit
background/colour rules they render light-on-light in dark mode — the exact
bug behind the invisible exam-date calendar and help popups. Palette tests
lock the red/yellow/green tokens so future tweaks keep the app lively.
"""
import re
import unittest
from pathlib import Path

from theme import DARK, LIGHT

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

    def test_primary_button_uses_vivid_gradient(self):
        match = re.search(r'button\[kind="primary"\][^{]*\{([^}]*)\}', CSS)
        self.assertIsNotNone(match, "primary button rule missing")
        self.assertIn("linear-gradient", match.group(1),
                      "primary actions must carry the violet→blue gradient")
        self.assertIn("!important", match.group(1))

    def test_selected_nav_pill_uses_gradient(self):
        match = re.search(
            r'\[data-testid="stSidebar"\][^{]*\[data-selected="true"\][^{]*\{([^}]*)\}',
            CSS)
        self.assertIsNotNone(match, "selected nav pill rule missing")
        self.assertIn("linear-gradient", match.group(1))

    def test_threshold_slider_track_is_red_yellow_green(self):
        match = re.search(
            r'\[data-testid="stSlider"\][^{]*div:has\(\+ \[role="slider"\]\)[^{]*\{([^}]*)\}',
            CSS)
        self.assertIsNotNone(match, "slider rainbow track rule missing")
        for token in ("var(--coral)", "var(--amber)", "var(--green)"):
            self.assertIn(token, match.group(1),
                          f"slider rail must pass through {token}")


class MobileLayoutTests(unittest.TestCase):
    """Phone widths: readable type floor, thumb-sized targets, tighter spacing."""

    @staticmethod
    def _mobile_blocks():
        # The two blocks in this file differ only by whitespace after @media.
        return re.findall(r"@media\s*\(max-width:768px\)\s*\{(.*?)\n\}", CSS, re.S)

    def test_no_undersized_captions_on_phones(self):
        # Both 768px blocks win over base rules — neither may drop below 11px.
        blocks = self._mobile_blocks()
        self.assertEqual(len(blocks), 2, "expected both max-width:768px media blocks")
        for body in blocks:
            self.assertNotIn("font-size:9px", body)
            self.assertNotIn("font-size:10px", body,
                             "mobile captions must keep an 11px floor")

    def test_mobile_touch_targets_are_thumb_sized(self):
        joined = "\n".join(self._mobile_blocks())
        self.assertIn('[data-testid="stRadioOption"] { min-height:44px', joined)
        self.assertIn('[data-testid="stExpander"] div[role="button"] { min-height:44px', joined)
        self.assertIn('[data-testid="stTabs"] button { min-height:44px', joined)
        self.assertIn('input[type="text"]', joined)

    def test_mobile_spacing_is_tighter_than_desktop(self):
        # Bottom padding must clear the fixed tab bar *and* the iOS home
        # indicator, so the last line of content is never covered.
        self.assertIn(
            "padding:4.1rem 14px calc(6.75rem + env(safe-area-inset-bottom))",
            CSS)
        self.assertIn("gap:14px !important", self._mobile_blocks()[0])

    def test_phone_bar_owns_no_extra_height(self):
        # The collapsed widget label can reserve a hidden row; zeroing label
        # and margins keeps the bar's height deterministic (44px options only).
        mobile = self._mobile_blocks()[0]
        self.assertIn('.st-key-nav_mob [data-testid="stWidgetLabel"] { display:none !important; }', mobile)
        self.assertIn('.st-key-nav_mob [data-testid="stRadio"] { width:100%;margin:0 !important; }', mobile)

    def test_phone_nav_bar_is_fixed_to_the_bottom(self):
        # Hidden at desktop widths, fixed and thumb-reachable on phones.
        self.assertIn(".st-key-nav_mob { display:none; }", CSS)
        mobile = self._mobile_blocks()[0]
        self.assertIn(".st-key-nav_mob { display:block;position:fixed;", mobile)
        self.assertIn("bottom:0", mobile)
        self.assertIn(":has(input:checked)", mobile,
                      "active tab needs the selected-pill treatment")


class LayoutAlignmentTests(unittest.TestCase):
    """Desktop: uniform gaps and one card system so grids line up."""

    def test_column_gaps_are_uniform_and_forced(self):
        # Streamlit per-row gap styling must not win over the design system.
        self.assertIn('[data-testid="stHorizontalBlock"] { gap: 20px !important; }',
                      CSS)
        first_block = re.findall(
            r"@media\s*\(max-width:768px\)\s*\{.*?\n\}", CSS, re.S)[0]
        self.assertIn("gap:8px !important", first_block)

    def test_kpi_cards_share_the_card_corner_and_padding(self):
        # KPI tiles and bordered cards are one system: 16px radius, 21px pad.
        match = re.search(r"\.kpi-card\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(match)
        self.assertIn("border-radius:16px", match.group(1))
        self.assertIn("padding:21px", match.group(1))
        self.assertIn("gap:20px", re.search(r"\.kpi-row\s*\{([^}]*)\}", CSS).group(1))

    def test_column_card_containers_stretch_to_equal_heights(self):
        # Every side-by-side bordered card uses height="stretch" (Streamlit
        # 1.67 native equal-height pattern). Full-width cards must not.
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        stretch = source.count('st.container(border=True, height="stretch")')
        plain = source.count("with st.container(border=True):")
        self.assertEqual(stretch, 14,
                         "column-paired card containers need height=\"stretch\"")
        self.assertEqual(plain, 3,
                         "only full-width cards stay content-height")


class FontTests(unittest.TestCase):
    def test_inter_loads_from_google_fonts_with_swap(self):
        # The stack names Inter first, so it must actually load — and @import
        # must precede every rule or the browser drops it.
        index = CSS.index("@import")
        self.assertLess(index, CSS.index("{"),
                        "@import must come before the first rule")
        head = CSS[index:index + 220]
        self.assertIn("fonts.googleapis.com/css2?family=Inter", head)
        self.assertIn("display=swap", head,
                      "font must never block first paint")


class PaletteTests(unittest.TestCase):
    def test_red_yellow_green_are_first_class_in_both_modes(self):
        self.assertEqual(LIGHT["green"], "#22C55E")
        self.assertEqual(LIGHT["amber"], "#F59E0B")
        self.assertEqual(LIGHT["coral"], "#EF4444")
        self.assertEqual(DARK["green"], "#22C55E")
        self.assertEqual(DARK["amber"], "#FBBF24")
        self.assertEqual(DARK["coral"], "#F87171")

    def test_modes_use_distinct_bases_and_shared_violet(self):
        self.assertNotEqual(LIGHT["bg"], DARK["bg"])
        self.assertNotEqual(LIGHT["card"], DARK["card"])
        self.assertEqual(LIGHT["accent"], "#7C3AED")
        self.assertEqual(DARK["accent"], "#A78BFA")


if __name__ == "__main__":
    unittest.main()
