from __future__ import annotations

import ast
from pathlib import Path
import tomllib
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class AppConfigurationTests(unittest.TestCase):
    def test_cors_is_enabled_and_xsrf_protection_remains_enabled(self) -> None:
        config = tomllib.loads(
            (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        )

        self.assertTrue(config["server"]["enableCORS"])
        self.assertTrue(config["server"]["enableXsrfProtection"])

    def test_local_users_file_is_a_fallback_when_streamlit_secrets_are_empty(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_configured_users"
        )
        local_file = Mock(
            is_file=Mock(return_value=True),
            read_text=Mock(return_value='[users.admin]\nrole = "admin"\n'),
        )
        namespace = {
            "LOCAL_USERS_FILE": local_file,
            "st": Mock(secrets={"users": {}}),
            "tomllib": tomllib,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)

        self.assertEqual(namespace["_configured_users"](), {"admin": {"role": "admin"}})

    def test_app_uses_supported_stretch_width_and_no_deprecated_argument(self) -> None:
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        app = ast.parse(source)
        calls = [
            node for node in ast.walk(app)
            if isinstance(node, ast.Call)
        ]
        self.assertFalse(
            any(
                keyword.arg == "use_container_width"
                for call in calls
                for keyword in call.keywords
            )
        )
        width_calls = [
            node for node in calls
            if isinstance(node.func, ast.Attribute)
            and node.func.attr in {"data_editor", "dataframe"}
        ]

        self.assertTrue(width_calls)
        for call in width_calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            self.assertNotIn("use_container_width", keywords)
            self.assertEqual(
                ast.literal_eval(keywords["width"]),
                "stretch",
                msg=f"{call.func.attr} must use width='stretch'",
            )

    def test_admin_role_can_open_planner_and_warehouse_operations(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_require_role"
        )
        namespace: dict[str, object] = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        require_role = namespace["_require_role"]

        self.assertTrue(require_role("admin", {"planner"}))
        self.assertTrue(require_role("admin", {"warehouse"}))
        self.assertTrue(require_role("planner", {"planner"}))
        self.assertFalse(require_role("viewer", {"planner"}))


if __name__ == "__main__":
    unittest.main()
