#!/usr/bin/env python3
"""Generate a password hash for a manually provisioned account."""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.auth_service import hash_password  # noqa: E402


def main() -> None:
    password = getpass.getpass("New password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    try:
        print(hash_password(password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
