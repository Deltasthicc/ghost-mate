from pathlib import Path
import re
import shutil
from datetime import datetime

root = Path.cwd()
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak_v3_{stamp}"))


# ------------------------------------------------------------
# 1. Backend: add safe White-POV engine endpoint + FEN/PGN loaders
# ------------------------------------------------------------
routes_path = root / "host/app/api/routes.py"
backup(routes_path)
routes = routes_path.read_text()

# Fix old Stockfish endpoint if it used side-to-move POV anywhere.
routes = routes.replace(".pov(board.turn)", ".pov(chess.WHITE)")
routes = routes.replace(
    "Turn score is from the player-to-move's point of view.",
    "All scores are White-centric: positive means White is better, negative means Black is better.",
)

if "GM_DYNAMIC_STOCKFISH_V3_BACKEND" not in routes:
    routes += r'''

# === GM_DYNAMIC_STOCKFISH_V3_BACKEND START ===
# Extra analysis/position endpoints. These are intentionally additive so existing
# routes/tests remain intact.

import asyncio as _gm_asyncio
from io import StringIO as _gm_StringIO

import chess as _gm_chess
import chess.engine as _gm_chess_engine
import chess.pgn as _gm_chess_pgn
from pydantic import BaseModel as _GMBaseModel


class _GMFenRequest(_GMBaseModel):
    fen: str


class _GMPgnRequest(_GMBaseModel):
    pgn: str


def _gm_score_cp_white(score: _gm_chess_engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


def _gm_score_display_white(score: _gm_chess_engine.Score) -> str:
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


def _gm_mate_display_white(score: _gm_chess_engine.Score) -> str:
    mate = score.mate()
    if mate is None:
        return "—"
    if mate > 0:
        return f"White mates in {mate}"
    if mate < 0:
        return f"Black mates in {abs(mate)}"
    return "Mate now"


def _gm_pv_to_san(board: _gm_chess.Board, pv: list[_gm_chess.Move], limit: int = 8) -> list[str]:
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


def _gm_stockfish_live_sync(
    board: _gm_chess.Board,
    stockfish_path: str,
    move_time_s: float,
    multipv: int,
) -> dict:
    if board.is_game_over(claim_draw=True):
        result = board.result(claim_draw=True)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == _gm_chess.WHITE else "black",
            "score_view": "white",
            "depth": None,
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
    limit = _gm_chess_engine.Limit(time=max(0.05, float(move_time_s)))

    with _gm_chess_engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        infos = engine.analyse(board, limit, multipv=safe_multipv)

    info_list = [infos] if isinstance(infos, dict) else list(infos)

    best_moves = []
    top_depth = None
    current_white_score = None

    for rank, info in enumerate(info_list, start=1):
        score_obj = info.get("score")
        pv = info.get("pv") or []
        if not score_obj or not pv:
            continue

        move = pv[0]
        if move not in board.legal_moves:
            continue

        white_score = score_obj.pov(_gm_chess.WHITE)

        depth = info.get("depth")
        if isinstance(depth, int) and (top_depth is None or depth > top_depth):
            top_depth = depth

        if current_white_score is None:
            current_white_score = white_score

        display = _gm_score_display_white(white_score)

        best_moves.append(
            {
                "rank": rank,
                "uci": move.uci(),
                "san": board.san(move),

                # Canonical White-POV fields.
                "score_cp": _gm_score_cp_white(white_score),
                "score_display": display,

                # Explicit White-POV fields.
                "score_cp_white": _gm_score_cp_white(white_score),
                "score_display_white": display,

                # Legacy aliases kept White-POV to avoid side-to-move sign confusion.
                "score_cp_turn": _gm_score_cp_white(white_score),
                "score_display_turn": display,

                "mate_in": white_score.mate(),
                "mate_display": _gm_mate_display_white(white_score),
                "pv": _gm_pv_to_san(board, list(pv)),
            }
        )

    if current_white_score is None:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == _gm_chess.WHITE else "black",
            "score_view": "white",
            "depth": top_depth,
            "current_display": "--",
            "current_display_white": "--",
            "current_score_cp": None,
            "current_score_cp_white": None,
            "mate_in": None,
            "mate_display": "—",
            "best_moves": [],
            "note": "Stockfish returned no usable legal move.",
        }

    display = _gm_score_display_white(current_white_score)

    return {
        "fen": board.fen(),
        "turn": "white" if board.turn == _gm_chess.WHITE else "black",
        "score_view": "white",
        "depth": top_depth,

        # Canonical fields.
        "current_display": display,
        "current_score_cp": _gm_score_cp_white(current_white_score),

        # Explicit White-POV fields.
        "current_display_white": display,
        "current_score_cp_white": _gm_score_cp_white(current_white_score),

        # Legacy aliases kept White-POV.
        "current_display_turn": display,
        "current_score_cp_turn": _gm_score_cp_white(current_white_score),

        "mate_in": current_white_score.mate(),
        "mate_display": _gm_mate_display_white(current_white_score),
        "best_moves": best_moves,
        "note": (
            "All scores are White-centric: positive means White is better, "
            "negative means Black is better. Move ranking is Stockfish MultiPV "
            "for the side to move."
        ),
    }


async def _gm_set_game_board_from_fen(request: Request, fen: str) -> dict:
    board = _gm_chess.Board(fen)

    game = request.app.state.game

    try:
        game.new_game(board.fen())
    except TypeError:
        # Fallback for older GameState implementations.
        game.new_game()
        game.board = board

    snapshot = game.snapshot()

    try:
        await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    except Exception:
        pass

    return snapshot


def _gm_final_board_from_pgn(pgn_text: str) -> _gm_chess.Board:
    game = _gm_chess_pgn.read_game(_gm_StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Could not parse PGN. Paste a valid PGN game.")

    board = game.board()
    for move in game.mainline_moves():
        board.push(move)

    return board


@router.get("/engine/live")
async def gm_engine_live(request: Request, multipv: int = 5) -> dict:
    settings = request.app.state.settings
    board = request.app.state.game.board.copy(stack=False)

    try:
        return await _gm_asyncio.to_thread(
            _gm_stockfish_live_sync,
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
        raise HTTPException(status_code=500, detail=f"Stockfish live analysis failed: {exc}") from exc


@router.post("/position/fen")
async def gm_load_fen(request: Request, body: _GMFenRequest) -> dict:
    try:
        return await _gm_set_game_board_from_fen(request, body.fen.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc


@router.post("/position/pgn")
async def gm_load_pgn(request: Request, body: _GMPgnRequest) -> dict:
    try:
        board = _gm_final_board_from_pgn(body.pgn)
        return await _gm_set_game_board_from_fen(request, board.fen())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PGN: {exc}") from exc

# === GM_DYNAMIC_STOCKFISH_V3_BACKEND END ===
'''

