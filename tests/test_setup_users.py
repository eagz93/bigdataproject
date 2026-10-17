from __future__ import annotations

import os
import argparse
import ast
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import MagicMock, Mock, patch

from auth_utils import verify_password
from setup_users import (
    _create_new_file,
    _ensure_no_existing_secrets_file,
    bootstrap_users,
    build_user_files,
)


ROOT = Path(__file__).resolve().parents[1]


class SetupUsersTests(unittest.TestCase):
    def test_generated_accounts_have_unique_passwords_and_valid_hashes(self) -> None:
        users_toml, credentials_toml = build_user_files()
        users = tomllib.loads(users_toml)["users"]
        passwords = tomllib.loads(credentials_toml)["passwords"]

        self.assertEqual(
            {record["role"] for record in users.values()},
            {"admin", "planner", "warehouse", "viewer"},
        )
        self.assertEqual(set(users), set(passwords))
        self.assertEqual(len(set(passwords.values())), len(passwords))
        for username, record in users.items():
            self.assertTrue(verify_password(passwords[username], record["password_hash"]))
            self.assertNotIn(passwords[username], users_toml)

    def test_bootstrap_refuses_existing_users_or_credentials_files(self) -> None:
        users_path = MagicMock()
        users_path.expanduser.return_value = users_path
        users_path.resolve.return_value = users_path
        users_path.exists.return_value = True
        credentials_path = MagicMock()
        credentials_path.expanduser.return_value = credentials_path
        credentials_path.resolve.return_value = credentials_path
        credentials_path.exists.return_value = False

        with patch("setup_users._create_new_file") as create_file:
            with self.assertRaises(FileExistsError):
                bootstrap_users(
                    credentials_path=credentials_path,
                    users_path=users_path,
                )

        create_file.assert_not_called()

    def test_bootstrap_preserves_an_existing_secrets_file(self) -> None:
        secrets_path = MagicMock()
        secrets_path.is_file.return_value = True

        with self.assertRaisesRegex(FileExistsError, "existing .streamlit/secrets.toml"):
            _ensure_no_existing_secrets_file(secrets_path)

    def test_new_files_are_exclusive_and_have_restrictive_permissions(self) -> None:
        path = MagicMock()
        output = MagicMock()
        stream = Mock()
        output.__enter__.return_value = stream

        with (
            patch("setup_users.os.open", return_value=37) as open_file,
            patch("setup_users.os.fdopen", return_value=output) as fdopen,
            patch("setup_users.os.name", "posix"),
        ):
            _create_new_file(path, "synthetic test content")

        open_file.assert_called_once_with(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        fdopen.assert_called_once_with(
            37, "w", encoding="utf-8", newline="\n"
        )
        stream.write.assert_called_once_with("synthetic test content")
        path.chmod.assert_called_once_with(0o600)

    def test_new_file_creation_refuses_existing_path_exclusively(self) -> None:
        path = MagicMock()

        with patch("setup_users.os.open", side_effect=FileExistsError) as open_file:
            with self.assertRaises(FileExistsError):
                _create_new_file(path, "replacement content")

        self.assertTrue(open_file.call_args.args[1] & os.O_EXCL)

    def test_credentials_destination_must_be_outside_repository(self) -> None:
        users_path = MagicMock()
        users_path.expanduser.return_value = users_path
        users_path.resolve.return_value = users_path
        users_path.exists.return_value = False
        users_path.parent.is_dir.return_value = True
        (users_path.parent / "secrets.toml").is_file.return_value = False
        credentials_path = MagicMock()
        credentials_path.expanduser.return_value = credentials_path
        credentials_path.resolve.return_value = credentials_path
        credentials_path.exists.return_value = False
        credentials_path.parent.is_dir.return_value = True
        credentials_path.is_relative_to.return_value = True

        with patch("setup_users._create_new_file") as create_file:
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                bootstrap_users(
                    credentials_path=credentials_path,
                    users_path=users_path,
                )

        create_file.assert_not_called()

    def test_cli_reports_success_without_printing_credentials(self) -> None:
        tree = ast.parse((ROOT / "setup_users.py").read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        bootstrap = Mock()
        namespace = {"argparse": argparse, "Path": Path, "bootstrap_users": bootstrap}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "setup_users.py", "exec"), namespace)
        credential_path = ROOT.parent / "synthetic-credentials.txt"

        with patch.object(
            sys,
            "argv",
            ["setup_users.py", "--credentials-file", str(credential_path)],
        ), patch("builtins.print") as printed:
            namespace["main"]()

        bootstrap.assert_called_once_with(credentials_path=credential_path)
        printed.assert_called_once_with(
            "Usuarios creados. Consulte el archivo de credenciales indicado."
        )


if __name__ == "__main__":
    unittest.main()
