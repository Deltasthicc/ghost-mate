"""Optional LLM chess coach.

The coach is deliberately advisory. It explains positions, compares Stockfish
lines, and answers student questions, but it never bypasses python-chess
legality checks or robot safety gates. The local fallback below is also tuned
to *teach* — it must not produce filler like "this coach is advisory only".
"""
from __future__ import annotations

import json
from typing import Any

import aiohttp
import chess

from host.app.config import Settings


def build_coach_context(snapshot: dict[str, Any], analysis: dict[str, Any] | None) -> dict[str, Any]:
    """Small, structured context that is safe to send to an LLM."""
    best_moves = []
    for move in (analysis or {}).get("best_moves", [])[:5]:
        best_moves.append({
            "rank": move.get("rank"),
            "uci": move.get("uci"),
            "san": move.get("san"),
            "score": move.get("score_display") or move.get("score_display_white"),
            "pv": move.get("pv", [])[:6],
        })

    fen = snapshot.get("fen")
    extras: dict[str, Any] = {}
    if fen:
        try:
            board = chess.Board(fen)
            extras = {
                "phase": _phase_label(board),
                "material_balance": _material_balance(board),
                "king_safety": _king_safety(board),
                "development": _development_status(board),
            }
        except Exception:
            extras = {}

    return {
        "fen": fen,
        "turn": snapshot.get("turn"),
        "is_check": snapshot.get("is_check"),
        "is_game_over": snapshot.get("is_game_over"),
        "result": snapshot.get("result"),
        "robot_busy": snapshot.get("robot_busy"),
        "last_error": snapshot.get("last_error"),
        "legal_moves_count": len(snapshot.get("legal_moves") or []),
        "fullmove_number": snapshot.get("fullmove_number"),
        "halfmove_clock": snapshot.get("halfmove_clock"),
        "stockfish": {
            "display": (analysis or {}).get("current_display"),
            "depth": (analysis or {}).get("depth"),
            "max_depth": (analysis or {}).get("max_depth"),
            "elapsed_ms": (analysis or {}).get("elapsed_ms"),
            "search_elapsed_ms": (analysis or {}).get("search_elapsed_ms"),
            "best_moves": best_moves,
        },
        "position_features": extras,
    }


# --------------------------------------------------------------------- helpers


def _phase_label(board: chess.Board) -> str:
    """Coarse opening/middlegame/endgame label based on remaining material."""
    pieces = sum(1 for piece in board.piece_map().values() if piece.piece_type != chess.KING)
    queens = sum(1 for piece in board.piece_map().values() if piece.piece_type == chess.QUEEN)
    move_no = board.fullmove_number

    if move_no <= 12 and pieces >= 24:
        return "opening"
    if pieces <= 10 or queens == 0:
        return "endgame"
    return "middlegame"


def _material_balance(board: chess.Board) -> dict[str, Any]:
    values = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
    }
    white = 0
    black = 0
    for piece in board.piece_map().values():
        v = values[piece.piece_type]
        if piece.color == chess.WHITE:
            white += v
        else:
            black += v
    diff = white - black
    if diff == 0:
        summary = "Material is even"
    elif diff > 0:
        summary = f"White is up {diff} point{'s' if diff != 1 else ''}"
    else:
        summary = f"Black is up {-diff} point{'s' if diff != -1 else ''}"
    return {"white": white, "black": black, "diff": diff, "summary": summary}


def _king_safety(board: chess.Board) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for color, label in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        king_square = board.king(color)
        if king_square is None:
            info[label] = "no king (illegal position)"
            continue
        rights = board.castling_rights
        can_kingside = bool(rights & (chess.BB_H1 if color == chess.WHITE else chess.BB_H8))
        can_queenside = bool(rights & (chess.BB_A1 if color == chess.WHITE else chess.BB_A8))
        castled = (
            (color == chess.WHITE and king_square in (chess.G1, chess.C1))
            or (color == chess.BLACK and king_square in (chess.G8, chess.C8))
        )
        if castled:
            info[label] = "castled"
        elif can_kingside or can_queenside:
            sides = []
            if can_kingside:
                sides.append("kingside")
            if can_queenside:
                sides.append("queenside")
            info[label] = "castling rights " + " and ".join(sides)
        else:
            info[label] = "king is exposed (no castling rights)"
    return info


