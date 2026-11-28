"""Chart colours must match their legends (dashboard "Score performance")."""
import unittest

import pandas as pd

from charts import score_bar_chart
from theme import palette


class ScoreBarColorTests(unittest.TestCase):
    def test_mastery_bars_are_green_and_weak_bars_red(self):
        # The dashboard legend promises green = at mastery, red = below;
        # bars that render violet break that contract (regression from the
        # lively-palette pass, which recoloured the legend dot only).
        df = pd.DataFrame([
            {"exam_date": "2026-11-23", "score": 40.0},
            {"exam_date": "2026-11-30", "score": 76.0},
        ])
        for theme in ("light", "dark"):
            fig = score_bar_chart(df, "Weekly", threshold=70, theme=theme)
            p = palette(theme)
            by_value = dict(zip(fig.data[0].y, fig.data[0].marker.color))
            self.assertEqual(by_value[76.0], p["green"],
                             f"{theme}: at-mastery bar must match the green legend dot")
            self.assertEqual(by_value[40.0], p["coral"],
                             f"{theme}: below-mastery bar must match the red legend dot")


if __name__ == "__main__":
    unittest.main()
