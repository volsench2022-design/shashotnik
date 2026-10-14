import unittest

from checkers import Move, apply_move, legal_moves, new_board


class CheckersRulesTests(unittest.TestCase):
    def test_initial_position_has_twelve_pieces_per_side_and_seven_moves(self) -> None:
        board = new_board()
        self.assertEqual(sum(piece is not None for row in board for piece in row), 24)
        self.assertEqual(len(legal_moves(board, "red")), 7)

    def test_capture_is_mandatory_and_can_continue(self) -> None:
        board = [[None for _ in range(8)] for _ in range(8)]
        board[5][0] = "r"
        board[4][1] = "b"
        board[2][3] = "b"
        moves = legal_moves(board, "red")
        self.assertEqual(moves, [Move((5, 0), (3, 2), (4, 1))])
        apply_move(board, moves[0])
        self.assertEqual(legal_moves(board, "red", (3, 2)), [Move((3, 2), (1, 4), (2, 3))])

    def test_men_capture_forward_only_but_kings_capture_both_directions(self) -> None:
        board = [[None for _ in range(8)] for _ in range(8)]
        board[3][2] = "r"
        board[2][1] = "r"
        board[2][3] = "r"
        board[4][3] = "b"
        self.assertFalse(any(move.captured is not None for move in legal_moves(board, "red")))
        board[3][2] = "R"
        self.assertEqual(legal_moves(board, "red"), [Move((3, 2), (5, 4), (4, 3))])

    def test_promotion(self) -> None:
        board = [[None for _ in range(8)] for _ in range(8)]
        board[1][2] = "r"
        move = legal_moves(board, "red")[0]
        self.assertEqual(apply_move(board, move), "R")
        self.assertEqual(board[0][1], "R")


if __name__ == "__main__":
    unittest.main()
