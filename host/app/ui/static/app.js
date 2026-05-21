const state = {
  game: null,
  snapshot: null,
  selected: null,
  pendingMove: "",
  lastMove: null,
  flipped: false,
  ws: null,
  shuttingDown: false,
  events: [],
};

const files = ["a", "b", "c", "d", "e", "f", "g", "h"];
const ranks = ["8", "7", "6", "5", "4", "3", "2", "1"];
const pieces = {
  P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};

function el(id) {
  return document.getElementById(id);
}

function q(selector) {
  return document.querySelector(selector);
}

function setText(idOrSelector, value) {
  const node = idOrSelector.startsWith("#") ? q(idOrSelector) : el(idOrSelector);
  if (node) node.textContent = value;
}

function showToast(message) {
  const node = el("toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => node.classList.remove("show"), 2500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = { detail: "Server returned non-JSON response" };
  }

  if (!response.ok) {
    const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data);
    throw new Error(msg || `Request failed: ${response.status}`);
  }

  return data;
}

function visibleFiles() {
  return state.flipped ? [...files].reverse() : files;
}

function visibleRanks() {
  return state.flipped ? [...ranks].reverse() : ranks;
}

function fenToMap(fen) {
  const map = {};
  const boardFen = String(fen || "").split(" ")[0];
  const rows = boardFen.split("/");

  rows.forEach((row, rowIndex) => {
    let fileIndex = 0;
    const rank = String(8 - rowIndex);

    for (const char of row) {
      if (/\d/.test(char)) {
        fileIndex += Number(char);
      } else {
        map[`${files[fileIndex]}${rank}`] = char;
        fileIndex += 1;
      }
    }
  });

  return map;
}

function renderAxisLabels() {
  const rankBox = el("rank-labels");
  const fileBox = el("file-labels");

  if (rankBox) {
    rankBox.innerHTML = visibleRanks().map((rank) => `<span>${rank}</span>`).join("");
  }

  if (fileBox) {
    fileBox.innerHTML = visibleFiles().map((file) => `<span>${file}</span>`).join("");
  }
}

function renderBoard() {
  renderAxisLabels();

  const board = el("chessboard");
  if (!board) return;

  const pieceMap = fenToMap(state.game?.fen || "");
  const legalMoves = state.game?.legal_moves || [];
  const targetSquares = new Set(
    state.selected
      ? legalMoves.filter((m) => m.slice(0, 2) === state.selected).map((m) => m.slice(2, 4))
      : []
  );

  board.innerHTML = "";

  visibleRanks().forEach((rank, row) => {
    visibleFiles().forEach((file, col) => {
      const square = `${file}${rank}`;
      const piece = pieceMap[square];

      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.square = square;
      btn.className = `square ${(row + col) % 2 ? "dark-square" : "light-square"}`;

      if (square === state.selected) btn.classList.add("selected");
      if (targetSquares.has(square)) btn.classList.add("target");
      if (state.lastMove && (square === state.lastMove.from || square === state.lastMove.to)) {
        btn.classList.add("last-move");
      }

      if (piece) {
        const pieceNode = document.createElement("span");
        pieceNode.className = `piece ${piece === piece.toUpperCase() ? "white" : "black"}`;
        pieceNode.textContent = pieces[piece] || piece;
        btn.appendChild(pieceNode);
      }

      const coord = document.createElement("span");
      coord.className = "coord";
      coord.textContent = square;
      btn.appendChild(coord);

      btn.addEventListener("click", () => handleSquareClick(square, piece));
      board.appendChild(btn);
    });
  });

  setText("selected-move", state.pendingMove || "Click a piece, then a target square");
}

async function handleSquareClick(square, piece) {
  if (!state.game) {
    showToast("Game state is still loading.");
    return;
  }

  if (!state.selected) {
    if (!piece) {
      showToast("Choose a piece first.");
      return;
    }

    state.selected = square;
    state.pendingMove = "";
    renderBoard();
    showToast(`Selected ${square}. Now choose a target square.`);
    return;
  }

  let move = `${state.selected}${square}`;
  if (!state.game.legal_moves.includes(move) && state.game.legal_moves.includes(`${move}q`)) {
    move = `${move}q`;
  }

  state.pendingMove = move;
  const input = el("uci");
  if (input) input.value = move;

  if (!state.game.legal_moves.includes(move)) {
    showToast(`${move} is not legal here.`);
    state.selected = null;
    state.pendingMove = "";
    renderBoard();
    return;
  }

  await sendHumanMove(move);
}

