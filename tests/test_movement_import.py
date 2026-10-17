from __future__ import annotations

from io import BytesIO
import unittest

import pandas as pd

from movement_import import prepare_movement_batches, read_movement_file


class MovementImportTests(unittest.TestCase):
    def test_normalizes_and_aggregates_rows_by_week_and_sku(self) -> None:
        frame = pd.DataFrame(
            {
                " SKU ": ["A", "A", "B"],
                "Semana": ["2026-W40", "2026-W40", ""],
                "Consumo": ["2", "3", "1"],
            }
        )
        batches = prepare_movement_batches(
            frame, "consumo", {"A", "B"}, "2026-W41"
        )
        self.assertEqual(
            batches,
            [("2026-W40", {"A": 5.0}), ("2026-W41", {"B": 1.0})],
        )

    def test_rejects_unknown_skus_instead_of_silently_dropping_them(self) -> None:
        frame = pd.DataFrame({"SKU": ["MISSING"], "recibido": [1]})
        with self.assertRaisesRegex(ValueError, "fuera del plan"):
            prepare_movement_batches(
                frame, "recepcion", {"A"}, "2026-W41"
            )

    def test_rejects_invalid_week_and_negative_quantity(self) -> None:
        invalid_week = pd.DataFrame(
            {"SKU": ["A"], "semana": ["2026-W54"], "consumo": [1]}
        )
        with self.assertRaisesRegex(ValueError, "Semana no válida"):
            prepare_movement_batches(
                invalid_week, "consumo", {"A"}, "2026-W41"
            )
        invalid_quantity = pd.DataFrame({"SKU": ["A"], "consumo": [-1]})
        with self.assertRaisesRegex(ValueError, "números finitos no negativos"):
            prepare_movement_batches(
                invalid_quantity, "consumo", {"A"}, "2026-W41"
            )

    def test_reads_csv_upload(self) -> None:
        uploaded = BytesIO(b"SKU,recibido\nA,2\n")
        frame = read_movement_file(uploaded, "recepciones.csv")
        self.assertEqual(frame.to_dict(orient="records"), [{"SKU": "A", "recibido": "2"}])

    def test_reads_xlsx_upload(self) -> None:
        uploaded = BytesIO()
        pd.DataFrame({"SKU": ["A"], "consumo": [2]}).to_excel(
            uploaded, index=False
        )
        uploaded.seek(0)
        frame = read_movement_file(uploaded, "consumos.xlsx")
        self.assertEqual(frame.to_dict(orient="records"), [{"SKU": "A", "consumo": 2}])


if __name__ == "__main__":
    unittest.main()
