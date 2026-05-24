from pathlib import Path
import re

app_path = Path("host/app/ui/static/app.js")
css_path = Path("host/app/ui/static/style.css")

app = app_path.read_text(encoding="utf-8")

# Use solid glyphs for both colors. CSS handles side color + outline.
app = re.sub(
    r'const pieces = \{[\s\S]*?\};',
    '''const pieces = {
  P: "♟", N: "♞", B: "♝", R: "♜", Q: "♛", K: "♚",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};''',
    app,
)

# Remove old tactical patch if it exists.
app = re.sub(
    r'\n// === GhostMate tactical overlay patch START ===[\s\S]*?// === GhostMate tactical overlay patch END ===\n?',
    "\n",
    app,
)

# Smooth WS close if current file has basic reconnect code.
app = re.sub(
    r'state\.ws\.onclose\s*=\s*\([^)]*\)\s*=>\s*\{[\s\S]*?\};\s*state\.ws\.onerror',
    '''state.ws.onclose = () => {
    const pill = el("connection-status");

    if (pill) {
      pill.classList.add("offline");
      pill.innerHTML = "<i></i> Offline";
    }

    if (state.shuttingDown) {
      setText("ws-status", "Closed");
      return;
    }

    setText("ws-status", "Reconnecting");

    setTimeout(() => {
      if (!state.shuttingDown) {
        connectWebSocket();
      }
    }, 1600);
  };

  state.ws.onerror''',
    app,
)

