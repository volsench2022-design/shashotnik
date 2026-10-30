from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from checkers import Board, Move, apply_move, legal_moves, new_board, side_of

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CHECKERS_DB", ROOT / "checkers.db"))
SESSION_SECONDS = 30 * 24 * 60 * 60
PASSWORD_ITERATIONS = 310_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


@contextmanager
def connect_db() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                rating INTEGER NOT NULL DEFAULT 1000,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                red_user TEXT NOT NULL REFERENCES users(id),
                black_user TEXT NOT NULL REFERENCES users(id),
                winner_user TEXT REFERENCES users(id),
                is_draw INTEGER NOT NULL DEFAULT 0,
                played_at INTEGER NOT NULL
            );
            """
        )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


def user_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "rating": row["rating"],
        "wins": row["wins"],
        "losses": row["losses"],
        "draws": row["draws"],
    }


def create_session(db: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (
            hashlib.sha256(token.encode()).hexdigest(),
            user_id,
            int(time.time()) + SESSION_SECONDS,
        ),
    )
    return token


def find_user_for_token(token: str) -> sqlite3.Row | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect_db() as db:
        return db.execute(
            """
            SELECT users.* FROM users JOIN sessions ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_hash, int(time.time())),
        ).fetchone()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=8, max_length=128)


@dataclass
class Match:
    id: str
    players: dict[str, str]
    names: dict[str, str]
    board: Board = field(default_factory=new_board)
    turn: str = "red"
    forced_from: tuple[int, int] | None = None
    quiet_plies: int = 0
    finished: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_db()
    yield


app = FastAPI(title="Checkers Arena", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
match_lock = asyncio.Lock()
waiting: deque[str] = deque()
connections: dict[str, WebSocket] = {}
user_matches: dict[str, Match] = {}
matches: dict[str, Match] = {}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


def issue_auth_error(status: int, detail: str) -> None:
    raise HTTPException(status_code=status, detail=detail)


@app.post("/api/register")
def register(credentials: Credentials) -> dict[str, Any]:
    if not USERNAME_RE.fullmatch(credentials.username):
        issue_auth_error(400, "Use 3–20 letters, numbers, or underscores for your username.")
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", credentials.password.encode(), salt, PASSWORD_ITERATIONS
    )
    user_id = uuid.uuid4().hex
    try:
        with connect_db() as db:
            db.execute(
                "INSERT INTO users (id, username, salt, password_hash) VALUES (?, ?, ?, ?)",
                (user_id, credentials.username, salt, password_hash),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            token = create_session(db, user_id)
    except sqlite3.IntegrityError:
        issue_auth_error(409, "That username is already taken.")
    return {"token": token, "user": user_dict(row)}


@app.post("/api/login")
def login(credentials: Credentials) -> dict[str, Any]:
    with connect_db() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (credentials.username,),
        ).fetchone()
        if row is None:
            issue_auth_error(401, "Incorrect username or password.")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", credentials.password.encode(), row["salt"], PASSWORD_ITERATIONS
        )
        if not hmac.compare_digest(candidate, row["password_hash"]):
            issue_auth_error(401, "Incorrect username or password.")
        token = create_session(db, row["id"])
    return {"token": token, "user": user_dict(row)}


def authenticated_user(authorization: str | None) -> sqlite3.Row:
    if authorization is None or not authorization.lower().startswith("bearer "):
        issue_auth_error(401, "Sign in to continue.")
    row = find_user_for_token(authorization[7:].strip())
    if row is None:
        issue_auth_error(401, "Your session has expired. Please sign in again.")
    return row


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return user_dict(authenticated_user(authorization))


@app.get("/api/leaderboard")
def leaderboard() -> dict[str, list[dict[str, Any]]]:
    with connect_db() as db:
        rows = db.execute(
            """
            SELECT username, rating, wins, losses, draws
            FROM users
            ORDER BY rating DESC, wins DESC, username COLLATE NOCASE
            LIMIT 10
            """
        ).fetchall()
    return {
        "players": [
            {
                "rank": rank,
                "username": row["username"],
                "rating": row["rating"],
                "wins": row["wins"],
                "losses": row["losses"],
                "draws": row["draws"],
            }
            for rank, row in enumerate(rows, start=1)
        ]
    }


