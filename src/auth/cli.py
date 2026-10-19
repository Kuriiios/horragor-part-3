"""Local secret helpers that never accept credentials through command arguments."""

from __future__ import annotations

import argparse
import getpass
import secrets

from argon2 import PasswordHasher


def hash_password() -> None:
    """Prompt privately and print an Argon2id hash suitable for the environment file."""
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    print(PasswordHasher().hash(password))


def generate_secret() -> None:
    """Print a cryptographically secure URL-safe signing or service secret."""
    print(secrets.token_urlsafe(48))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local HorRAGor secrets")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hash-password", help="Generate an Argon2id password hash")
    subparsers.add_parser("generate-secret", help="Generate a random service secret")
    arguments = parser.parse_args()
    if arguments.command == "hash-password":
        hash_password()
    else:
        generate_secret()


if __name__ == "__main__":
    main()