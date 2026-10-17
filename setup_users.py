from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets

from auth_utils import hash_password


REPOSITORY_ROOT = Path(__file__).resolve().parent
USERS_FILE = REPOSITORY_ROOT / ".streamlit" / "users.local.toml"
USER_ROLES = {
    "admin": "admin",
    "planner": "planner",
    "warehouse": "warehouse",
    "viewer": "viewer",
}


def build_user_files() -> tuple[str, str]:
    passwords: dict[str, str] = {}
    for username in USER_ROLES:
        password = secrets.token_urlsafe(24)
        while password in passwords.values():
            password = secrets.token_urlsafe(24)
        passwords[username] = password

    users_toml = "\n".join(
        "\n".join(
            (
            f"[users.{username}]",
            f"role = {json.dumps(role)}",
            f"password_hash = {json.dumps(hash_password(passwords[username]))}",
            )
        )
        for username, role in USER_ROLES.items()
    ) + "\n"
    credentials_toml = "[passwords]\n" + "".join(
        f"{username} = {json.dumps(password)}\n"
        for username, password in passwords.items()
    )
    return users_toml, credentials_toml


def _create_new_file(path: Path, content: str) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        if os.name != "nt":
            path.chmod(0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _ensure_no_existing_secrets_file(path: Path) -> None:
    if path.is_file():
        raise FileExistsError(
            "An existing .streamlit/secrets.toml file is preserved; "
            "review it before bootstrapping local users."
        )


def bootstrap_users(
    *,
    credentials_path: Path,
    users_path: Path = USERS_FILE,
    repository_root: Path = REPOSITORY_ROOT,
) -> None:
    credentials_path = credentials_path.expanduser().resolve()
    users_path = users_path.expanduser().resolve()
    repository_root = repository_root.resolve()

    if credentials_path == users_path:
        raise ValueError("The users file and credentials file must be different.")
    existing_secrets_file = users_path.parent / "secrets.toml"
    _ensure_no_existing_secrets_file(existing_secrets_file)
    for path in (users_path, credentials_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")

    if credentials_path.is_relative_to(repository_root):
        raise ValueError("The credentials file must be outside the repository.")

    users_toml, credentials_toml = build_user_files()
    created: list[Path] = []
    try:
        _create_new_file(users_path, users_toml)
        created.append(users_path)
        _create_new_file(credentials_path, credentials_toml)
        created.append(credentials_path)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create local Streamlit accounts with random passwords."
    )
    parser.add_argument(
        "--credentials-file",
        required=True,
        type=Path,
        help="Path outside the repository for the generated passwords.",
    )
    args = parser.parse_args()
    bootstrap_users(credentials_path=args.credentials_file)
    print("Usuarios creados. Consulte el archivo de credenciales indicado.")


if __name__ == "__main__":
    main()
