import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

import app


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


class LeaderboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = app.DB_PATH
        app.DB_PATH = Path(self.temp_dir.name) / "test.db"
        app.initialize_db()

    def tearDown(self) -> None:
        app.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_leaderboard_orders_players_by_rating_and_assigns_ranks(self) -> None:
        with app.connect_db() as db:
            db.executemany(
                """
                INSERT INTO users (id, username, salt, password_hash, rating, wins)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("player-one", "Mira", b"salt", b"hash", 1200, 3),
                    ("player-two", "Alex", b"salt", b"hash", 1500, 1),
                ],
            )
        self.assertEqual(
            app.leaderboard()["players"],
            [
                {
                    "rank": 1,
                    "username": "Alex",
                    "rating": 1500,
                    "wins": 1,
                    "losses": 0,
                    "draws": 0,
                },
                {
                    "rank": 2,
                    "username": "Mira",
                    "rating": 1200,
                    "wins": 3,
                    "losses": 0,
                    "draws": 0,
                },
            ],
        )


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.red_socket = FakeWebSocket()
        self.black_socket = FakeWebSocket()
        self.match = app.Match(
            "game-id",
            {"red-id": "red", "black-id": "black"},
            {"red-id": "Mira", "black-id": "Alex"},
        )
        app.connections.update(
            {"red-id": self.red_socket, "black-id": self.black_socket}
        )
        app.user_matches.update({"red-id": self.match, "black-id": self.match})

    def tearDown(self) -> None:
        app.connections.pop("red-id", None)
        app.connections.pop("black-id", None)
        app.user_matches.pop("red-id", None)
        app.user_matches.pop("black-id", None)

    async def test_chat_is_trimmed_and_broadcast_only_to_match_players(self) -> None:
        await app.handle_chat("red-id", {"message": "  Good game!  "})

        expected = {
            "type": "chat",
            "username": "Mira",
            "message": "Good game!",
        }
        self.assertEqual(len(self.red_socket.messages), 1)
        self.assertEqual(len(self.black_socket.messages), 1)
        self.assertEqual(
            {key: self.red_socket.messages[0][key] for key in expected},
            expected,
        )
        self.assertEqual(self.red_socket.messages, self.black_socket.messages)

    async def test_chat_rejects_messages_over_300_characters(self) -> None:
        await app.handle_chat("red-id", {"message": "x" * 301})

        self.assertEqual(self.red_socket.messages[0]["type"], "error")
        self.assertEqual(self.black_socket.messages, [])


if __name__ == "__main__":
    unittest.main()