def _development_status(board: chess.Board) -> dict[str, Any]:
    starting_minor_squares = {
        chess.WHITE: {chess.B1, chess.G1, chess.C1, chess.F1},
        chess.BLACK: {chess.B8, chess.G8, chess.C8, chess.F8},
    }
    out: dict[str, Any] = {}
    for color, label in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        undeveloped = 0
        for square in starting_minor_squares[color]:
            piece = board.piece_at(square)
            if piece and piece.color == color and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                undeveloped += 1
        out[label] = {"undeveloped_minors": undeveloped}
    return out


# --------------------------------------------------------------------- coach


def rule_based_coach(context: dict[str, Any], question: str | None = None) -> str:
    """Deterministic teaching response. No filler, no boilerplate disclaimers.

    The output focuses on:
    1. Position overview (phase, material, side to move, evaluation).
    2. Concrete top-move guidance with the line and the human idea.
    3. Practical tips that match the phase and the asked question.
    """
    stockfish = context.get("stockfish") or {}
    features = context.get("position_features") or {}
    moves = stockfish.get("best_moves") or []
    top = moves[0] if moves else {}
    alt = moves[1:3]

    turn = context.get("turn", "white")
    move_no = context.get("fullmove_number") or 1
    score = stockfish.get("display") or "--"
    depth = stockfish.get("depth")
    depth_text = f"depth {depth}" if depth else "shallow read"
    phase = features.get("phase", "middlegame")
    material = (features.get("material_balance") or {}).get("summary") or "Material is even"

    paragraphs: list[str] = []

    # ── 1. Overview ─────────────────────────────────────────────────────────
    overview = (
        f"Move {move_no}, {turn} to move. We are in the {phase}. "
        f"Stockfish reads {score} ({depth_text}). {material}."
    )
    if context.get("is_check"):
        overview += " The side to move is in check, so every reply must address the threat."
    if context.get("is_game_over"):
        overview += f" The game is over: {context.get('result') or 'no result reported'}."
    paragraphs.append(overview)

    # ── 2. Top move and the plan ───────────────────────────────────────────
    if top:
        pv_line = " ".join(top.get("pv") or [])
        intent = _move_intent(top.get("san") or "", phase)
        plan = (
            f"Best move: {top.get('san')} ({top.get('uci')}) at {top.get('score')}. "
            f"Idea: {intent}"
        )
        if pv_line:
            plan += f" Engine line: {pv_line}."
        paragraphs.append(plan)
    else:
        paragraphs.append(
            "No engine candidate is ready yet. Look at the position structurally: "
            "find the most active piece for the side to move and the safest king."
        )

    # ── 3. Alternatives ────────────────────────────────────────────────────
    if alt:
        alt_lines = []
        for option in alt:
            alt_lines.append(
                f"{option.get('san')} ({option.get('score')})"
            )
        paragraphs.append("Other candidates worth comparing: " + ", ".join(alt_lines) + ".")

    # ── 4. Practical guidance by phase ─────────────────────────────────────
    paragraphs.append(_phase_guidance(phase, features, turn))

    # ── 5. Tailored hint based on the question ─────────────────────────────
    if question:
        paragraphs.append(_question_hint(question, top, phase))

    return "\n\n".join(paragraphs)


def _move_intent(san: str, phase: str) -> str:
    """Heuristic plain-language label for a candidate move."""
    if not san:
        return "no move available"
    if san.startswith("O-O-O"):
        return "long castle to bring the king to safety and connect the rooks."
    if san.startswith("O-O"):
        return "short castle, activating the rook and tucking the king away."
    if "+" in san:
        return "give check to disrupt the opponent's coordination and force a reply."
    if "#" in san:
        return "deliver checkmate."
    if "x" in san:
        return "capture to gain material or remove a key defender."
    if san[0].islower():
        return "advance a pawn to claim space and shape the structure."
    if san.startswith("N"):
        return "develop or reroute the knight toward an active outpost."
    if san.startswith("B"):
        return "place the bishop on a long, open diagonal."
    if san.startswith("R"):
        return "shift the rook to an open or semi-open file."
    if san.startswith("Q"):
        return "bring the queen to a coordinated square without exposing it."
    if san.startswith("K"):
        return "step the king to a safer square (often important in endgames)." if phase == "endgame" else "move the king as a last resort."
    return "improve piece coordination."