def board_state(match: Match, viewer_id: str) -> dict[str, Any]:
    side = match.players[viewer_id]
    current_moves = legal_moves(match.board, match.turn, match.forced_from)
    return {
        "type": "state",
        "gameId": match.id,
        "board": match.board,
        "yourSide": side,
        "turn": match.turn,
        "yourTurn": match.turn == side,
        "forcedFrom": match.forced_from,
        "legalMoves": [
            {"from": move.start, "to": move.end, "capture": move.captured}
            for move in current_moves
            if side_of(match.board[move.start[0]][move.start[1]]) == side
        ],
        "opponent": next(name for player_id, name in match.names.items() if player_id != viewer_id),
        "ratings": _ratings(match),
    }


def _ratings(match: Match) -> dict[str, int]:
    with connect_db() as db:
        users = db.execute(
            "SELECT id, rating FROM users WHERE id IN (?, ?)",
            tuple(match.players.keys()),
        ).fetchall()
    return {row["id"]: row["rating"] for row in users}


def _apply_result(match: Match, winner_side: str | None) -> dict[str, Any]:
    red_id = next(user_id for user_id, side in match.players.items() if side == "red")
    black_id = next(user_id for user_id, side in match.players.items() if side == "black")
    with connect_db() as db:
        rows = db.execute(
            "SELECT id, rating FROM users WHERE id IN (?, ?)", (red_id, black_id)
        ).fetchall()
        ratings = {row["id"]: row["rating"] for row in rows}
        red_rating, black_rating = ratings[red_id], ratings[black_id]
        expected_red = 1 / (1 + 10 ** ((black_rating - red_rating) / 400))
        red_score = 0.5 if winner_side is None else (1 if winner_side == "red" else 0)
        change = round(24 * (red_score - expected_red))
        new_red = max(100, red_rating + change)
        new_black = max(100, black_rating - change)
        db.execute("UPDATE users SET rating = ? WHERE id = ?", (new_red, red_id))
        db.execute("UPDATE users SET rating = ? WHERE id = ?", (new_black, black_id))
        if winner_side is None:
            db.execute("UPDATE users SET draws = draws + 1 WHERE id IN (?, ?)", (red_id, black_id))
            winner_id = None
        else:
            winner_id = red_id if winner_side == "red" else black_id
            loser_id = black_id if winner_side == "red" else red_id
            db.execute("UPDATE users SET wins = wins + 1 WHERE id = ?", (winner_id,))
            db.execute("UPDATE users SET losses = losses + 1 WHERE id = ?", (loser_id,))
        db.execute(
            """
            INSERT INTO games (id, red_user, black_user, winner_user, is_draw, played_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (match.id, red_id, black_id, winner_id, int(winner_side is None), int(time.time())),
        )
        fresh = db.execute(
            "SELECT id, rating FROM users WHERE id IN (?, ?)", (red_id, black_id)
        ).fetchall()
    return {row["id"]: row["rating"] for row in fresh}


async def finish_match(match: Match, winner_side: str | None, reason: str) -> None:
    if match.finished:
        return
    match.finished = True
    ratings = _apply_result(match, winner_side)
    for player_id, websocket in list(connections.items()):
        if user_matches.get(player_id) is match:
            await websocket.send_json(
                {
                    "type": "game_over",
                    "winner": winner_side,
                    "result": "draw" if winner_side is None else ("win" if match.players[player_id] == winner_side else "loss"),
                    "reason": reason,
                    "ratings": ratings,
                }
            )
            user_matches.pop(player_id, None)
    matches.pop(match.id, None)


async def join_queue(user_id: str, websocket: WebSocket) -> None:
    opponent_id: str | None = None
    async with match_lock:
        if user_id in user_matches:
            match = user_matches[user_id]
            await websocket.send_json(board_state(match, user_id))
            return
        while waiting:
            candidate = waiting.popleft()
            if candidate != user_id and candidate in connections and candidate not in user_matches:
                opponent_id = candidate
                break
        if opponent_id is None:
            if user_id not in waiting:
                waiting.append(user_id)
            await websocket.send_json({"type": "queued", "message": "Looking for a worthy opponent…"})
            return

        player_rows: dict[str, str] = {}
        for player_id in (opponent_id, user_id):
            row = find_user_for_token_for_id(player_id)
            player_rows[player_id] = row["username"]
        match = Match(uuid.uuid4().hex, {opponent_id: "red", user_id: "black"}, player_rows)
        matches[match.id] = match
        user_matches[opponent_id] = match
        user_matches[user_id] = match
        for player_id in (opponent_id, user_id):
            await connections[player_id].send_json(board_state(match, player_id))


def find_user_for_token_for_id(user_id: str) -> sqlite3.Row:
    with connect_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise RuntimeError("Authenticated player account no longer exists.")
    return row


async def handle_move(user_id: str, message: dict[str, Any]) -> None:
    async with match_lock:
        match = user_matches.get(user_id)
        if match is None or match.finished:
            await connections[user_id].send_json({"type": "error", "message": "You are not in an active game."})
            return
        side = match.players[user_id]
        if match.turn != side:
            await connections[user_id].send_json({"type": "error", "message": "It is your opponent's turn."})
            return
        try:
            start = tuple(message["from"])
            end = tuple(message["to"])
            if (
                len(start) != 2
                or len(end) != 2
                or any(type(value) is not int or not 0 <= value < 8 for value in (*start, *end))
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            await connections[user_id].send_json({"type": "error", "message": "That move is not valid."})
            return

        legal = legal_moves(match.board, side, match.forced_from)
        move = next((item for item in legal if item.start == start and item.end == end), None)
        if move is None:
            await connections[user_id].send_json(
                {"type": "error", "message": "That move is not legal. Captures are mandatory."}
            )
            return

        moved_piece = match.board[start[0]][start[1]]
        apply_move(match.board, move)
        match.quiet_plies = 0 if move.captured else match.quiet_plies + 1
        if (
            move.captured is not None
            and moved_piece is not None
            and moved_piece.islower()
            and match.board[end[0]][end[1]].isupper()
        ):
            match.turn = "black" if side == "red" else "red"
            match.forced_from = None
        elif move.captured is not None and legal_moves(match.board, side, end):
            match.forced_from = end
        else:
            match.turn = "black" if side == "red" else "red"
            match.forced_from = None

        if not legal_moves(match.board, match.turn):
            await finish_match(match, side, "No legal moves")
        elif match.quiet_plies >= 80:
            await finish_match(match, None, "Draw by 80-move rule")
        else:
            for player_id, websocket in list(connections.items()):
                if user_matches.get(player_id) is match:
                    await websocket.send_json(board_state(match, player_id))


async def handle_chat(user_id: str, message: dict[str, Any]) -> None:
    async with match_lock:
        match = user_matches.get(user_id)
        if match is None or match.finished:
            await connections[user_id].send_json(
                {"type": "error", "message": "Chat is available during an active match."}
            )
            return
        text = message.get("message")
        if not isinstance(text, str):
            await connections[user_id].send_json(
                {"type": "error", "message": "Enter a valid chat message."}
            )
            return
        text = text.strip()
        if not text or len(text) > 300:
            await connections[user_id].send_json(
                {"type": "error", "message": "Messages must be between 1 and 300 characters."}
            )
            return
        payload = {
            "type": "chat",
            "username": match.names[user_id],
            "message": text,
            "sentAt": int(time.time()),
        }
        for player_id in match.players:
            connection = connections.get(player_id)
            if connection is not None:
                await connection.send_json(payload)


async def websocket_user(websocket: WebSocket) -> sqlite3.Row | None:
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4401, reason="Sign-in timed out")
        return None
    token = message.get("token") if isinstance(message, dict) else None
    if not isinstance(token, str):
        await websocket.close(code=4401, reason="Sign in required")
        return None
    user = find_user_for_token(token)
    if user is None:
        await websocket.close(code=4401, reason="Session expired")
        return None
    return user


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await websocket_user(websocket)
    if user is None:
        return
    user_id = user["id"]
    async with match_lock:
        if user_id in connections:
            await websocket.close(code=4409, reason="This account is already connected")
            return
        connections[user_id] = websocket
    await join_queue(user_id, websocket)
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                await websocket.send_json({"type": "error", "message": "Unexpected message."})
            elif message.get("type") == "move":
                await handle_move(user_id, message)
            elif message.get("type") == "chat":
                await handle_chat(user_id, message)
            elif message.get("type") == "resign":
                async with match_lock:
                    match = user_matches.get(user_id)
                    if match is not None:
                        await finish_match(match, "black" if match.players[user_id] == "red" else "red", "Resignation")
            elif message.get("type") == "rematch":
                await join_queue(user_id, websocket)
            else:
                await websocket.send_json({"type": "error", "message": "Unknown action."})
    except WebSocketDisconnect:
        pass
    finally:
        async with match_lock:
            if connections.get(user_id) is websocket:
                connections.pop(user_id, None)
                try:
                    waiting.remove(user_id)
                except ValueError:
                    pass
                match = user_matches.get(user_id)
                if match is not None:
                    opponent_side = "black" if match.players[user_id] == "red" else "red"
                    await finish_match(match, opponent_side, "Opponent disconnected")
