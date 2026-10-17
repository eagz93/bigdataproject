from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
import shlex
import tomllib
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_function(filename: str, name: str, namespace: dict):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, filename, "exec"), namespace)
    return namespace[name]


class DockerStartupTests(unittest.TestCase):
    def test_spark_entrypoint_has_posix_shebang(self) -> None:
        script = (ROOT / "docker-entrypoint.spark.sh").read_bytes()
        self.assertTrue(script.startswith(b"#!/bin/sh\n"))

    def test_spark_entrypoint_uses_lf_and_build_normalizes_windows_checkouts(self) -> None:
        self.assertNotIn(b"\r", (ROOT / "docker-entrypoint.spark.sh").read_bytes())
        dockerfile = (ROOT / "Dockerfile.spark").read_text(encoding="utf-8")
        self.assertIn("sed -i 's/\\r$//' docker-entrypoint.spark.sh", dockerfile)
        attributes = ROOT / ".gitattributes"
        self.assertTrue(attributes.is_file())
        self.assertIn("*.sh text eol=lf", attributes.read_text(encoding="utf-8"))

    def test_app_images_copy_every_local_runtime_import(self) -> None:
        app = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        local_modules = {
            f"{node.module}.py"
            for node in app.body
            if isinstance(node, ast.ImportFrom)
            and node.module
            and (ROOT / f"{node.module}.py").is_file()
        }
        for filename in ("Dockerfile", "Dockerfile.app"):
            with self.subTest(dockerfile=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                copied = set()
                for line in text.replace("\\\n", " ").splitlines():
                    if line.startswith("COPY "):
                        copied.update(shlex.split(line)[1:-1])
                self.assertTrue(local_modules <= copied, local_modules - copied)

    def test_app_images_use_credential_free_fallback_not_host_secrets(self) -> None:
        for filename in ("Dockerfile", "Dockerfile.app"):
            with self.subTest(dockerfile=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("COPY .streamlit/config.toml ./.streamlit/config.toml", text)
                self.assertNotIn("COPY .streamlit/ ./.streamlit/", text)
                self.assertIn("printf '[users]\\n' > .streamlit/secrets.toml", text)
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".streamlit/*", ignored)
        self.assertIn("!.streamlit/config.toml", ignored)

    def test_compose_requires_the_bootstrapped_users_file(self) -> None:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("source: ./.streamlit/users.local.toml", text)
        self.assertIn("target: /app/.streamlit/secrets.toml", text)
        self.assertIn("create_host_path: false", text)
        self.assertIn("read_only: true", text)
        self.assertIn('127.0.0.1:8501:8501', text)

    def test_local_users_file_is_ignored_by_git_and_docker_build(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".streamlit/users.local.toml", gitignore)
        self.assertIn(".streamlit/*", dockerignore)

    def test_startup_mode_is_overridable_without_changing_auto_default(self) -> None:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('PIPELINE_RUN_ON_STARTUP: "${PIPELINE_RUN_ON_STARTUP:-auto}"', text)

    def test_empty_users_stop_before_authenticated_session_or_data_access(self) -> None:
        class StopExecution(Exception):
            pass

        streamlit = Mock()
        streamlit.secrets = {"users": {}}
        streamlit.session_state = {
            "authenticated_user": "stale-session",
            "authenticated_role": "admin",
        }
        streamlit.stop.side_effect = StopExecution
        configured_users = load_function(
            "app.py",
            "_configured_users",
            {
                "LOCAL_USERS_FILE": Mock(is_file=Mock(return_value=False)),
                "st": streamlit,
                "tomllib": tomllib,
            },
        )
        authenticate = load_function(
            "app.py",
            "_authenticate",
            {"_configured_users": configured_users, "st": streamlit},
        )
        with self.assertRaises(StopExecution):
            authenticate()
        self.assertIn("bloqueada", streamlit.error.call_args.args[0])
        streamlit.form.assert_not_called()

    def test_scheduler_auto_preserves_existing_successful_plan(self) -> None:
        marker = Mock()
        marker.exists.return_value = True
        should_run = load_function(
            "scheduler.py", "_should_run_on_startup",
            {"os": os, "log": logging.getLogger(__name__), "_SUCCESS_MARKER": marker},
        )
        with patch.dict(os.environ, {"PIPELINE_RUN_ON_STARTUP": "auto"}):
            self.assertFalse(should_run())
        marker.exists.return_value = False
        with patch.dict(os.environ, {"PIPELINE_RUN_ON_STARTUP": "auto"}):
            self.assertTrue(should_run())
        with patch.dict(os.environ, {"PIPELINE_RUN_ON_STARTUP": "false"}):
            self.assertFalse(should_run())


if __name__ == "__main__":
    unittest.main()
