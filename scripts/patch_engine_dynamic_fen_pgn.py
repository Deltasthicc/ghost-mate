from pathlib import Path
import re
import shutil
from datetime import datetime

root = Path.cwd()
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak_engine_{stamp}"))


# ---------------------------------------------------------------------
# 1. Replace routes.py with clean engine + FEN + PGN support
# ---------------------------------------------------------------------
routes_path = root / "host/app/api/routes.py"
backup(routes_path)

routes_path.write_text(r'''from __future__ import annotations

import asyncio
from io import StringIO

import chess
import chess.engine
import chess.pgn
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from host.app.domain.events import Event, EventType

router = APIRouter()


class MoveRequest(BaseModel):
    uci: str


class RobotMoveRequest(BaseModel):
    source: str
    target: str
    capture: bool = False
    victim: str | None = None


class FenRequest(BaseModel):
    fen: str


class PgnRequest(BaseModel):
    pgn: str


def _score_cp_white(score: chess.engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


def _score_display_white(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is not None:
        if mate > 0:
            return f"M{mate}"
        if mate < 0:
            return f"-M{abs(mate)}"
        return "M0"

    cp = score.score()
    if cp is None:
        return "--"

    return f"{cp / 100:+.2f}"


def _mate_display_white(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is None:
        return "—"
    if mate > 0:
        return f"White mates in {mate}"
    if mate < 0:
        return f"Black mates in {abs(mate)}"
    return "Mate now"


def _pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 8) -> list[str]:
    copy = board.copy(stack=False)
    readable: list[str] = []

    for move in pv[:limit]:
        try:
            if move in copy.legal_moves:
                readable.append(copy.san(move))
                copy.push(move)
            else:
                readable.append(move.uci())
                break
        except Exception:
            readable.append(move.uci())
            break

    return readable


def _stockfish_analysis_sync(
    board: chess.Board,
    stockfish_path: str,
    move_time_s: float,
    multipv: int,
) -> dict:
    if board.is_game_over(claim_draw=True):
        result = board.result(claim_draw=True)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": None,
            "score_view": "white",
            "current_display": result,
            "current_display_white": result,
            "current_score_cp": None,
            "current_score_cp_white": None,
            "mate_in": None,
            "mate_display": result,
            "best_moves": [],
            "note": "Game is over.",
        }

    legal_moves = list(board.legal_moves)
    safe_multipv = max(1, min(int(multipv), 5, len(legal_moves)))
    limit = chess.engine.Limit(time=max(0.05, float(move_time_s)))

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        infos = engine.analyse(board, limit, multipv=safe_multipv)

    info_list = [infos] if isinstance(infos, dict) else list(infos)

    best_moves = []
    top_depth = None
    current_white_score: chess.engine.Score | None = None

    for rank, info in enumerate(info_list, start=1):
        score_obj = info.get("score")
        pv = info.get("pv") or []

        if not score_obj or not pv:
            continue

        move = pv[0]
        if move not in board.legal_moves:
            continue

        white_score = score_obj.pov(chess.WHITE)

        depth = info.get("depth")
        if isinstance(depth, int) and (top_depth is None or depth > top_depth):
            top_depth = depth

        if current_white_score is None:
            current_white_score = white_score

        display = _score_display_white(white_score)

        best_moves.append(
            {
                "rank": rank,
                "uci": move.uci(),
                "san": board.san(move),

                # White-centric values only:
                # positive = White better, negative = Black better.
                "score_cp": _score_cp_white(white_score),
                "score_cp_white": _score_cp_white(white_score),
                "score_display": display,
                "score_display_white": display,

                # Legacy aliases kept white-centric to avoid sign confusion.
                "score_cp_turn": _score_cp_white(white_score),
                "score_display_turn": display,

                "mate_in": white_score.mate(),
                "mate_display": _mate_display_white(white_score),
                "pv": _pv_to_san(board, list(pv)),
            }
        )

    if current_white_score is None:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": top_depth,
            "score_view": "white",
            "current_display": "--",
            "current_display_white": "--",
            "current_score_cp": None,
            "current_score_cp_white": None,
            "mate_in": None,
            "mate_display": "—",
            "best_moves": [],
            "note": "Stockfish returned no usable legal move.",
        }

    current_display = _score_display_white(current_white_score)

    return {
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "depth": top_depth,
        "score_view": "white",

        # Canonical eval fields.
        "current_display": current_display,
        "current_score_cp": _score_cp_white(current_white_score),

        # Explicit White-POV fields.
        "current_display_white": current_display,
        "current_score_cp_white": _score_cp_white(current_white_score),

        # Legacy aliases kept white-centric.
        "current_display_turn": current_display,
        "current_score_cp_turn": _score_cp_white(current_white_score),

        "mate_in": current_white_score.mate(),
        "mate_display": _mate_display_white(current_white_score),
        "best_moves": best_moves,
        "note": (
            "All scores are White-centric: positive means White is better, "
            "negative means Black is better. Move ranking is still Stockfish MultiPV "
            "for the side to move."
        ),
    }


def _final_board_from_pgn(pgn_text: str) -> chess.Board:
    game = chess.pgn.read_game(StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Could not parse PGN. Paste a valid PGN game.")

    board = game.board()
    for move in game.mainline_moves():
        board.push(move)

    return board


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/state")
async def state(request: Request) -> dict:
    return request.app.state.game.snapshot()


@router.post("/game/new")
async def new_game(request: Request, fen: str | None = None) -> dict:
    try:
        request.app.state.game.new_game(fen)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

    snapshot = request.app.state.game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


@router.post("/position/fen")
async def load_fen(request: Request, body: FenRequest) -> dict:
    try:
        board = chess.Board(body.fen.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

    request.app.state.game.new_game(board.fen())
    snapshot = request.app.state.game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


@router.post("/position/pgn")
async def load_pgn(request: Request, body: PgnRequest) -> dict:
    try:
        board = _final_board_from_pgn(body.pgn)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.app.state.game.new_game(board.fen())
    snapshot = request.app.state.game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


@router.post("/move/human")
async def human_move(request: Request, body: MoveRequest) -> dict:
    try:
        move = request.app.state.game.push_uci(body.uci)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    snapshot = request.app.state.game.snapshot()
    await request.app.state.events.publish(
        Event(EventType.LOCAL_MOVE_CANDIDATE, {"uci": move.uci(), "fen": request.app.state.game.board.fen()})
    )
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


@router.post("/move/robot")
async def robot_move(request: Request, body: RobotMoveRequest) -> dict:
    motion = request.app.state.motion
    if body.capture and body.victim:
        reply = await motion.capture_move(body.victim, body.source, body.target)
    else:
        reply = await motion.move_square_to_square(body.source, body.target, body.capture)

    if not reply.ok:
        raise HTTPException(status_code=500, detail=reply.err or "motion failed")

    return {"ok": True, "reply": reply.raw}


@router.post("/hardware/home")
async def hardware_home(request: Request) -> dict:
    reply = await request.app.state.motion.home()
    request.app.state.safety.homed = reply.ok
    return {"ok": reply.ok, "err": reply.err}


@router.post("/hardware/park")
async def hardware_park(request: Request) -> dict:
    reply = await request.app.state.motion.park()
    return {"ok": reply.ok, "err": reply.err}


@router.post("/hardware/scan")
async def hardware_scan(request: Request, full: bool = True) -> dict:
    reply = await request.app.state.motion.scan(full=full)
    return {"ok": reply.ok, "err": reply.err}


@router.get("/board/snapshot")
async def board_snapshot(request: Request) -> dict:
    return request.app.state.board_sensor.latest.to_payload()


@router.get("/engine/analysis")
async def engine_analysis(request: Request, multipv: int = 5) -> dict:
    settings = request.app.state.settings
    board = request.app.state.game.board.copy(stack=False)

    try:
        return await asyncio.to_thread(
            _stockfish_analysis_sync,
            board,
            settings.stockfish_path,
            settings.engine_move_time_s,
            multipv,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish executable not found at {settings.stockfish_path!r}. Set STOCKFISH_PATH in .env.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stockfish analysis failed: {exc}") from exc
''')


