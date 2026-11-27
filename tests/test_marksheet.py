"""Pure save-path for the class marksheet grid: no Streamlit, no network."""
import unittest
import pandas as pd
from database import build_marksheet_records

TOPIC_IDS = {(10, "Mathematics", "Real Numbers"): (1, 1),
             (10, "Mathematics", "Polynomials"): (2, 1)}
LABELS = {"A · Class 10 · ID 1": 1, "B · Class 10 · ID 2": 2}


def grid(rows: dict) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index")


class MarksheetRecords(unittest.TestCase):
    def build(self, edited, outs, ticked):
        return build_marksheet_records(
            edited, LABELS, ticked, outs, TOPIC_IDS,
            "Mathematics", 10, "Weekly 2", "2026-12-02", "Weekly Test",
        )

    def test_blank_cells_skipped_and_raw_marks_converted(self):
        edited = grid({
            "A · Class 10 · ID 1": {"Real Numbers": 15.0, "Polynomials": None},
            "B · Class 10 · ID 2": {"Real Numbers": None, "Polynomials": 18.0},
        })
        records, conversions, errors = self.build(
            edited, {"Real Numbers": 20.0, "Polynomials": 20.0},
            ["Real Numbers", "Polynomials"])
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 2)
        first = next(r for r in records if r["student_id"] == 1)
        self.assertEqual(first["score"], 75.0)          # 15/20 -> 75%
        self.assertEqual(first["raw_score"], 15.0)
        self.assertEqual(first["raw_max"], 20.0)
        self.assertEqual(first["topic_id"], 1)
        self.assertEqual(first["exam"], "Weekly 2")
        second = next(r for r in records if r["student_id"] == 2)
        self.assertEqual(second["score"], 90.0)         # 18/20 -> 90%
        self.assertEqual(second["topic_id"], 2)
        self.assertEqual(len(conversions), 2)

    def test_zero_is_a_mark_not_a_blank(self):
        records, _, errors = self.build(
            grid({"A · Class 10 · ID 1": {"Real Numbers": 0.0}}),
            {"Real Numbers": 100.0}, ["Real Numbers"])
        self.assertEqual(errors, [])
        self.assertEqual(records[0]["score"], 0.0)

    def test_out_of_range_cell_blocks_with_clear_error(self):
        records, _, errors = self.build(
            grid({"A · Class 10 · ID 1": {"Real Numbers": 25.0}}),
            {"Real Numbers": 20.0}, ["Real Numbers"])
        self.assertEqual(records, [])                   # nothing lands
        self.assertTrue(errors)
        self.assertIn("between 0 and 20", errors[0])
        self.assertIn("A ·", errors[0])

    def test_zero_out_of_is_rejected(self):
        records, _, errors = self.build(
            grid({"A · Class 10 · ID 1": {"Real Numbers": 10.0}}),
            {"Real Numbers": 0.0}, ["Real Numbers"])
        self.assertEqual(records, [])
        self.assertTrue(any("above 0" in e for e in errors))

    def test_unknown_row_label_is_ignored(self):
        records, _, errors = self.build(
            grid({"Ghost · X · ID 99": {"Real Numbers": 10.0}}),
            {"Real Numbers": 100.0}, ["Real Numbers"])
        self.assertEqual((records, errors), ([], []))


if __name__ == "__main__":
    unittest.main()