patch = r'''
// === GhostMate tactical overlay patch START ===

state.shuttingDown = false;
state.annotations = state.annotations || [];
state.annotationDraft = null;
state.annotationBound = false;

const __ghostmateOriginalRenderGame = renderGame;
renderGame = function patchedRenderGame() {
  __ghostmateOriginalRenderGame();
  renderEvaluationUI();
};

const __ghostmateOriginalRenderBoard = renderBoard;
renderBoard = function patchedRenderBoard() {
  __ghostmateOriginalRenderBoard();
  ensureAnnotationLayer();
  renderAnnotations();
  bindAnnotationHandlers();
};

function renderEvaluationUI() {
  const evaluation = state.game?.evaluation;
  const display = evaluation?.display || "0.00";
  const source = evaluation?.source || "material";
  const mateText = evaluation?.mate_in === null || evaluation?.mate_in === undefined
    ? "Mate: —"
    : `Mate: ${evaluation.mate_in}`;

  let statusSmall = el("game-result");
  if (statusSmall) {
    const resultText = state.game?.result || "No result yet";
    statusSmall.innerHTML = `${resultText}<br><span class="eval-inline">Eval ${display} · ${mateText}</span>`;
  }

  const details = document.querySelector(".details-list");
  if (details && !el("eval-detail-row")) {
    const row = document.createElement("div");
    row.id = "eval-detail-row";
    row.innerHTML = `<span>Evaluation</span><strong id="eval-detail-value">--</strong>`;
    details.appendChild(row);
  }

  const evalDetail = el("eval-detail-value");
  if (evalDetail) {
    evalDetail.textContent = `${display} · ${source}`;
    evalDetail.title = evaluation?.note || "Positive means White is better. Negative means Black is better.";
  }
}

function squareNameFromEvent(event) {
  const node = event.target.closest?.(".square");
  return node?.dataset?.square || null;
}

function squareNameFromPoint(clientX, clientY) {
  const node = document.elementFromPoint(clientX, clientY)?.closest?.(".square");
  return node?.dataset?.square || null;
}

function squareToCenter(square) {
  const board = el("chessboard");
  const node = document.querySelector(`[data-square="${square}"]`);

  if (!board || !node) return null;

  const b = board.getBoundingClientRect();
  const r = node.getBoundingClientRect();

  return {
    x: r.left - b.left + r.width / 2,
    y: r.top - b.top + r.height / 2,
  };
}

function isValidChessAnnotation(from, to) {
  if (!from || !to || from === to) return false;

  const fx = files.indexOf(from[0]);
  const tx = files.indexOf(to[0]);
  const fy = Number(from[1]);
  const ty = Number(to[1]);

  const dx = Math.abs(tx - fx);
  const dy = Math.abs(ty - fy);

  const straight = dx === 0 || dy === 0;
  const diagonal = dx === dy;
  const knight = (dx === 1 && dy === 2) || (dx === 2 && dy === 1);

  return straight || diagonal || knight;
}

function isKnightAnnotation(from, to) {
  const fx = files.indexOf(from[0]);
  const tx = files.indexOf(to[0]);
  const fy = Number(from[1]);
  const ty = Number(to[1]);

  const dx = Math.abs(tx - fx);
  const dy = Math.abs(ty - fy);

  return (dx === 1 && dy === 2) || (dx === 2 && dy === 1);
}

function ensureAnnotationLayer() {
  const board = el("chessboard");
  if (!board || board.querySelector(".annotation-layer")) return;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("annotation-layer");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.innerHTML = `
    <defs>
      <marker id="ghostmate-arrow-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
        <path d="M0,0 L0,6 L7,3 z" class="annotation-arrow-head"></path>
      </marker>
    </defs>
  `;
  board.appendChild(svg);
}

function drawAnnotation(svg, annotation, draft = false) {
  const from = squareToCenter(annotation.from);
  const to = squareToCenter(annotation.to);

  if (!from || !to) return;

  const board = el("chessboard");
  const rect = board.getBoundingClientRect();

  const sx = (from.x / rect.width) * 100;
  const sy = (from.y / rect.height) * 100;
  const tx = (to.x / rect.width) * 100;
  const ty = (to.y / rect.height) * 100;

  if (isKnightAnnotation(annotation.from, annotation.to)) {
    const horizontalFirst = Math.abs(tx - sx) > Math.abs(ty - sy);
    const mx = horizontalFirst ? tx : sx;
    const my = horizontalFirst ? sy : ty;

    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", `${sx},${sy} ${mx},${my} ${tx},${ty}`);
    polyline.setAttribute("class", `annotation-line annotation-knight ${draft ? "draft" : ""}`);
    polyline.setAttribute("marker-end", "url(#ghostmate-arrow-head)");
    svg.appendChild(polyline);
    return;
  }

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", sx);
  line.setAttribute("y1", sy);
  line.setAttribute("x2", tx);
  line.setAttribute("y2", ty);
  line.setAttribute("class", `annotation-line ${draft ? "draft" : ""}`);
  line.setAttribute("marker-end", "url(#ghostmate-arrow-head)");
  svg.appendChild(line);
}

function renderAnnotations() {
  const board = el("chessboard");
  const svg = board?.querySelector(".annotation-layer");
  if (!svg) return;

  svg.querySelectorAll(".annotation-line").forEach((node) => node.remove());

  for (const annotation of state.annotations) {
    drawAnnotation(svg, annotation, false);
  }

  if (state.annotationDraft?.from && state.annotationDraft?.to) {
    drawAnnotation(svg, state.annotationDraft, true);
  }
}

function bindAnnotationHandlers() {
  const board = el("chessboard");
  if (!board || state.annotationBound) return;

  state.annotationBound = true;

  board.addEventListener("contextmenu", (event) => {
    event.preventDefault();
  });

  board.addEventListener("pointerdown", (event) => {
    if (event.button !== 2) return;

    const from = squareNameFromEvent(event);
    if (!from) return;

    event.preventDefault();

    state.annotationDraft = { from, to: from };
    board.setPointerCapture?.(event.pointerId);
    renderAnnotations();
  });

  board.addEventListener("pointermove", (event) => {
    if (!state.annotationDraft) return;

    const to = squareNameFromPoint(event.clientX, event.clientY);
    if (!to) return;

    state.annotationDraft.to = to;
    renderAnnotations();
  });

  board.addEventListener("pointerup", (event) => {
    if (!state.annotationDraft) return;

    event.preventDefault();

    const draft = state.annotationDraft;
    state.annotationDraft = null;

    if (isValidChessAnnotation(draft.from, draft.to)) {
      state.annotations.push(draft);
      addEvent("BOARD_ANNOTATION", draft);
    } else if (draft.from !== draft.to) {
      showToast("Only straight, diagonal, or knight L-shape annotations are allowed.");
    }

    renderAnnotations();
  });

  board.addEventListener("dblclick", () => {
    state.annotations = [];
    state.annotationDraft = null;
    renderAnnotations();
    showToast("Board annotations cleared.");
  });

  el("clear-selection")?.addEventListener("click", () => {
    state.annotations = [];
    state.annotationDraft = null;
    renderAnnotations();
  });
}

window.addEventListener("beforeunload", () => {
  state.shuttingDown = true;

  if (state.ws) {
    try {
      state.ws.onclose = null;
      state.ws.close(1000, "page unload");
    } catch (_) {}
  }
});

window.addEventListener("pagehide", () => {
  state.shuttingDown = true;
});

// === GhostMate tactical overlay patch END ===
'''