# ---------------------------------------------------------------------
# 2. Patch HTML
# ---------------------------------------------------------------------
html_path = root / "host/app/ui/templates/index.html"
backup(html_path)
html = html_path.read_text()

engine_card = '''        <article class="card">
          <p class="kicker">Stockfish</p>
          <h2>Top 5 Move Explorer</h2>
          <div id="engine-summary" class="engine-summary">Stockfish analysis loading...</div>
          <input id="move-filter" class="search" placeholder="Filter suggested moves..." />
          <div id="legal-moves" class="move-list engine-move-list"></div>
        </article>'''

html = re.sub(
    r'\s*<article class="card">\s*<p class="kicker">(?:Legal Moves|Stockfish)</p>\s*<h2>.*?</h2>.*?<div id="legal-moves"[^>]*></div>\s*</article>',
    "\n" + engine_card,
    html,
    flags=re.DOTALL,
)

position_card = '''        <article class="card" id="position-loader">
          <p class="kicker">Position Setup</p>
          <h2>Load FEN / PGN</h2>
          <textarea id="position-text" class="position-text" placeholder="Paste a FEN, or paste a full PGN game here."></textarea>
          <div class="button-row">
            <button id="load-fen" class="btn soft">Load FEN</button>
            <button id="load-pgn" class="btn primary">Load PGN Final Position</button>
          </div>
          <p class="hint">Use this for puzzle-style analysis. After loading, the board becomes playable from that position and Stockfish updates automatically.</p>
        </article>'''

