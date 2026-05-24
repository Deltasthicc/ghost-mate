from pathlib import Path

root = Path.cwd()

# -----------------------------
# 1. Patch backend API routes
# -----------------------------
routes_path = root / "host/app/api/routes.py"
routes = routes_path.read_text()

if "import asyncio" not in routes:
    routes = routes.replace("from __future__ import annotations\n\n", "from __future__ import annotations\n\nimport asyncio\n")

if "import chess\nimport chess.engine" not in routes:
    routes = routes.replace("from fastapi import APIRouter, HTTPException, Request\n", "from fastapi import APIRouter, HTTPException, Request\nimport chess\nimport chess.engine\n")

engine_helpers = r'''

def _score_display(score: chess.engine.Score) -> str:
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


def _score_cp(score: chess.engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


def _pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 6) -> list[str]:
    copy = board.copy(stack=False)
    readable: list[str] = []

    for move in pv[:limit]:
        try:
            if move in copy.legal_moves:
                readable.append(copy.san(move))
                copy.push(move)
            else:
                readable.append(move.uci())
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
            "current_display_white": result,
            "current_display_turn": result,
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "best_moves": [],
            "note": f"Game is over: {result}",
        }

    legal_moves = list(board.legal_moves)
    safe_multipv = max(1, min(int(multipv), 5, len(legal_moves)))
    limit = chess.engine.Limit(time=move_time_s)

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        infos = engine.analyse(board, limit, multipv=safe_multipv)

    if isinstance(infos, dict):
        info_list = [infos]
    else:
        info_list = list(infos)

    best_moves = []
    top_depth = None
    current_white_score = None
    current_turn_score = None

    for index, info in enumerate(info_list, start=1):
        score_obj = info.get("score")
        pv = info.get("pv") or []

        if not score_obj or not pv:
            continue

        move = pv[0]

        if move not in board.legal_moves:
            continue

        white_score = score_obj.pov(chess.WHITE)
        turn_score = score_obj.pov(board.turn)

        depth = info.get("depth")
        if isinstance(depth, int) and (top_depth is None or depth > top_depth):
            top_depth = depth

        if current_white_score is None:
            current_white_score = white_score
            current_turn_score = turn_score

        best_moves.append(
            {
                "rank": index,
                "uci": move.uci(),
                "san": board.san(move),
                "score_cp_white": _score_cp(white_score),
                "score_cp_turn": _score_cp(turn_score),
                "score_display_white": _score_display(white_score),
                "score_display_turn": _score_display(turn_score),
                "mate_in": turn_score.mate(),
                "pv": _pv_to_san(board, list(pv)),
            }
        )

    if current_white_score is None or current_turn_score is None:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": top_depth,
            "current_display_white": "--",
            "current_display_turn": "--",
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "best_moves": [],
            "note": "Stockfish returned no usable legal move.",
        }

    return {
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "depth": top_depth,
        "current_display_white": _score_display(current_white_score),
        "current_display_turn": _score_display(current_turn_score),
        "current_score_cp_white": _score_cp(current_white_score),
        "current_score_cp_turn": _score_cp(current_turn_score),
        "mate_in": current_turn_score.mate(),
        "best_moves": best_moves,
        "note": (
            "White score is from White's point of view. "
            "Turn score is from the player-to-move's point of view."
        ),
    }
'''

if "_stockfish_analysis_sync" not in routes:
    marker = "router = APIRouter()\n"
    routes = routes.replace(marker, marker + engine_helpers)

engine_route = r'''

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
'''

if '@router.get("/engine/analysis")' not in routes:
    routes += engine_route

routes_path.write_text(routes)


# -----------------------------
# 2. Patch HTML move explorer
# -----------------------------
html_path = root / "host/app/ui/templates/index.html"
html = html_path.read_text()

old_html = '''        <article class="card">
          <p class="kicker">Legal Moves</p>
          <h2>Move Explorer</h2>
          <input id="move-filter" class="search" placeholder="Filter legal moves..." />
          <div id="legal-moves" class="move-list"></div>
        </article>'''

new_html = '''        <article class="card">
          <p class="kicker">Stockfish</p>
          <h2>Top 5 Move Explorer</h2>
          <div id="engine-summary" class="engine-summary">Loading engine analysis...</div>
          <input id="move-filter" class="search" placeholder="Filter suggested moves..." />
          <div id="legal-moves" class="move-list engine-move-list"></div>
        </article>'''

if old_html in html:
    html = html.replace(old_html, new_html)

html_path.write_text(html)


# -----------------------------
# 3. Patch frontend JS
# -----------------------------
js_path = root / "host/app/ui/static/app.js"
js = js_path.read_text()

if "engineLoading" not in js:
    js = js.replace(
        '''  events: [],
};''',
        '''  events: [],
  engine: null,
  engineLoading: false,
  engineError: null,
  engineSeq: 0,
};'''
    )

old_render = '''function renderLegalMoves() {
  const box = el("legal-moves");
  if (!box) return;

  const filter = (el("move-filter")?.value || "").trim().toLowerCase();
  const moves = (state.game?.legal_moves || []).filter((m) => m.includes(filter));

  box.innerHTML = "";

  if (!moves.length) {
    box.innerHTML = `<span class="hint">No matching legal moves.</span>`;
    return;
  }

  moves.forEach((move) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "move-pill";
    chip.textContent = move;
    chip.addEventListener("click", () => sendHumanMove(move));
    box.appendChild(chip);
  });
}
'''

