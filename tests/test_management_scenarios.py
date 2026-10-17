import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "05_escenarios_gerenciales.ipynb"


def load_scenario_functions():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    first_code_cell = next(
        cell for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    namespace = {}
    exec(compile("".join(first_code_cell["source"]), str(NOTEBOOK), "exec"), namespace)
    return namespace


class ManagementScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_scenario_functions()

    def sample_plan(self):
        return pd.DataFrame(
            [
                {
                    "SKU": "NORMAL",
                    "DESCRIPCION": "Cup",
                    "mu": 2.0,
                    "sigma": 1.0,
                    "z_aplicado": 1.0,
                    "EXIST_W11": 5.0,
                    "TRANSITO": 10.0,
                    "FACTOR": 2.0,
                    "COSTO_UNITARIO": 3.0,
                },
                {
                    "SKU": "ZERO",
                    "DESCRIPCION": "No demand",
                    "mu": 0.0,
                    "sigma": 0.0,
                    "z_aplicado": 1.0,
                    "EXIST_W11": 4.0,
                    "TRANSITO": 0.0,
                    "FACTOR": 1.0,
                    "COSTO_UNITARIO": np.nan,
                },
            ]
        )

    def test_duplicate_skus_are_rejected_not_double_counted(self):
        plan = pd.concat([self.sample_plan(), self.sample_plan().iloc[[0]]])
        with self.assertRaisesRegex(ValueError, "duplic"):
            self.scenarios["validate_plan"](plan)

    def test_unknown_cost_remains_unvalued(self):
        plan = self.scenarios["validate_plan"](self.sample_plan())
        self.assertTrue(np.isnan(plan.loc[plan["SKU"] == "ZERO", "COSTO_UNITARIO"].iloc[0]))
        with self.assertRaisesRegex(ValueError, "negativ|finito"):
            self.scenarios["validate_plan"](
                self.sample_plan().assign(EXIST_W11=[-1.0, 4.0])
            )

    def test_replenishment_keeps_physical_and_transit_separate(self):
        plan = self.scenarios["validate_plan"](self.sample_plan())
        result = self.scenarios["replenishment_scenario"](plan, 1.0)
        normal = result.set_index("SKU").loc["NORMAL"]
        self.assertEqual(normal["physical_units"], 5.0)
        self.assertEqual(normal["transit_units"], 10.0)
        self.assertEqual(normal["available_units"], 15.0)
        self.assertEqual(normal["physical_only_units"], 5.0)

    def test_zero_demand_has_undefined_coverage(self):
        plan = self.scenarios["validate_plan"](self.sample_plan())
        result = self.scenarios["replenishment_scenario"](plan, 1.0)
        zero = result.set_index("SKU").loc["ZERO"]
        self.assertTrue(np.isnan(zero["coverage_weeks"]))

    def test_replenishment_does_not_order_above_reorder_point(self):
        plan = pd.DataFrame(
            [{
                "SKU": "BETWEEN",
                "DESCRIPCION": "Cup",
                "mu": 1.0,
                "sigma": 0.0,
                "z_aplicado": 0.0,
                "EXIST_W11": 15.0,
                "TRANSITO": 0.0,
                "FACTOR": 1.0,
                "COSTO_UNITARIO": 2.0,
            }]
        )
        result = self.scenarios["replenishment_scenario"](plan, 1.0).iloc[0]
        self.assertGreater(result["available_units"], result["rop_scenario"])
        self.assertLess(result["available_units"], result["target_scenario"])
        self.assertEqual(result["order_units"], 0.0)

    def test_liquidation_requires_whitelist_and_protects_suspected_spares(self):
        plan = self.scenarios["validate_plan"](
            pd.DataFrame(
                [
                    {
                        "SKU": "SPARE",
                        "DESCRIPCION": "Filter replacement spare",
                        "mu": 0,
                        "sigma": 0,
                        "z_aplicado": 1,
                        "EXIST_W11": 3,
                        "TRANSITO": 0,
                        "FACTOR": 1,
                        "COSTO_UNITARIO": 4,
                    },
                    {
                        "SKU": "NORMAL",
                        "DESCRIPCION": "Paper cup",
                        "mu": 0,
                        "sigma": 0,
                        "z_aplicado": 1,
                        "EXIST_W11": 5,
                        "TRANSITO": 2,
                        "FACTOR": 1,
                        "COSTO_UNITARIO": 2,
                    },
                ]
            )
        )
        history = pd.DataFrame(
            {"SKU": ["SPARE", "NORMAL"], **{f"wk{i}": [0, 0] for i in range(1, 27)}}
        )

        review = self.scenarios["liquidation_review"](plan, history)
        self.assertEqual(review["approved_release_units"].sum(), 0)
        self.assertEqual(review.set_index("SKU").loc["SPARE", "approved_release_units"], 0)
        self.assertTrue(review.set_index("SKU").loc["SPARE", "suspected_spare"])

        approved = self.scenarios["liquidation_review"](
            plan, history, approved_skus={"NORMAL"}
        ).set_index("SKU")
        self.assertEqual(approved.loc["NORMAL", "approved_release_units"], 5)
        self.assertEqual(approved.loc["SPARE", "approved_release_units"], 0)
        self.assertEqual(approved.loc["NORMAL", "transit_units_excluded"], 2)

    def test_five_scenarios_are_explicitly_defined(self):
        self.assertEqual(len(self.scenarios["SCENARIO_DEFINITIONS"]), 5)

    def test_missing_history_is_not_misclassified_as_inactivity(self):
        plan = self.scenarios["validate_plan"](self.sample_plan())
        history = pd.DataFrame(
            {"SKU": ["NORMAL", "ZERO"], **{f"wk{i}": [0, 0] for i in range(1, 27)}}
        )
        history.loc[0, "wk26"] = np.nan
        review = self.scenarios["liquidation_review"](plan, history).set_index("SKU")
        self.assertFalse(review.loc["NORMAL", "activity_known"])
        self.assertFalse(review.loc["NORMAL", "review_candidate"])


if __name__ == "__main__":
    unittest.main()
