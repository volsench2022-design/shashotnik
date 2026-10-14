"""Rules for English draughts (American checkers)."""

from dataclasses import dataclass
from typing import TypeAlias

Piece: TypeAlias = str | None
Board: TypeAlias = list[list[Piece]]
Square: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class Move:
    start: Square
    end: Square
    captured: Square | None = None


def new_board() -> Board:
    board: Board = [[None for _ in range(8)] for _ in range(8)]
    for row in range(3):
        for col in range(8):
            if (row + col) % 2 == 1:
                board[row][col] = "b"
    for row in range(5, 8):
        for col in range(8):
            if (row + col) % 2 == 1:
                board[row][col] = "r"
    return board


def side_of(piece: Piece) -> str | None:
    if piece is None:
        return None
    return "red" if piece.lower() == "r" else "black"


def legal_moves(board: Board, side: str, only_from: Square | None = None) -> list[Move]:
    """Return all legal moves, enforcing mandatory captures and jump continuation."""
    if side not in ("red", "black"):
        raise ValueError("side must be 'red' or 'black'")

    directions = (-1, 1) if side == "red" else (1, -1)
    captures: list[Move] = []
    steps: list[Move] = []

    for row in range(8):
        for col in range(8):
            if only_from is not None and (row, col) != only_from:
                continue
            piece = board[row][col]
            if side_of(piece) != side:
                continue
            piece_directions = (-1, 1) if piece.isupper() else (directions[0],)
            for dr in piece_directions:
                for dc in (-1, 1):
                    next_row, next_col = row + dr, col + dc
                    if not (0 <= next_row < 8 and 0 <= next_col < 8):
                        continue
                    target = board[next_row][next_col]
                    if target is None:
                        if only_from is None:
                            steps.append(Move((row, col), (next_row, next_col)))
                        continue
                    if side_of(target) != side:
                        jump_row, jump_col = row + 2 * dr, col + 2 * dc
                        if (
                            0 <= jump_row < 8
                            and 0 <= jump_col < 8
                            and board[jump_row][jump_col] is None
                        ):
                            captures.append(
                                Move((row, col), (jump_row, jump_col), (next_row, next_col))
                            )

    return captures if captures else steps


def apply_move(board: Board, move: Move) -> str:
    """Apply a previously validated move in place and return the moved piece."""
    start_row, start_col = move.start
    end_row, end_col = move.end
    piece = board[start_row][start_col]
    if piece is None:
        raise ValueError("cannot move from an empty square")

    board[start_row][start_col] = None
    board[end_row][end_col] = piece
    if move.captured is not None:
        captured_row, captured_col = move.captured
        board[captured_row][captured_col] = None

    if piece == "r" and end_row == 0:
        board[end_row][end_col] = "R"
    elif piece == "b" and end_row == 7:
        board[end_row][end_col] = "B"
    return board[end_row][end_col] or piece
