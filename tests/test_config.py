import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Settings


class SettingsTests(unittest.TestCase):
    def test_secret_files_are_supported_and_direct_values_take_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_key_file = root / "data-key"
            jwt_file = root / "jwt"
            password_file = root / "password"
            data_key_file.write_text("file-data-key", encoding="utf-8")
            jwt_file.write_text("file-jwt-secret", encoding="utf-8")
            password_file.write_text("file-password-hash", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "HORRAGOR_DATA_API_KEY": "direct-data-key",
                    "HORRAGOR_DATA_API_KEY_FILE": str(data_key_file),
                    "HORRAGOR_JWT_SECRET": "",
                    "HORRAGOR_JWT_SECRET_FILE": str(jwt_file),
                    "HORRAGOR_AUTH_PASSWORD_HASH": "",
                    "HORRAGOR_AUTH_PASSWORD_HASH_FILE": str(password_file),
                },
            ):
                configured = Settings.from_environment()

        self.assertEqual(configured.data_api_key, "direct-data-key")
        self.assertEqual(configured.jwt_secret, "file-jwt-secret")
        self.assertEqual(configured.auth_password_hash, "file-password-hash")


if __name__ == "__main__":
    unittest.main()