routes_path.write_text(routes)


# ------------------------------------------------------------
# 2. Frontend JS: dynamic polling + FEN/PGN UI
# ------------------------------------------------------------
js_path = root / "host/app/ui/static/app.js"
backup(js_path)
js = js_path.read_text()

start = "// === GM_DYNAMIC_STOCKFISH_V3_UI START ==="
end = "// === GM_DYNAMIC_STOCKFISH_V3_UI END ==="

if start in js and end in js:
    js = re.sub(re.escape(start) + r".*?" + re.escape(end), "", js, flags=re.DOTALL)

js += r'''

// === GM_DYNAMIC_STOCKFISH_V3_UI START ===
(() => {
  const ENGINE_URL = "/api/engine/live?multipv=5";
  const REFRESH_MS = 3000;

  let engineAnalysis = null;
  let engineLoading = false;
  let engineError = null;
  let engineTimer = null;
  let requestSeq = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function safeToast(message) {
    if (typeof showToast === "function") showToast(message);
    else console.log(message);
  }

  function ensureStockfishUI() {
    const moveList = $("legal-moves");
    if (!moveList) return;

    const card = moveList.closest(".card") || moveList.parentElement;

    if (card) {
      const kicker = card.querySelector(".kicker");
      if (kicker) kicker.textContent = "Stockfish";

      const h2 = card.querySelector("h2");
      if (h2) h2.textContent = "Top 5 Move Explorer";

      let summary = $("engine-summary");
      if (!summary) {
        summary = document.createElement("div");
        summary.id = "engine-summary";
        summary.className = "engine-summary";
        summary.textContent = "Stockfish analysis loading...";

        const filter = $("move-filter");
        if (filter && filter.parentNode === card) {
          card.insertBefore(summary, filter);
        } else {
          card.insertBefore(summary, moveList);
        }
      }

      moveList.classList.add("engine-move-list");
    }

    if (!$("position-loader") && card) {
      const loader = document.createElement("article");
      loader.className = "card";
      loader.id = "position-loader";
      loader.innerHTML = `
        <p class="kicker">Position Setup</p>
        <h2>Load FEN / PGN</h2>
        <textarea id="position-text" class="position-text" placeholder="Paste a FEN, or paste a full PGN game here."></textarea>
        <div class="button-row">
          <button id="load-fen" class="btn soft" type="button">Load FEN</button>
          <button id="load-pgn" class="btn primary" type="button">Load PGN Final Position</button>
        </div>
        <p class="hint">Use this for puzzle-style analysis. After loading, the board becomes playable from that position and Stockfish refreshes automatically.</p>
      `;
      card.parentNode.insertBefore(loader, card);
    }

    $("load-fen")?.addEventListener("click", loadFenFromInput);
    $("load-pgn")?.addEventListener("click", loadPgnFromInput);
    $("move-filter")?.addEventListener("input", renderEnginePanel);
  }

  function evalDisplay(analysis) {
    if (!analysis) return "—";
    return analysis.current_display || analysis.current_display_white || "—";
  }

  function mateDisplay(analysis) {
    if (!analysis) return "Mate: —";
    return analysis.mate_display || "Mate: —";
  }

  function renderEnginePanel() {
    ensureStockfishUI();

    const summary = $("engine-summary");
    const box = $("legal-moves");
    if (!box) return;

    const filter = ($("move-filter")?.value || "").trim().toLowerCase();

    if (summary) {
      if (engineLoading && !engineAnalysis) {
        summary.textContent = "Stockfish is analyzing...";
      } else if (engineError) {
        summary.textContent = `Stockfish error: ${engineError}`;
      } else if (engineAnalysis) {
        summary.innerHTML = `
          <strong>Position value:</strong> ${evalDisplay(engineAnalysis)}
          <span class="muted">(White POV: + = White better, − = Black better)</span><br>
          <strong>Turn:</strong> ${engineAnalysis.turn}
          · <strong>${mateDisplay(engineAnalysis)}</strong>
          · depth ${engineAnalysis.depth ?? "?"}
          · updated ${new Date().toLocaleTimeString()}<br>
          <span class="muted">Moves are ranked by Stockfish for the side to move. Scores are always White POV.</span>
        `;
      } else {
        summary.textContent = "No Stockfish analysis yet.";
      }
    }

    box.innerHTML = "";

    if (engineLoading && !engineAnalysis) {
      box.innerHTML = `<span class="hint">Analyzing position...</span>`;
      return;
    }

    if (engineError) {
      box.innerHTML = `<span class="hint">${engineError}</span>`;
      return;
    }

    const moves = (engineAnalysis?.best_moves || []).filter((move) => {
      const haystack = `${move.uci} ${move.san} ${move.score_display || ""} ${(move.pv || []).join(" ")}`.toLowerCase();
      return haystack.includes(filter);
    });

    if (!moves.length) {
      box.innerHTML = `<span class="hint">No Stockfish suggestions for this position.</span>`;
      return;
    }

    moves.forEach((move) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "engine-move-card";

      const score = move.score_display || move.score_display_white || "—";
      const mate = move.mate_display && move.mate_display !== "—" ? ` · ${move.mate_display}` : "";

      button.innerHTML = `
        <span class="engine-rank">#${move.rank}</span>
        <span class="engine-main">
          <strong>${move.san}</strong>
          <code>${move.uci}</code>
        </span>
        <span class="engine-score">${score}${mate}</span>
        <small>PV: ${(move.pv || []).join(" ") || "—"}</small>
      `;

      button.title = "Click to play this Stockfish suggested move";
      button.addEventListener("click", async () => {
        if (typeof sendHumanMove === "function") {
          await sendHumanMove(move.uci);
          queueEngineRefresh(250);
        }
      });

      box.appendChild(button);
    });
  }

  async function refreshEngineAnalysis({ silent = false } = {}) {
    if (engineLoading) return;

    const seq = ++requestSeq;
    engineLoading = true;
    engineError = null;

    if (!silent) renderEnginePanel();

    try {
      const analysis = await api(ENGINE_URL);
      if (seq !== requestSeq) return;

      engineAnalysis = analysis;
      engineLoading = false;
      engineError = null;

      if (state?.game) {
        state.game.evaluation = {
          display: analysis.current_display || analysis.current_display_white || "--",
          score_cp: analysis.current_score_cp ?? analysis.current_score_cp_white ?? null,
          score_pawns: analysis.current_score_cp == null ? null : analysis.current_score_cp / 100,
          mate_in: analysis.mate_in,
          source: "stockfish",
          note: "White POV: positive means White is better, negative means Black is better.",
        };
      }

      if (typeof renderGame === "function") renderGame();
      renderEnginePanel();
    } catch (err) {
      if (seq !== requestSeq) return;

      engineLoading = false;
      engineError = err.message || String(err);
      renderEnginePanel();
    }
  }

  function queueEngineRefresh(delay = 150) {
    clearTimeout(queueEngineRefresh.timer);
    queueEngineRefresh.timer = setTimeout(() => refreshEngineAnalysis({ silent: true }), delay);
  }

  async function loadFenFromInput() {
    const text = ($("position-text")?.value || "").trim();
    if (!text) {
      safeToast("Paste a FEN first.");
      return;
    }

    try {
      state.game = await api("/api/position/fen", {
        method: "POST",
        body: JSON.stringify({ fen: text }),
      });

      if (typeof renderGame === "function") renderGame();
      queueEngineRefresh(100);
      safeToast("FEN loaded. You can play from this position.");
    } catch (err) {
      safeToast(err.message || String(err));
    }
  }

  async function loadPgnFromInput() {
    const text = ($("position-text")?.value || "").trim();
    if (!text) {
      safeToast("Paste a PGN first.");
      return;
    }

    try {
      state.game = await api("/api/position/pgn", {
        method: "POST",
        body: JSON.stringify({ pgn: text }),
      });

      if (typeof renderGame === "function") renderGame();
      queueEngineRefresh(100);
      safeToast("PGN loaded at final position. You can play from here.");
    } catch (err) {
      safeToast(err.message || String(err));
    }
  }

  function bootDynamicStockfish() {
    ensureStockfishUI();
    queueEngineRefresh(250);

    clearInterval(engineTimer);
    engineTimer = setInterval(() => {
      refreshEngineAnalysis({ silent: true });
    }, REFRESH_MS);

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) queueEngineRefresh(100);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(bootDynamicStockfish, 800));
  } else {
    setTimeout(bootDynamicStockfish, 800);
  }

  window.GhostMateRefreshEngine = refreshEngineAnalysis;
})();
// === GM_DYNAMIC_STOCKFISH_V3_UI END ===
'''

js_path.write_text(js)


# ------------------------------------------------------------
# 3. CSS: engine cards + FEN/PGN loader
# ------------------------------------------------------------
css_path = root / "host/app/ui/static/style.css"
backup(css_path)
css = css_path.read_text()

css_start = "/* === GM_DYNAMIC_STOCKFISH_V3_CSS START === */"
css_end = "/* === GM_DYNAMIC_STOCKFISH_V3_CSS END === */"

if css_start in css and css_end in css:
    css = re.sub(re.escape(css_start) + r".*?" + re.escape(css_end), "", css, flags=re.DOTALL)

css += r'''

/* === GM_DYNAMIC_STOCKFISH_V3_CSS START === */
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
/* === GM_DYNAMIC_STOCKFISH_V3_CSS END === */
'''

css_path.write_text(css)

print("✅ Dynamic Stockfish v3 patch applied safely.")
