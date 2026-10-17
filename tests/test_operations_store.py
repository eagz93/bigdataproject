from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from operations_store import (
    apply_movements,
    approve_orders,
    breaker_paused,
    get_approvals,
    get_inventory,
    initialize,
    movement_history,
    pilot_history,
    record_pilot_metrics,
    replace_movements_batch,
)


class OperationsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "operations.sqlite3"
        self.plan = pd.DataFrame(
            {"SKU": ["A", "B"], "EXIST_W11": [100, 40], "TRANSITO": [50, 20]}
        )
        initialize(self.db_path, self.plan)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_reinitializing_preserves_operational_balances(self) -> None:
        apply_movements(self.db_path, "2026-W40", "consumo", {"A": 10}, "planner", "planner")
        initialize(self.db_path, self.plan)
        self.assertEqual(get_inventory(self.db_path)["A"], (90, 50))

    def test_movement_history_filters_kind_orders_and_limits_saved_rows(self) -> None:
        self.assertTrue(movement_history(self.db_path, "consumo").empty)
        apply_movements(self.db_path, "2026-W40", "consumo", {"A": 3}, "admin", "admin")
        apply_movements(self.db_path, "2026-W41", "consumo", {"B": 2}, "admin", "admin")
        apply_movements(self.db_path, "2026-W41", "recepcion", {"A": 4}, "admin", "admin")
        before = get_inventory(self.db_path)
        history = movement_history(self.db_path, "consumo", limit=1)
        self.assertEqual(history[["sku", "week", "quantity"]].values.tolist(), [["B", "2026-W41", 2]])
        self.assertEqual(history.iloc[0]["updated_by"], "admin")
        self.assertEqual(get_inventory(self.db_path), before)
        with self.assertRaises(ValueError):
            movement_history(self.db_path, "invalid")

    def test_pilot_history_returns_persisted_metrics_latest_first(self) -> None:
        self.assertTrue(pilot_history(self.db_path).empty)
        record_pilot_metrics(self.db_path, "2026-W40", 12, 100, 10, 100, "admin")
        record_pilot_metrics(self.db_path, "2026-W41", 13, 100, 10, 100, "admin")
        history = pilot_history(self.db_path, limit=1)
        self.assertEqual(history["week"].tolist(), ["2026-W41"])
        self.assertEqual(history.iloc[0]["above_limit"], 1)
        self.assertEqual(history.iloc[0]["entered_by"], "admin")

    def test_movement_updates_are_idempotent_and_replace_the_week(self) -> None:
        apply_movements(self.db_path, "2026-W40", "recepcion", {"A": 15}, "warehouse", "warehouse")
        apply_movements(self.db_path, "2026-W40", "recepcion", {"A": 15}, "warehouse", "warehouse")
        self.assertEqual(get_inventory(self.db_path)["A"], (115, 35))
        apply_movements(self.db_path, "2026-W40", "recepcion", {"A": 12}, "warehouse", "warehouse")
        self.assertEqual(get_inventory(self.db_path)["A"], (112, 38))

    def test_movement_rejects_consumption_or_receipt_above_stock(self) -> None:
        with self.assertRaises(ValueError):
            apply_movements(self.db_path, "2026-W40", "consumo", {"A": 101}, "planner", "planner")
        with self.assertRaises(ValueError):
            apply_movements(self.db_path, "2026-W40", "recepcion", {"A": 51}, "warehouse", "warehouse")
        self.assertEqual(get_inventory(self.db_path)["A"], (100, 50))

    def test_large_order_override_requires_reason_and_is_auditable(self) -> None:
        order = {
            "sku": "A",
            "suggested_cases": 10,
            "approved_cases": 12,
            "reason": "",
        }
        with self.assertRaisesRegex(ValueError, "justifique"):
            approve_orders(self.db_path, "2026-W40", [order], "buyer", "planner")
        order["reason"] = "Campaña comercial autorizada"
        approve_orders(self.db_path, "2026-W40", [order], "buyer", "planner")
        self.assertEqual(get_approvals(self.db_path, "2026-W40")["A"]["approved_cases"], 12)

    def test_two_consecutive_weeks_above_limit_pause_recommendations(self) -> None:
        for week in ("2026-W40", "2026-W41"):
            triggered = record_pilot_metrics(
                self.db_path, week, 20, 100, 10, 100, "warehouse"
            )
        self.assertTrue(triggered)
        self.assertTrue(breaker_paused(self.db_path))

    def test_pilot_limit_is_strict_and_exact_for_unequal_exposures(self) -> None:
        cases = [
            (23, 100, 20, 100, False),
            (46, 200, 20, 100, False),
            (45, 200, 20, 100, False),
            (47, 200, 20, 100, True),
            (1, 200, 0, 100, True),
            (0, 200, 0, 100, False),
        ]
        for index, (pilot_events, pilot_exposure, control_events, control_exposure, above) in enumerate(cases):
            with self.subTest(counts=(pilot_events, pilot_exposure, control_events, control_exposure)):
                db_path = Path(self.tempdir.name) / f"boundary_{index}.sqlite3"
                initialize(db_path, self.plan)
                for week in ("2026-W40", "2026-W41"):
                    triggered = record_pilot_metrics(
                        db_path, week, pilot_events, pilot_exposure,
                        control_events, control_exposure, "admin",
                    )
                self.assertEqual(bool(pilot_history(db_path).iloc[0]["above_limit"]), above)
                self.assertEqual(triggered, above)
                self.assertEqual(breaker_paused(db_path), above)

    def test_weekly_import_replaces_omitted_skus_idempotently(self) -> None:
        apply_movements(
            self.db_path, "2026-W40", "consumo",
            {"A": 10, "B": 5}, "warehouse", "warehouse",
        )
        batch = [("2026-W40", {"A": 8})]
        replace_movements_batch(
            self.db_path, "consumo", batch, "warehouse", "warehouse"
        )
        replace_movements_batch(
            self.db_path, "consumo", batch, "warehouse", "warehouse"
        )
        self.assertEqual(get_inventory(self.db_path), {"A": (92, 50), "B": (40, 20)})

    def test_weekly_import_rolls_back_all_weeks_on_invalid_movement(self) -> None:
        batches = [
            ("2026-W40", {"A": 10}),
            ("2026-W41", {"A": 5, "B": 21}),
        ]
        with self.assertRaisesRegex(ValueError, "tránsito disponible"):
            replace_movements_batch(
                self.db_path, "recepcion", batches, "warehouse", "warehouse"
            )
        self.assertEqual(get_inventory(self.db_path), {"A": (100, 50), "B": (40, 20)})


if __name__ == "__main__":
    unittest.main()
