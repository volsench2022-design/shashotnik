import unittest

from desktop import validate_server_url


class DesktopServerUrlTests(unittest.TestCase):
    def test_normalizes_a_server_address(self) -> None:
        self.assertEqual(
            validate_server_url("  https://games.example.com/  "),
            "https://games.example.com",
        )

    def test_rejects_non_http_schemes_and_paths(self) -> None:
        for value in (
            "ws://games.example.com",
            "https://games.example.com/game",
            "https://user:password@games.example.com",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_server_url(value)


if __name__ == "__main__":
    unittest.main()
