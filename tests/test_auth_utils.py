from __future__ import annotations

import unittest

from auth_utils import hash_password, verify_password


class AuthUtilsTests(unittest.TestCase):
    def test_password_hash_verifies_only_the_matching_password(self) -> None:
        encoded = hash_password("a sufficiently long test password")
        self.assertTrue(verify_password("a sufficiently long test password", encoded))
        self.assertFalse(verify_password("incorrect password", encoded))
        self.assertFalse(verify_password("x", "invalid"))

    def test_password_hash_requires_minimum_length(self) -> None:
        with self.assertRaises(ValueError):
            hash_password("short")


if __name__ == "__main__":
    unittest.main()