function renderGame() {
  if (!state.game) return;

  const game = state.game;

  setText("turn-value", game.turn || "--");
  setText("turn-helper", game.turn === "white" ? "White to move" : "Black to move");
  setText("legal-count", String(game.legal_moves?.length || 0));
  setText("game-status", game.is_game_over ? "Game Over" : game.is_check ? "Check" : "Active");
  setText("game-result", game.result || "No result yet");
  setText("robot-status", game.robot_busy ? "Busy" : "Ready");
  setText("robot-helper", game.last_error || "No robot error reported");
  setText("game-id", game.game_id || "--");
  setText("check-state", game.is_check ? "Yes" : "No");
  setText("fen-value", game.fen || "--");

  const raw = el("state");
  if (raw) raw.textContent = JSON.stringify(game, null, 2);

  renderBoard();
  renderLegalMoves();
}

function renderLegalMoves() {
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

function renderSnapshot() {
  const grid = el("sensor-grid");
  if (!grid) return;

  const snapshot = state.snapshot;
  grid.innerHTML = "";

  if (!snapshot?.cells) {
    setText("occupied-count", "--");
    setText("sensor-timestamp", "--");
    return;
  }

  let occupied = 0;

  ranks.forEach((rank) => {
    files.forEach((file) => {
      const square = `${file}${rank}`;
      const cell = snapshot.cells[square] || { o: 0, p: 0, m: 0 };
      if (cell.o) occupied += 1;

      const node = document.createElement("div");
      const polarity = cell.p < 0 ? "white" : cell.p > 0 ? "black" : "";
      node.className = `sensor-cell ${cell.o ? "occupied" : ""} ${polarity}`;
      node.innerHTML = `<span>${square}</span><small>m:${cell.m ?? 0}</small>`;
      grid.appendChild(node);
    });
  });

  setText("occupied-count", String(occupied));
  setText("sensor-timestamp", String(snapshot.ts_ms || "--"));
}

function addEvent(type, payload = {}) {
  state.events.unshift({ type, payload, time: new Date().toLocaleTimeString() });
  state.events = state.events.slice(0, 40);
  renderEvents();
}

function renderEvents() {
  const feed = el("events");
  if (!feed) return;

  feed.innerHTML = "";

  if (!state.events.length) {
    feed.innerHTML = `<div class="event"><strong>No events yet</strong><small>Live events will appear here.</small></div>`;
    return;
  }

  state.events.forEach((event) => {
    const node = document.createElement("div");
    node.className = "event";
    node.innerHTML = `<strong>${event.type}</strong><small>${event.time}</small><code>${JSON.stringify(event.payload)}</code>`;
    feed.appendChild(node);
  });
}

async function refreshState() {
  state.game = await api("/api/state");
  setText("host-status", "Online");
  renderGame();
}

async function refreshSnapshot() {
  state.snapshot = await api("/api/board/snapshot");
  renderSnapshot();
}

async function sendHumanMove(rawMove) {
  const move = String(rawMove || el("uci")?.value || "").trim();
  if (!move) {
    showToast("Enter a move first.");
    return;
  }

  try {
    state.game = await api("/api/move/human", {
      method: "POST",
      body: JSON.stringify({ uci: move }),
    });

    state.lastMove = { from: move.slice(0, 2), to: move.slice(2, 4) };
    state.selected = null;
    state.pendingMove = "";

    const input = el("uci");
    if (input) input.value = "";

    renderGame();
    addEvent("HUMAN_MOVE_APPLIED", { uci: move });
    showToast(`Move applied: ${move}`);
  } catch (err) {
    addEvent("MOVE_REJECTED", { move, error: err.message });
    showToast(err.message);
  }
}

async function hardwareCommand(path, scanAfter = false) {
  try {
    const response = await api(path, { method: "POST" });
    const log = el("hardware-log");
    if (log) log.textContent = JSON.stringify(response, null, 2);

    addEvent("HARDWARE_COMMAND", { path, response });

    if (scanAfter) {
      setTimeout(refreshSnapshot, 150);
    }

    showToast(`Hardware OK: ${path.split("/").pop()}`);
  } catch (err) {
    const log = el("hardware-log");
    if (log) log.textContent = err.message;
    addEvent("HARDWARE_ERROR", { path, error: err.message });
    showToast(err.message);
  }
}

async function sendRobotMove() {
  const source = (el("robot-source")?.value || "").trim();
  const target = (el("robot-target")?.value || "").trim();
  const capture = Boolean(el("robot-capture")?.checked);

  if (!/^[a-h][1-8]$/.test(source) || !/^[a-h][1-8]$/.test(target)) {
    showToast("Use valid squares like g1 and f3.");
    return;
  }

  try {
    const response = await api("/api/move/robot", {
      method: "POST",
      body: JSON.stringify({ source, target, capture }),
    });

    const log = el("hardware-log");
    if (log) log.textContent = JSON.stringify(response, null, 2);

    addEvent("ROBOT_MOVE_SENT", { source, target, capture, response });
    showToast(`Robot command sent: ${source} → ${target}`);
  } catch (err) {
    showToast(err.message);
  }
}

function connectWebSocket() {
  const pill = el("connection-status");
  const protocol = location.protocol === "https:" ? "wss" : "ws";

  state.ws = new WebSocket(`${protocol}://${location.host}/ws`);

  state.ws.onopen = () => {
    if (pill) {
      pill.classList.remove("offline");
      pill.innerHTML = "<i></i> Live";
    }
    setText("ws-status", "Live");
    addEvent("WS_CONNECTED", { url: "/ws" });
  };

  state.ws.onclose = () => {
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

  state.ws.onerror = () => {
    if (pill) pill.classList.add("offline");
    setText("ws-status", "Error");
  };

  state.ws.onmessage = async (message) => {
    try {
      const data = JSON.parse(message.data);
      addEvent(data.type || "WS_EVENT", data.payload || data);

      if (data.type === "HELLO" && data.state) {
        state.game = data.state;
        renderGame();
      }

      if (["STATE_CHANGED", "LOCAL_MOVE_CANDIDATE", "SCAN_RECEIVED", "ROBOT_MOVE_COMPLETE"].includes(data.type)) {
        await refreshState();
      }

      if (data.type === "SCAN_RECEIVED") {
        await refreshSnapshot();
      }
    } catch (err) {
      addEvent("WS_PARSE_ERROR", { error: err.message });
    }
  };
}

function bindEvents() {
  el("new-game")?.addEventListener("click", async () => {
    try {
      state.game = await api("/api/game/new", { method: "POST" });
      state.selected = null;
      state.pendingMove = "";
      state.lastMove = null;
      renderGame();
      addEvent("NEW_GAME", { game_id: state.game.game_id });
      showToast("New game started.");
    } catch (err) {
      showToast(err.message);
    }
  });

  el("refresh-all")?.addEventListener("click", async () => {
    await refreshState();
    await refreshSnapshot();
    showToast("Dashboard refreshed.");
  });

  el("scan-board-hero")?.addEventListener("click", () => hardwareCommand("/api/hardware/scan", true));
  el("refresh-snapshot")?.addEventListener("click", refreshSnapshot);
  el("send-move")?.addEventListener("click", () => sendHumanMove());
  el("submit-selected")?.addEventListener("click", () => sendHumanMove(state.pendingMove));
  el("send-robot-move")?.addEventListener("click", sendRobotMove);

  el("uci")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendHumanMove();
  });

  el("move-filter")?.addEventListener("input", renderLegalMoves);

  el("flip-board")?.addEventListener("click", () => {
    state.flipped = !state.flipped;
    renderBoard();
  });

  el("clear-selection")?.addEventListener("click", () => {
    state.selected = null;
    state.pendingMove = "";
    if (el("uci")) el("uci").value = "";
    renderBoard();
  });

  el("clear-events")?.addEventListener("click", () => {
    state.events = [];
    renderEvents();
  });

  el("toggle-raw")?.addEventListener("click", () => {
    el("state")?.classList.toggle("hidden");
  });

  el("theme-toggle")?.addEventListener("click", () => {
    document.body.classList.toggle("dark");
    localStorage.setItem("ghostmate-theme", document.body.classList.contains("dark") ? "dark" : "light");
  });

  document.querySelectorAll("[data-hardware]").forEach((button) => {
    button.addEventListener("click", () => hardwareCommand(button.dataset.hardware, button.dataset.scan === "true"));
  });

  document.querySelectorAll("[data-quick-move]").forEach((button) => {
    button.addEventListener("click", () => sendHumanMove(button.dataset.quickMove));
  });
}

function tickClock() {
  setText("clock", new Date().toLocaleTimeString());
}

async function boot() {
  try {
    if (localStorage.getItem("ghostmate-theme") === "dark") {
      document.body.classList.add("dark");
    }

    bindEvents();
    renderAxisLabels();
    renderBoard();
    renderEvents();
    renderSnapshot();

    tickClock();
    setInterval(tickClock, 1000);

    await api("/api/health");
    setText("host-status", "Online");

    await refreshState();
    await refreshSnapshot();

    connectWebSocket();
  } catch (err) {
    console.error("UI boot failed:", err);
    showToast(`UI boot error: ${err.message}`);
  }
}

window.addEventListener("DOMContentLoaded", boot);

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
      <marker
        id="ghostmate-arrow-head"
        markerWidth="3.8"
        markerHeight="3.8"
        refX="3.25"
        refY="1.9"
        orient="auto"
        markerUnits="strokeWidth"
      >
        <path d="M0,0 L0,3.8 L3.8,1.9 z" class="annotation-arrow-head"></path>
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