if 'id="position-loader"' not in html:
    html = html.replace(engine_card, position_card + "\n\n" + engine_card)

html_path.write_text(html)


# ---------------------------------------------------------------------
# 3. Append robust frontend patch
# ---------------------------------------------------------------------
js_path = root / "host/app/ui/static/app.js"
backup(js_path)
js = js_path.read_text()

start = "// === GhostMate Stockfish dynamic analysis patch START ==="
end = "// === GhostMate Stockfish dynamic analysis patch END ==="

if start in js and end in js:
    js = re.sub(
        re.escape(start) + r".*?" + re.escape(end),
        "",
        js,
        flags=re.DOTALL,
    )

js += r'''

// === GhostMate Stockfish dynamic analysis patch START ===

state.engine = state.engine || null;
state.engineLoading = false;
state.engineError = null;
state.engineSeq = 0;
state.engineInterval = null;
state.engineIntervalMs = 3000;

function whiteEvalText(analysis) {
  if (!analysis) return "—";
  return analysis.current_display || analysis.current_display_white || "—";
}

function mateTextWhite(analysis) {
  if (!analysis) return "Mate: —";
  if (analysis.mate_display) return analysis.mate_display;
  const mate = analysis.mate_in;
  if (mate === null || mate === undefined) return "Mate: —";
  if (mate > 0) return `White mates in ${mate}`;
  if (mate < 0) return `Black mates in ${Math.abs(mate)}`;
  return "Mate now";
}

function renderEnginePanel() {
  const summary = el("engine-summary");
  const box = el("legal-moves");
  if (!box) return;

  const analysis = state.engine;
  const filter = (el("move-filter")?.value || "").trim().toLowerCase();

  if (summary) {
    if (state.engineLoading && !analysis) {
      summary.textContent = "Stockfish is analyzing...";
    } else if (state.engineError) {
      summary.textContent = `Stockfish error: ${state.engineError}`;
    } else if (analysis) {
      const updated = analysis.updated_at ? ` · updated ${analysis.updated_at}` : "";
      summary.innerHTML = `
        <strong>Position value:</strong> ${whiteEvalText(analysis)}
        <span class="muted">(White POV: + = White better, − = Black better)</span><br>
        <strong>Turn:</strong> ${analysis.turn}
        · <strong>${mateTextWhite(analysis)}</strong>
        · depth ${analysis.depth ?? "?"}${updated}<br>
        <span class="muted">Moves are ranked by Stockfish for the side to move. Scores are always White POV.</span>
      `;
    } else {
      summary.textContent = "No Stockfish analysis yet.";
    }
  }

  box.innerHTML = "";

  if (state.engineLoading && !analysis) {
    box.innerHTML = `<span class="hint">Analyzing position...</span>`;
    return;
  }

  if (state.engineError) {
    box.innerHTML = `<span class="hint">${state.engineError}</span>`;
    return;
  }

  const moves = (analysis?.best_moves || []).filter((move) => {
    const haystack = `${move.uci} ${move.san} ${move.score_display || ""} ${(move.pv || []).join(" ")}`.toLowerCase();
    return haystack.includes(filter);
  });

  if (!moves.length) {
    box.innerHTML = `<span class="hint">No Stockfish suggestions for this position.</span>`;
    return;
  }

  moves.forEach((move) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "engine-move-card";

    const score = move.score_display || move.score_display_white || "—";
    const mate = move.mate_display && move.mate_display !== "—" ? ` · ${move.mate_display}` : "";

    card.innerHTML = `
      <span class="engine-rank">#${move.rank}</span>
      <span class="engine-main">
        <strong>${move.san}</strong>
        <code>${move.uci}</code>
      </span>
      <span class="engine-score">${score}${mate}</span>
      <small>PV: ${(move.pv || []).join(" ") || "—"}</small>
    `;

    card.title = "Click to play this Stockfish suggested move";
    card.addEventListener("click", () => sendHumanMove(move.uci));
    box.appendChild(card);
  });
}

async function refreshEngineAnalysis({ silent = false } = {}) {
  if (!state.game?.fen) return;
  if (state.engineLoading) return;

  const requestId = ++state.engineSeq;
  state.engineLoading = true;
  state.engineError = null;

  if (!silent) renderEnginePanel();

  try {
    const analysis = await api("/api/engine/analysis?multipv=5");

    if (requestId !== state.engineSeq) return;

    analysis.updated_at = new Date().toLocaleTimeString();
    state.engine = analysis;
    state.engineLoading = false;
    state.engineError = null;

    // Keep old evaluation UI consistent if any older code reads state.game.evaluation.
    if (state.game) {
      state.game.evaluation = {
        display: analysis.current_display || analysis.current_display_white || "--",
        score_cp: analysis.current_score_cp ?? analysis.current_score_cp_white ?? null,
        score_pawns: analysis.current_score_cp == null ? null : analysis.current_score_cp / 100,
        mate_in: analysis.mate_in,
        source: "stockfish",
        note: "White POV: positive means White is better, negative means Black is better.",
      };
    }

    renderGame();
    renderEnginePanel();
  } catch (err) {
    if (requestId !== state.engineSeq) return;

    state.engineLoading = false;
    state.engineError = err.message;
    renderEnginePanel();
  }
}

function queueEngineAnalysis(delayMs = 150) {
  clearTimeout(queueEngineAnalysis.timer);
  queueEngineAnalysis.timer = setTimeout(() => refreshEngineAnalysis({ silent: true }), delayMs);
}

const __stockfishOriginalRenderLegalMoves = renderLegalMoves;
renderLegalMoves = function patchedRenderLegalMoves() {
  renderEnginePanel();
};

const __stockfishOriginalRenderGame = renderGame;
renderGame = function patchedRenderGame() {
  __stockfishOriginalRenderGame();
  renderEnginePanel();
};

const __stockfishOriginalSendHumanMove = sendHumanMove;
sendHumanMove = async function patchedSendHumanMove(rawMove) {
  await __stockfishOriginalSendHumanMove(rawMove);
  queueEngineAnalysis(50);
};

const __stockfishOriginalRefreshState = refreshState;
refreshState = async function patchedRefreshState() {
  await __stockfishOriginalRefreshState();
  queueEngineAnalysis(120);
};

if (typeof renderEvaluationUI === "function") {
  renderEvaluationUI = function patchedEvaluationUI() {
    const evaluation = state.engine || state.game?.evaluation;
    const display = evaluation?.current_display || evaluation?.current_display_white || evaluation?.display || "—";
    const mate = state.engine ? mateTextWhite(state.engine) : "Mate: —";

    const statusSmall = el("game-result");
    if (statusSmall) {
      const resultText = state.game?.result || "No result yet";
      statusSmall.innerHTML = `${resultText}<br><span class="eval-inline">Eval ${display} · ${mate} · White POV</span>`;
    }
  };
}

async function loadFenFromInput() {
  const text = (el("position-text")?.value || "").trim();
  if (!text) {
    showToast("Paste a FEN first.");
    return;
  }

  try {
    state.game = await api("/api/position/fen", {
      method: "POST",
      body: JSON.stringify({ fen: text }),
    });

    state.selected = null;
    state.pendingMove = "";
    state.lastMove = null;

    renderGame();
    queueEngineAnalysis(50);
    addEvent("FEN_LOADED", { fen: state.game.fen });
    showToast("FEN loaded. You can play from this position.");
  } catch (err) {
    addEvent("FEN_LOAD_FAILED", { error: err.message });
    showToast(err.message);
  }
}

async function loadPgnFromInput() {
  const text = (el("position-text")?.value || "").trim();
  if (!text) {
    showToast("Paste a PGN first.");
    return;
  }

  try {
    state.game = await api("/api/position/pgn", {
      method: "POST",
      body: JSON.stringify({ pgn: text }),
    });

    state.selected = null;
    state.pendingMove = "";
    state.lastMove = null;

    renderGame();
    queueEngineAnalysis(50);
    addEvent("PGN_LOADED", { fen: state.game.fen });
    showToast("PGN loaded at final position. You can play from here.");
  } catch (err) {
    addEvent("PGN_LOAD_FAILED", { error: err.message });
    showToast(err.message);
  }
}

function initStockfishDynamicPanel() {
  el("load-fen")?.addEventListener("click", loadFenFromInput);
  el("load-pgn")?.addEventListener("click", loadPgnFromInput);
  el("move-filter")?.addEventListener("input", renderEnginePanel);

  el("new-game")?.addEventListener("click", () => queueEngineAnalysis(250));
  el("refresh-all")?.addEventListener("click", () => queueEngineAnalysis(250));

  clearInterval(state.engineInterval);
  state.engineInterval = setInterval(() => {
    refreshEngineAnalysis({ silent: true });
  }, state.engineIntervalMs);

  queueEngineAnalysis(500);
}

window.addEventListener("DOMContentLoaded", () => {
  setTimeout(initStockfishDynamicPanel, 700);
});

// === GhostMate Stockfish dynamic analysis patch END ===
'''