new_render = '''function renderLegalMoves() {
  const box = el("legal-moves");
  const summary = el("engine-summary");
  if (!box) return;

  const filter = (el("move-filter")?.value || "").trim().toLowerCase();
  const analysis = state.engine;

  if (summary) {
    if (state.engineLoading) {
      summary.textContent = "Stockfish is analyzing the current position...";
    } else if (state.engineError) {
      summary.textContent = `Stockfish error: ${state.engineError}`;
    } else if (analysis) {
      const mate = analysis.mate_in === null || analysis.mate_in === undefined
        ? "Mate: —"
        : analysis.mate_in > 0
          ? `Mate for ${analysis.turn} in ${analysis.mate_in}`
          : `Mated in ${Math.abs(analysis.mate_in)}`;

      summary.innerHTML = `
        <strong>Position:</strong> ${analysis.current_display_white} from White ·
        <strong>${analysis.turn} to move:</strong> ${analysis.current_display_turn} ·
        <strong>${mate}</strong> ·
        <span>depth ${analysis.depth ?? "?"}</span>
      `;
    } else {
      summary.textContent = "No engine analysis yet.";
    }
  }

  box.innerHTML = "";

  if (state.engineLoading && !analysis) {
    box.innerHTML = `<span class="hint">Analyzing...</span>`;
    return;
  }

  if (state.engineError) {
    box.innerHTML = `<span class="hint">${state.engineError}</span>`;
    return;
  }

  const moves = (analysis?.best_moves || []).filter((move) => {
    const haystack = `${move.uci} ${move.san} ${(move.pv || []).join(" ")}`.toLowerCase();
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

    const mateText = move.mate_in === null || move.mate_in === undefined
      ? ""
      : move.mate_in > 0
        ? ` · mate in ${move.mate_in}`
        : ` · mated in ${Math.abs(move.mate_in)}`;

    card.innerHTML = `
      <span class="engine-rank">#${move.rank}</span>
      <span class="engine-main"><strong>${move.san}</strong><code>${move.uci}</code></span>
      <span class="engine-score">${move.score_display_turn}${mateText}</span>
      <small>PV: ${(move.pv || []).join(" ") || "—"}</small>
    `;

    card.title = "Click to play this Stockfish suggested move";
    card.addEventListener("click", () => sendHumanMove(move.uci));
    box.appendChild(card);
  });
}

async function refreshEngineAnalysis() {
  if (!state.game?.fen) return;

  const requestId = ++state.engineSeq;
  state.engineLoading = true;
  state.engineError = null;
  renderLegalMoves();

  try {
    const analysis = await api("/api/engine/analysis?multipv=5");

    if (requestId !== state.engineSeq) return;

    state.engine = analysis;
    state.engineLoading = false;
    state.engineError = null;

    if (state.game) {
      state.game.evaluation = {
        display: analysis.current_display_white,
        mate_in: analysis.mate_in,
        source: "stockfish",
      };
    }

    renderGame();
    renderLegalMoves();
  } catch (err) {
    if (requestId !== state.engineSeq) return;

    state.engineLoading = false;
    state.engineError = err.message;
    renderLegalMoves();
  }
}

function queueEngineAnalysis(delayMs = 120) {
  clearTimeout(queueEngineAnalysis.timer);
  queueEngineAnalysis.timer = setTimeout(refreshEngineAnalysis, delayMs);
}
'''

if old_render in js:
    js = js.replace(old_render, new_render)
elif "async function refreshEngineAnalysis()" not in js:
    raise SystemExit("Could not find renderLegalMoves() block. Open app.js and patch manually.")

js = js.replace(
    '''  state.game = await api("/api/state");
  setText("host-status", "Online");
  renderGame();''',
    '''  state.game = await api("/api/state");
  setText("host-status", "Online");
  renderGame();
  queueEngineAnalysis();'''
)

js = js.replace(
    '''    renderGame();
    addEvent("HUMAN_MOVE_APPLIED", { uci: move });''',
    '''    renderGame();
    queueEngineAnalysis();
    addEvent("HUMAN_MOVE_APPLIED", { uci: move });'''
)

js = js.replace(
    '''      renderGame();
      addEvent("NEW_GAME", { game_id: state.game.game_id });''',
    '''      renderGame();
      queueEngineAnalysis();
      addEvent("NEW_GAME", { game_id: state.game.game_id });'''
)

js = js.replace(
    '''        state.game = data.state;
        renderGame();''',
    '''        state.game = data.state;
        renderGame();
        queueEngineAnalysis();'''
)

js_path.write_text(js)


# -----------------------------
# 4. Patch CSS
# -----------------------------
css_path = root / "host/app/ui/static/style.css"
css = css_path.read_text()

if ".engine-summary" not in css:
    css += r'''

/* Stockfish analysis panel */
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
  background: rgba(255,255,255,0.04);
}

.engine-move-list {
  display: grid;
  gap: 10px;
  max-height: 360px;
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
'''

css_path.write_text(css)

print("✅ Stockfish analysis patch applied.")
