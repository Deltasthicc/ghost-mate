"""Deep, robust tests for the AI coach module.

Coverage targets:
- ``build_coach_context`` shape across normal, empty, and malformed inputs
- ``rule_based_coach`` content across phases, special moves, and question types
- Every private helper (`_phase_label`, `_material_balance`, `_king_safety`,
  `_development_status`, `_move_intent`, `_phase_guidance`, `_question_hint`)
- ``LlmCoach.explain`` for the local fallback, mocked LLM success, mocked LLM
  HTTP error, and exception-during-request paths.

All tests are hermetic: they never spawn Stockfish, never touch the network,
and stub aiohttp where needed so they remain deterministic on CI.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import chess
import pytest

from host.app.ai import coach as coach_mod
from host.app.ai.coach import (
    LlmCoach,
    _development_status,
    _king_safety,
    _material_balance,
    _move_intent,
    _phase_guidance,
    _phase_label,
    _question_hint,
    build_coach_context,
    rule_based_coach,
)
from host.app.domain.game_state import GameState


# ─────────────────────────────────────────────────────────────────────────────
# Forbidden phrases — the user explicitly rejected these in the coach output.
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_PHRASES = [
    "advisory only",
    "tactical anchor",
    "physical move",
    "robot commands still go through",
    "Source: local_fallback",
]


def _assert_no_boilerplate(answer: str) -> None:
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in answer, (
            f"Coach output must never contain '{phrase}'.\nGot:\n{answer}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# build_coach_context
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildCoachContext:
    def test_starting_position_has_expected_keys(self):
        snapshot = GameState().snapshot()
        ctx = build_coach_context(snapshot, None)
        for key in (
            "fen", "turn", "is_check", "is_game_over", "result",
            "robot_busy", "last_error", "legal_moves_count",
            "fullmove_number", "halfmove_clock",
            "stockfish", "position_features",
        ):
            assert key in ctx
        assert ctx["legal_moves_count"] == 20
        assert ctx["stockfish"]["best_moves"] == []

    def test_analysis_is_truncated_to_five_lines(self):
        snapshot = GameState().snapshot()
        analysis = {
            "best_moves": [
                {"rank": i, "uci": "e2e4", "san": "e4",
                 "score_display": "+0.10", "pv": ["e4", "e5"]}
                for i in range(1, 10)
            ],
            "current_display": "+0.10",
            "depth": 12,
        }
        ctx = build_coach_context(snapshot, analysis)
        assert len(ctx["stockfish"]["best_moves"]) == 5

    def test_pv_is_capped_at_six_moves(self):
        snapshot = GameState().snapshot()
        long_pv = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O"]
        analysis = {
            "best_moves": [{"rank": 1, "uci": "e2e4", "san": "e4",
                            "score_display": "+0.10", "pv": long_pv}],
        }
        ctx = build_coach_context(snapshot, analysis)
        assert len(ctx["stockfish"]["best_moves"][0]["pv"]) == 6

    def test_missing_analysis_yields_empty_stockfish(self):
        ctx = build_coach_context(GameState().snapshot(), None)
        assert ctx["stockfish"]["best_moves"] == []
        assert ctx["stockfish"]["display"] is None
        assert ctx["stockfish"]["depth"] is None

    def test_invalid_fen_in_snapshot_returns_empty_features(self):
        snapshot = {"fen": "not-a-real-fen", "turn": "white",
                    "legal_moves": []}
        ctx = build_coach_context(snapshot, None)
        assert ctx["position_features"] == {}

    def test_snapshot_without_fen_returns_empty_features(self):
        ctx = build_coach_context({"turn": "white", "legal_moves": []}, None)
        assert ctx["position_features"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# _phase_label
# ─────────────────────────────────────────────────────────────────────────────

class TestPhaseLabel:
    def test_starting_position_is_opening(self):
        assert _phase_label(chess.Board()) == "opening"

    def test_only_kings_is_endgame(self):
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 60")
        assert _phase_label(board) == "endgame"

    def test_king_and_pawn_endgame(self):
        board = chess.Board("4k3/8/8/4P3/8/8/8/4K3 w - - 0 50")
        assert _phase_label(board) == "endgame"

    def test_no_queens_late_move_is_endgame(self):
        board = chess.Board("4k3/pp3pp1/2p5/8/8/2P5/PP3PP1/4K3 w - - 0 30")
        assert _phase_label(board) == "endgame"

    def test_dense_material_mid_move_is_middlegame(self):
        board = chess.Board(
            "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
        )
        for _ in range(40):
            board.fullmove_number += 1
        # phase logic is based on remaining pieces + queens + move number
        assert _phase_label(board) == "middlegame"


# ─────────────────────────────────────────────────────────────────────────────
# _material_balance
# ─────────────────────────────────────────────────────────────────────────────

class TestMaterialBalance:
    def test_starting_position_is_even(self):
        result = _material_balance(chess.Board())
        assert result["diff"] == 0
        assert result["summary"] == "Material is even"

    def test_white_up_a_queen(self):
        board = chess.Board(
            "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        result = _material_balance(board)
        assert result["diff"] == 9
        assert "White is up 9" in result["summary"]

    def test_black_up_a_rook(self):
        board = chess.Board(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w Kkq - 0 1"
        )
        result = _material_balance(board)
        assert result["diff"] == -5
        assert "Black is up 5" in result["summary"]

    def test_singular_plural_grammar(self):
        # "1 point" not "1 points"
        board = chess.Board(
            "rnbqkbnr/ppppppp1/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        # Black missing one pawn → +1 for White → "1 point" (no s)
        result = _material_balance(board)
        assert result["diff"] == 1
        assert "1 point" in result["summary"] and "1 points" not in result["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# _king_safety
# ─────────────────────────────────────────────────────────────────────────────

class TestKingSafety:
    def test_starting_position_both_have_castling_rights(self):
        info = _king_safety(chess.Board())
        assert "castling rights" in info["white"]
        assert "castling rights" in info["black"]

    def test_castled_king_is_labelled_castled(self):
        board = chess.Board()
        for move in ("e2e4", "e7e5", "g1f3", "g8f6", "f1c4", "f8c5", "e1g1"):
            board.push_uci(move)
        info = _king_safety(board)
        assert info["white"] == "castled"
        assert "castling rights" in info["black"]

    def test_no_castling_rights_marks_exposed(self):
        board = chess.Board(
            "rnbq1bnr/pppppkpp/5p2/8/8/5P2/PPPPPKPP/RNBQ1BNR w - - 0 1"
        )
        info = _king_safety(board)
        assert "exposed" in info["white"]
        assert "exposed" in info["black"]


# ─────────────────────────────────────────────────────────────────────────────
# _development_status
# ─────────────────────────────────────────────────────────────────────────────

class TestDevelopmentStatus:
    def test_starting_position_has_four_undeveloped_minors_each(self):
        info = _development_status(chess.Board())
        assert info["white"]["undeveloped_minors"] == 4
        assert info["black"]["undeveloped_minors"] == 4

    def test_after_developing_two_knights(self):
        board = chess.Board()
        for move in ("g1f3", "g8f6", "b1c3", "b8c6"):
            board.push_uci(move)
        info = _development_status(board)
        assert info["white"]["undeveloped_minors"] == 2
        assert info["black"]["undeveloped_minors"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# _move_intent
# ─────────────────────────────────────────────────────────────────────────────

class TestMoveIntent:
    @pytest.mark.parametrize("san,must_contain", [
        ("O-O", "short castle"),
        ("O-O-O", "long castle"),
        ("Qxh7+", "check"),
        ("Qxh7#", "checkmate"),
        ("Nxe5", "capture"),
        ("e4", "pawn"),
        ("Nf3", "knight"),
        ("Bc4", "bishop"),
        ("Rd1", "rook"),
        ("Qd1", "queen"),
    ])
    def test_intent_labels_cover_all_move_types(self, san, must_contain):
        assert must_contain in _move_intent(san, "middlegame")

    def test_king_move_endgame_says_safer_square(self):
        assert "safer square" in _move_intent("Ke2", "endgame")

    def test_king_move_opening_says_last_resort(self):
        assert "last resort" in _move_intent("Ke2", "opening")

    def test_empty_san_returns_no_move(self):
        assert _move_intent("", "middlegame") == "no move available"


# ─────────────────────────────────────────────────────────────────────────────
# _phase_guidance
# ─────────────────────────────────────────────────────────────────────────────

class TestPhaseGuidance:
    def test_opening_mentions_develop(self):
        features = {"development": {"white": {"undeveloped_minors": 3}}}
        out = _phase_guidance("opening", features, "white")
        assert "develop" in out.lower()
        assert "3 minor piece" in out

    def test_endgame_mentions_king(self):
        out = _phase_guidance("endgame", {}, "white")
        assert "king" in out.lower()

    def test_middlegame_mentions_pieces(self):
        out = _phase_guidance("middlegame", {}, "black")
        assert "piece" in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# _question_hint
# ─────────────────────────────────────────────────────────────────────────────

class TestQuestionHint:
    @pytest.mark.parametrize("question", [
        "why does this work", "Explain please", "What's the reason",
    ])
    def test_why_questions_reference_best_move(self, question):
        out = _question_hint(question, {"san": "Nf3"}, "opening")
        assert "Nf3" in out

    def test_why_without_top_move_falls_back(self):
        out = _question_hint("why", {}, "middlegame")
        assert "no candidate" in out.lower()

    @pytest.mark.parametrize("question,phase,keyword", [
        ("what's the plan?", "opening", "develop"),
        ("strategy here", "endgame", "king"),
        ("what do I do next", "middlegame", "worst"),
    ])
    def test_plan_questions_pick_phase_guidance(self, question, phase, keyword):
        out = _question_hint(question, {"san": "e4"}, phase)
        assert keyword in out.lower()

    def test_mistake_question_explains_evaluation_jumps(self):
        out = _question_hint("was that a blunder?", {"san": "e4"}, "middlegame")
        assert "inaccuracy" in out.lower() or "evaluation" in out.lower()

    def test_teach_question_returns_teaching_tip(self):
        out = _question_hint("teach me", {"san": "e4"}, "opening")
        assert "blunder" in out.lower() or "habit" in out.lower()

    def test_unknown_question_falls_back_to_best_move(self):
        out = _question_hint("???", {"san": "Nc3"}, "middlegame")
        assert "Nc3" in out

    def test_empty_question_returns_empty_string(self):
        assert _question_hint("", {"san": "Nc3"}, "middlegame") == ""


# ─────────────────────────────────────────────────────────────────────────────
# rule_based_coach end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleBasedCoach:
    def _ctx_with_top_move(self, **overrides):
        snapshot = GameState().snapshot()
        analysis = {
            "current_display": "+0.30",
            "depth": 9,
            "best_moves": [
                {"rank": 1, "uci": "e2e4", "san": "e4",
                 "score_display": "+0.30", "pv": ["e4", "e5", "Nf3"]},
                {"rank": 2, "uci": "d2d4", "san": "d4",
                 "score_display": "+0.22", "pv": ["d4"]},
                {"rank": 3, "uci": "c2c4", "san": "c4",
                 "score_display": "+0.18", "pv": ["c4"]},
            ],
        }
        ctx = build_coach_context(snapshot, analysis)
        ctx.update(overrides)
        return ctx

    def test_basic_lesson_has_overview_plan_and_phase(self):
        ctx = self._ctx_with_top_move()
        answer = rule_based_coach(ctx, "What's the plan?")
        _assert_no_boilerplate(answer)
        assert "white to move" in answer.lower()
        assert "Best move" in answer
        assert "e4" in answer
        assert "Opening priorities" in answer or "opening" in answer.lower()

    def test_no_question_still_returns_lesson(self):
        ctx = self._ctx_with_top_move()
        answer = rule_based_coach(ctx, None)
        _assert_no_boilerplate(answer)
        assert "Best move" in answer

    def test_alternatives_listed_when_present(self):
        ctx = self._ctx_with_top_move()
        answer = rule_based_coach(ctx, None)
        assert "Other candidates" in answer
        assert "d4" in answer

    def test_no_stockfish_data_falls_back_gracefully(self):
        snapshot = GameState().snapshot()
        ctx = build_coach_context(snapshot, None)
        answer = rule_based_coach(ctx, "any tips?")
        _assert_no_boilerplate(answer)
        assert "No engine candidate" in answer

    def test_checkmate_position_mentions_game_over(self):
        # Fool's mate (Black mates)
        game = GameState()
        game.new_game()
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            game.push_uci(uci)
        ctx = build_coach_context(game.snapshot(), None)
        answer = rule_based_coach(ctx, None)
        _assert_no_boilerplate(answer)
        assert "game is over" in answer.lower() or "result" in answer.lower()

    def test_endgame_advice_mentions_king(self):
        snapshot = {
            "fen": "4k3/8/8/4P3/8/8/8/4K3 w - - 0 50",
            "turn": "white",
            "legal_moves": [],
            "fullmove_number": 50,
        }
        ctx = build_coach_context(snapshot, {
            "current_display": "+1.20",
            "depth": 12,
            "best_moves": [{"rank": 1, "uci": "e1e2", "san": "Ke2",
                            "score_display": "+1.20", "pv": ["Ke2"]}],
        })
        answer = rule_based_coach(ctx, "what now?")
        _assert_no_boilerplate(answer)
        assert "king" in answer.lower()

    def test_check_state_is_mentioned(self):
        ctx = self._ctx_with_top_move(is_check=True)
        answer = rule_based_coach(ctx, None)
        assert "in check" in answer.lower()


# ─────────────────────────────────────────────────────────────────────────────
# LlmCoach.explain — local fallback paths
# ─────────────────────────────────────────────────────────────────────────────

class _StubSettings:
    def __init__(self, **overrides):
        self.llm_coach_enabled = False
        self.llm_api_base = "https://api.example.com/v1"
        self.llm_api_key = None
        self.llm_model = "test-model"
        self.llm_timeout_s = 1.0
        self.llm_max_tokens = 256
        for k, v in overrides.items():
            setattr(self, k, v)


@pytest.mark.asyncio
class TestLlmCoachFallbackPaths:
    async def test_returns_local_when_llm_disabled(self):
        coach = LlmCoach(_StubSettings(llm_coach_enabled=False, llm_api_key="x"))
        ctx = build_coach_context(GameState().snapshot(), None)
        result = await coach.explain(context=ctx, question="explain")
        assert result["source"] == "local_fallback"
        assert result["configured"] is False
        _assert_no_boilerplate(result["answer"])

    async def test_returns_local_when_api_key_missing(self):
        coach = LlmCoach(_StubSettings(llm_coach_enabled=True, llm_api_key=None))
        ctx = build_coach_context(GameState().snapshot(), None)
        result = await coach.explain(context=ctx, question=None)
        assert result["source"] == "local_fallback"

    async def test_local_fallback_carries_context(self):
        coach = LlmCoach(_StubSettings())
        ctx = build_coach_context(GameState().snapshot(), None)
        result = await coach.explain(context=ctx, question="why?")
        assert result["context"]["fen"] == ctx["fen"]


# ─────────────────────────────────────────────────────────────────────────────
# LlmCoach.explain — mocked aiohttp paths
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]):
        self.status = status
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, status: int = 200, payload: dict[str, Any] | None = None,
                 raise_on_post: Exception | None = None):
        self.status = status
        self.payload = payload or {
            "choices": [{"message": {"content": "Engine teaching response."}}]
        }
        self.raise_on_post = raise_on_post
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None
        self.last_payload: dict[str, Any] | None = None

    def post(self, url, headers=None, json=None):
        if self.raise_on_post is not None:
            raise self.raise_on_post
        self.last_url = url
        self.last_headers = headers
        self.last_payload = json
        return _FakeResponse(self.status, self.payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
class TestLlmCoachNetworkedPaths:
    async def test_successful_llm_returns_answer(self):
        settings = _StubSettings(llm_coach_enabled=True, llm_api_key="sk-test")
        session = _FakeSession(
            status=200,
            payload={"choices": [{"message": {"content": "Clear, useful lesson."}}]},
        )
        with patch.object(coach_mod.aiohttp, "ClientSession",
                          return_value=session):
            ctx = build_coach_context(GameState().snapshot(), None)
            result = await LlmCoach(settings).explain(
                context=ctx, question="Teach me", style="student"
            )
        assert result["source"] == "llm"
        assert result["configured"] is True
        assert result["model"] == "test-model"
        assert result["answer"] == "Clear, useful lesson."
        # The request URL must hit /chat/completions
        assert session.last_url.endswith("/chat/completions")
        # Headers must include the bearer token
        assert session.last_headers["Authorization"] == "Bearer sk-test"
        # Payload must carry the chess context as JSON string in user content
        user_msg = session.last_payload["messages"][1]["content"]
        assert isinstance(user_msg, str)
        assert "fen" in user_msg

    async def test_llm_4xx_falls_back_to_local(self):
        settings = _StubSettings(llm_coach_enabled=True, llm_api_key="sk-test")
        session = _FakeSession(status=429, payload={"error": "rate_limited"})
        with patch.object(coach_mod.aiohttp, "ClientSession",
                          return_value=session):
            ctx = build_coach_context(GameState().snapshot(), None)
            result = await LlmCoach(settings).explain(context=ctx, question="why")
        assert result["source"] == "llm_error"
        assert result["configured"] is True
        assert "error" in result
        _assert_no_boilerplate(result["answer"])

    async def test_llm_empty_answer_uses_local_text(self):
        settings = _StubSettings(llm_coach_enabled=True, llm_api_key="sk-test")
        session = _FakeSession(
            status=200,
            payload={"choices": [{"message": {"content": "   "}}]},
        )
        with patch.object(coach_mod.aiohttp, "ClientSession",
                          return_value=session):
            ctx = build_coach_context(GameState().snapshot(), None)
            result = await LlmCoach(settings).explain(context=ctx, question="why")
        assert result["source"] == "llm"
        # Empty-string answer is replaced by the deterministic local lesson.
        assert result["answer"]
        _assert_no_boilerplate(result["answer"])

    async def test_llm_session_construction_failure_raises_for_caller(self):
        """Network failures must propagate so the caller can decide what to do.

        The route layer (api/routes.py) is responsible for catching this and
        returning a 5xx, so we explicitly assert the exception surfaces.
        """
        settings = _StubSettings(llm_coach_enabled=True, llm_api_key="sk-test")
        session = _FakeSession(raise_on_post=RuntimeError("network dead"))
        with patch.object(coach_mod.aiohttp, "ClientSession",
                          return_value=session):
            ctx = build_coach_context(GameState().snapshot(), None)
            with pytest.raises(RuntimeError, match="network dead"):
                await LlmCoach(settings).explain(context=ctx, question="why")