js_path.write_text(js)


# ---------------------------------------------------------------------
# 4. CSS patch
# ---------------------------------------------------------------------
css_path = root / "host/app/ui/static/style.css"
backup(css_path)
css = css_path.read_text()

css_start = "/* === GhostMate Stockfish UI patch START === */"
css_end = "/* === GhostMate Stockfish UI patch END === */"

if css_start in css and css_end in css:
    css = re.sub(
        re.escape(css_start) + r".*?" + re.escape(css_end),
        "",
        css,
        flags=re.DOTALL,
    )

css += r'''

/* === GhostMate Stockfish UI patch START === */

.engine-summary {
  margin: 12px 0 10px;
  padding: 12px 14px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.48);
  color: var(--ink-soft);
  font-size: 0.92rem;
  line-height: 1.45;
}

body.dark .engine-summary {
  background: rgba(255,255,255,0.05);
}

.engine-summary strong {
  color: var(--ink);
}

.muted {
  color: var(--ink-soft);
  opacity: 0.9;
}

.engine-move-list {
  display: grid;
  gap: 10px;
  max-height: 390px;
  overflow: auto;
  padding-right: 4px;
}

.engine-move-card {
  width: 100%;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  text-align: left;
  padding: 12px 13px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.58);
  color: var(--ink);
  cursor: pointer;
  transition: 0.16s ease;
}

body.dark .engine-move-card {
  background: rgba(255,255,255,0.05);
}

.engine-move-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(31, 38, 135, 0.15);
}

.engine-rank {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 900;
  color: #fff;
  background: linear-gradient(135deg, #7b73ff, #7db4ff);
}

.engine-main {
  display: grid;
  gap: 3px;
}

.engine-main strong {
  font-size: 1.05rem;
}

.engine-main code {
  color: var(--ink-soft);
}

.engine-score {
  font-weight: 900;
  color: #5d66d8;
  white-space: nowrap;
}

.engine-move-card small {
  grid-column: 2 / -1;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.position-text {
  width: 100%;
  min-height: 150px;
  resize: vertical;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.56);
  color: var(--ink);
  padding: 14px 16px;
  border-radius: 18px;
  outline: none;
  font: inherit;
  line-height: 1.45;
}

body.dark .position-text {
  background: rgba(255,255,255,0.05);
}

.position-text:focus {
  border-color: rgba(125, 121, 255, 0.38);
  box-shadow: 0 0 0 4px rgba(126, 181, 255, 0.14);
}

/* === GhostMate Stockfish UI patch END === */
'''

css_path.write_text(css)

print("✅ Dynamic Stockfish + White POV eval + FEN/PGN loader patch applied.")