def _phase_guidance(phase: str, features: dict[str, Any], turn: str) -> str:
    development = features.get("development") or {}
    side = development.get(turn, {})
    undeveloped = side.get("undeveloped_minors") if isinstance(side, dict) else None

    if phase == "opening":
        tip = (
            "Opening priorities: develop knights then bishops, contest the centre, "
            "and castle early."
        )
        if isinstance(undeveloped, int) and undeveloped > 0:
            tip += f" {turn.capitalize()} still has {undeveloped} minor piece(s) on its starting square."
        return tip
    if phase == "endgame":
        return (
            "Endgame priorities: activate the king, push passed pawns, and trade pieces "
            "when you are ahead in material. Keep an eye on king opposition and the "
            "rule of the square."
        )
    return (
        "Middlegame priorities: improve your worst piece, find weak squares in the "
        "opponent's camp, and look for tactics on long diagonals, open files, and "
        "exposed kings."
    )


def _question_hint(question: str, top: dict[str, Any], phase: str) -> str:
    """Map free-form questions to a focused answer about this position."""
    q = question.strip().lower()
    if not q:
        return ""

    if any(word in q for word in ["why", "explain", "reason"]):
        if top.get("san"):
            return (
                f"Why {top['san']} works: it scores best because the resulting line "
                "improves piece activity faster than the alternatives and keeps the "
                "king safe."
            )
        return "There is no candidate to justify yet; ask again once the engine reports a top move."

    if any(word in q for word in ["plan", "strategy", "do next", "what next"]):
        if phase == "opening":
            return "Plan: finish development, castle, then bring rooks to central files."
        if phase == "endgame":
            return "Plan: centralise the king, push the most advanced pawn, and trade into a winning king-and-pawn race."
        return "Plan: identify the worst-placed piece, improve it, and target a weak square or open file."

    if any(word in q for word in ["mistake", "blunder", "wrong"]):
        return (
            "Spotting mistakes: compare the engine's top move with the move that was "
            "actually considered. A jump in evaluation larger than ~0.6 usually marks an inaccuracy."
        )

    if any(word in q for word in ["teach", "learn", "student", "beginner"]):
        return (
            "Teaching tip: name the move type out loud (development, capture, check, "
            "castling) before playing it. That habit catches most one-move blunders."
        )

    return f"On the question: focus on {top.get('san') or 'the most active piece'} and the resulting plan above."


# --------------------------------------------------------------------- LLM


class LlmCoach:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def explain(
        self,
        *,
        context: dict[str, Any],
        question: str | None = None,
        style: str = "student",
    ) -> dict[str, Any]:
        if not self.settings.llm_coach_enabled or not self.settings.llm_api_key:
            return {
                "source": "local_fallback",
                "configured": False,
                "answer": rule_based_coach(context, question),
                "context": context,
            }

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are GhostMate's chess coach. Teach clearly using the supplied "
                        "Stockfish and board-state data. Do not invent board facts. Keep the "
                        "response focused on the position, the engine's top moves, and the "
                        "plan the student should follow next."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "style": style,
                        "question": question or "Explain this position and the best candidate moves.",
                        "context": context,
                    }),
                },
            ],
            "temperature": 0.35,
            "max_tokens": self.settings.llm_max_tokens,
        }
        url = self.settings.llm_api_base.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=self.settings.llm_timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    return {
                        "source": "llm_error",
                        "configured": True,
                        "answer": rule_based_coach(context, question),
                        "error": data,
                        "context": context,
                    }

        answer = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return {
            "source": "llm",
            "configured": True,
            "model": self.settings.llm_model,
            "answer": answer or rule_based_coach(context, question),
            "context": context,
        }