app += "\n" + patch + "\n"
app_path.write_text(app, encoding="utf-8")

css = css_path.read_text(encoding="utf-8")

css = re.sub(
    r'\n/\* === GhostMate tactical overlay and piece outline patch START ===[\s\S]*?/\* === GhostMate tactical overlay and piece outline patch END === \*/\n?',
    "\n",
    css,
)

css += r'''

/* === GhostMate tactical overlay and piece outline patch START === */

/* Stronger, readable chess-piece rendering */
.piece {
  opacity: 1 !important;
  line-height: 1 !important;
  font-weight: 900 !important;
  filter: drop-shadow(0 5px 10px rgba(0, 0, 0, 0.22));
}

.piece.white {
  color: #fffdf4 !important;
  -webkit-text-stroke: 1.45px rgba(5, 8, 16, 0.72) !important;
  text-shadow:
    0 1px 0 rgba(0, 0, 0, 0.60),
    0 8px 18px rgba(0, 0, 0, 0.28) !important;
}

.piece.black {
  color: #111522 !important;
  -webkit-text-stroke: 1.12px rgba(255, 255, 255, 0.46) !important;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.35),
    0 8px 16px rgba(0, 0, 0, 0.24) !important;
}

.square.light-square .piece.white,
.square.dark-square .piece.white {
  color: #fffefa !important;
}

.square.light-square .piece.black,
.square.dark-square .piece.black {
  color: #111522 !important;
}

/* Evaluation UI */
.eval-inline {
  display: inline-block;
  margin-top: 4px;
  color: #b9baff;
  font-weight: 850;
  letter-spacing: 0.01em;
}

#eval-detail-value {
  color: #ffffff;
}

/* Right-click chess annotation layer */
.chessboard {
  position: relative !important;
}

.annotation-layer {
  position: absolute;
  inset: 0;
  z-index: 15;
  pointer-events: none;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.annotation-line {
  fill: none;
  stroke: rgba(126, 181, 255, 0.92);
  stroke-width: 2.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 3px 6px rgba(0, 0, 0, 0.35));
}

.annotation-line.draft {
  stroke: rgba(255, 255, 255, 0.88);
  stroke-dasharray: 3 2;
}

.annotation-knight {
  stroke: rgba(185, 186, 255, 0.96);
}

.annotation-arrow-head {
  fill: rgba(126, 181, 255, 0.94);
}

.annotation-line.draft + .annotation-arrow-head {
  fill: rgba(255, 255, 255, 0.88);
}

/* Slightly improve contrast on the current board */
.square.light-square {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.18), transparent 50%),
    #f4f1ea !important;
}

.square.dark-square {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.12), transparent 50%),
    #aeb9c8 !important;
}

/* === GhostMate tactical overlay and piece outline patch END === */
'''

css_path.write_text(css, encoding="utf-8")
