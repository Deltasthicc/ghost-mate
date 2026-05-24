const app = {
  game: null,
  snapshot: null,
  selected: null,
  pendingMove: "",
  lastMove: null,
  flipped: false,
  events: [],
  ws: null,
};

const files = ["a", "b", "c", "d", "e", "f", "g", "h"];
const ranksWhite = ["8", "7", "6", "5", "4", "3", "2", "1"];
const pieceSymbols = {
  P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};

const $ = (selector) => document.querySelector(selector);

function setText(selector, value) {
  const el = $(selector);
  if (el) el.textContent = value;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

async function requestJson(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = { detail: "Response was not JSON" };
  }

  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : prettyJson(data);
    throw new Error(detail || `Request failed: ${res.status}`);
  }

  return data;
}

function fenToBoardMap(fen) {
  const boardPart = (fen || "").split(" ")[0];
  const rows = boardPart.split("/");
  const map = {};

  rows.forEach((row, rowIndex) => {
    let fileIndex = 0;
    const rank = String(8 - rowIndex);

    for (const char of row) {
      if (/\d/.test(char)) {
        fileIndex += Number(char);
      } else {
        const square = `${files[fileIndex]}${rank}`;
        map[square] = char;
        fileIndex += 1;
      }
    }
  });

  return map;
}

function getVisibleFiles() {
  return app.flipped ? [...files].reverse() : files;
}

function getVisibleRanks() {
  return app.flipped ? [...ranksWhite].reverse() : ranksWhite;
}

function isWhitePiece(piece) {
  return piece && piece === piece.toUpperCase();
}

function renderBoard() {
  const board = $("#chessboard");
  if (!board) return;

  const map = fenToBoardMap(app.game?.fen || "");
  const legalMoves = app.game?.legal_moves || [];
  const selectedTargets = new Set(
    app.selected
      ? legalMoves
          .filter((move) => move.slice(0, 2) === app.selected)
          .map((move) => move.slice(2, 4))
      : []
  );

  board.innerHTML = "";

  const visibleRanks = getVisibleRanks();
  const visibleFiles = getVisibleFiles();

  visibleRanks.forEach((rank, row) => {
    visibleFiles.forEach((file, col) => {
      const square = `${file}${rank}`;
      const piece = map[square];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `square ${(row + col) % 2 === 0 ? "light" : "dark"}`;
      btn.dataset.square = square;

      if (square === app.selected) btn.classList.add("selected");
      if (selectedTargets.has(square)) btn.classList.add("target");
      if (app.lastMove && (square === app.lastMove.from || square === app.lastMove.to)) {
        btn.classList.add("last-move");
      }

      if (piece) {
        const span = document.createElement("span");
        span.className = `piece ${isWhitePiece(piece) ? "white" : "black"}`;
        span.textContent = pieceSymbols[piece] || piece;
        btn.appendChild(span);
      }

      const coord = document.createElement("span");
      coord.className = "square-coord";
      coord.textContent = square;
      btn.appendChild(coord);

      btn.addEventListener("click", () => handleSquareClick(square, piece));
      board.appendChild(btn);
    });
  });

  setText("#selected-move", app.pendingMove || "Click a piece, then a target square");
}

async function handleSquareClick(square, piece) {
  const legalMoves = app.game?.legal_moves || [];

  if (!app.selected) {
    if (!piece) {
      showToast("Pick a piece first.");
      return;
    }

    app.selected = square;
    app.pendingMove = "";
    renderBoard();
    showToast(`Selected ${square}. Now choose a target square.`);
    return;
  }

  let uci = `${app.selected}${square}`;
  if (!legalMoves.includes(uci) && legalMoves.includes(`${uci}q`)) {
    uci = `${uci}q`;
  }

  app.pendingMove = uci;
  $("#uci").value = uci;

  if (legalMoves.includes(uci)) {
    await submitHumanMove(uci);
  } else {
    showToast(`${uci} is not legal in the current position.`);
    app.selected = null;
    renderBoard();
  }
}

function renderGame() {
  const game = app.game;
  if (!game) return;

  const legalCount = game.legal_moves?.length || 0;
  const status = game.is_game_over ? "Game Over" : game.is_check ? "Check" : "Active";
  const result = game.result || "No result yet";

  setText("#turn-value", game.turn || "--");
  setText("#turn-helper", game.turn === "white" ? "White to move" : "Black to move");
  setText("#legal-count", String(legalCount));
  setText("#game-status", status);
  setText("#game-result", result);
  setText("#robot-status", game.robot_busy ? "Busy" : "Ready");
  setText("#robot-helper", game.last_error || "No robot error reported");
  setText("#game-id", game.game_id || "--");
  setText("#check-state", game.is_check ? "Yes" : "No");
  setText("#fen-value", game.fen || "--");

  $("#state").textContent = prettyJson(game);
  renderBoard();
  renderLegalMoves();
}

function renderLegalMoves() {
  const box = $("#legal-moves");
  const filter = ($("#move-filter").value || "").trim().toLowerCase();
  const moves = (app.game?.legal_moves || []).filter((move) => move.toLowerCase().includes(filter));

  box.innerHTML = "";

  if (!moves.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "No matching legal moves.";
    box.appendChild(empty);
    return;
  }

  moves.forEach((move) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "move-chip";
    chip.textContent = move;
    if (move === app.pendingMove) chip.classList.add("active");
    chip.addEventListener("click", async () => {
      $("#uci").value = move;
      await submitHumanMove(move);
    });
    box.appendChild(chip);
  });
}

function renderSnapshot() {
  const grid = $("#sensor-grid");
  const snapshot = app.snapshot;
  grid.innerHTML = "";

  if (!snapshot?.cells) {
    setText("#occupied-count", "--");
    setText("#sensor-timestamp", "--");
    return;
  }

  const cells = snapshot.cells;
  const orderedSquares = [];

  ranksWhite.forEach((rank) => {
    files.forEach((file) => orderedSquares.push(`${file}${rank}`));
  });

  let occupied = 0;

  orderedSquares.forEach((square) => {
    const cell = cells[square] || { o: 0, p: 0, m: 0 };
    if (cell.o) occupied += 1;

    const div = document.createElement("div");
    const polarityClass = cell.p < 0 ? "white" : cell.p > 0 ? "black" : "";
    div.className = `sensor-cell ${cell.o ? "occupied" : ""} ${polarityClass}`;
    div.innerHTML = `<span>${square}</span><small>m:${cell.m ?? 0}</small>`;
    div.title = `${square} | occupied: ${cell.o} | polarity: ${cell.p} | magnitude: ${cell.m}`;
    grid.appendChild(div);
  });

  setText("#occupied-count", String(occupied));
  setText("#sensor-timestamp", String(snapshot.ts_ms || "--"));
}

function appendEvent(type, payload = {}) {
  const event = {
    type,
    payload,
    created_at: new Date().toISOString(),
  };

  app.events.unshift(event);
  app.events = app.events.slice(0, 40);
  renderEvents();
}

function renderEvents() {
  const feed = $("#events");
  feed.innerHTML = "";

  if (!app.events.length) {
    const empty = document.createElement("div");
    empty.className = "event-item";
    empty.innerHTML = "<strong>No events yet</strong><small>WebSocket and UI events will appear here.</small>";
    feed.appendChild(empty);
    return;
  }

  app.events.forEach((event) => {
    const item = document.createElement("div");
    item.className = "event-item";
    item.innerHTML = `
      <strong>${event.type}</strong>
      <small>${new Date(event.created_at).toLocaleTimeString()}</small>
      <code>${JSON.stringify(event.payload)}</code>
    `;
    feed.appendChild(item);
  });
}

async function refreshState() {
  try {
    app.game = await requestJson("/api/state");
    setText("#host-status", "Online");
    renderGame();
  } catch (err) {
    setText("#host-status", "Offline");
    showToast(err.message);
  }
}

async function refreshSnapshot() {
  try {
    app.snapshot = await requestJson("/api/board/snapshot");
    renderSnapshot();
  } catch (err) {
    showToast(err.message);
  }
}

async function healthCheck() {
  try {
    await requestJson("/api/health");
    setText("#host-status", "Online");
  } catch {
    setText("#host-status", "Offline");
  }
}

async function submitHumanMove(uci) {
  const move = (uci || $("#uci").value || "").trim();

  if (!move) {
    showToast("Enter a move first.");
    return;
  }

  try {
    const nextState = await requestJson("/api/move/human", {
      method: "POST",
      body: JSON.stringify({ uci: move }),
    });

    app.lastMove = { from: move.slice(0, 2), to: move.slice(2, 4) };
    app.selected = null;
    app.pendingMove = "";
    app.game = nextState;
    $("#uci").value = "";
    appendEvent("HUMAN_MOVE_APPLIED", { uci: move });
    renderGame();
    showToast(`Move applied: ${move}`);
  } catch (err) {
    showToast(err.message);
    appendEvent("MOVE_REJECTED", { uci: move, error: err.message });
  }
}

async function runHardwareCommand(path, shouldRefreshSnapshot = false) {
  try {
    const response = await requestJson(path, { method: "POST" });
    $("#hardware-log").textContent = prettyJson(response);
    appendEvent("HARDWARE_COMMAND", { path, response });

    if (shouldRefreshSnapshot) {
      window.setTimeout(refreshSnapshot, 120);
    }

    showToast(`Hardware command OK: ${path.split("/").at(-1)}`);
  } catch (err) {
    $("#hardware-log").textContent = err.message;
    appendEvent("HARDWARE_ERROR", { path, error: err.message });
    showToast(err.message);
  }
}

async function sendRobotMove() {
  const source = ($("#robot-source").value || "").trim();
  const target = ($("#robot-target").value || "").trim();
  const capture = $("#robot-capture").checked;

  if (!/^[a-h][1-8]$/.test(source) || !/^[a-h][1-8]$/.test(target)) {
    showToast("Robot source and target must look like g1 and f3.");
    return;
  }

  try {
    const response = await requestJson("/api/move/robot", {
      method: "POST",
      body: JSON.stringify({ source, target, capture }),
    });

    $("#hardware-log").textContent = prettyJson(response);
    appendEvent("ROBOT_MOVE_SENT", { source, target, capture, response });
    showToast(`Robot mock move sent: ${source} → ${target}`);
  } catch (err) {
    $("#hardware-log").textContent = err.message;
    appendEvent("ROBOT_MOVE_ERROR", { source, target, error: err.message });
    showToast(err.message);
  }
}

function connectWebSocket() {
  const status = $("#connection-status");
  const protocol = location.protocol === "https:" ? "wss" : "ws";

  if (app.ws) {
    app.ws.close();
  }

  app.ws = new WebSocket(`${protocol}://${location.host}/ws`);

  app.ws.onopen = () => {
    status.classList.remove("offline");
    status.innerHTML = '<span class="pulse"></span> Live';
    setText("#ws-status", "Live");
    appendEvent("WS_CONNECTED", { url: "/ws" });
  };

  app.ws.onclose = () => {
    status.classList.add("offline");
    status.innerHTML = '<span class="pulse"></span> Reconnecting';
    setText("#ws-status", "Reconnecting");
    window.setTimeout(connectWebSocket, 1400);
  };

  app.ws.onerror = () => {
    status.classList.add("offline");
    setText("#ws-status", "Error");
  };

  app.ws.onmessage = async (message) => {
    try {
      const event = JSON.parse(message.data);
      appendEvent(event.type || "WS_EVENT", event.payload || event);

      if (event.type === "HELLO" && event.state) {
        app.game = event.state;
        renderGame();
      }

      if (
        event.type === "STATE_CHANGED" ||
        event.type === "LOCAL_MOVE_CANDIDATE" ||
        event.type === "SCAN_RECEIVED" ||
        event.type === "ROBOT_MOVE_COMPLETE"
      ) {
        await refreshState();
      }

      if (event.type === "SCAN_RECEIVED") {
        await refreshSnapshot();
      }
    } catch (err) {
      appendEvent("WS_PARSE_ERROR", { error: err.message });
    }
  };
}

function updateClock() {
  setText("#clock", new Date().toLocaleTimeString());
}

function bindEvents() {
  $("#new-game").addEventListener("click", async () => {
    try {
      app.game = await requestJson("/api/game/new", { method: "POST" });
      app.selected = null;
      app.pendingMove = "";
      app.lastMove = null;
      appendEvent("NEW_GAME", { game_id: app.game.game_id });
      renderGame();
      showToast("New game started.");
    } catch (err) {
      showToast(err.message);
    }
  });

  $("#refresh-all").addEventListener("click", async () => {
    await healthCheck();
    await refreshState();
    await refreshSnapshot();
    showToast("Dashboard refreshed.");
  });

  $("#scan-board-hero").addEventListener("click", () => runHardwareCommand("/api/hardware/scan", true));
  $("#refresh-snapshot").addEventListener("click", refreshSnapshot);
  $("#send-move").addEventListener("click", () => submitHumanMove());
  $("#submit-selected").addEventListener("click", () => submitHumanMove(app.pendingMove));
  $("#send-robot-move").addEventListener("click", sendRobotMove);

  $("#uci").addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitHumanMove();
  });

  $("#move-filter").addEventListener("input", renderLegalMoves);

  $("#flip-board").addEventListener("click", () => {
    app.flipped = !app.flipped;
    renderBoard();
  });

  $("#clear-selection").addEventListener("click", () => {
    app.selected = null;
    app.pendingMove = "";
    $("#uci").value = "";
    renderBoard();
  });

  $("#clear-events").addEventListener("click", () => {
    app.events = [];
    renderEvents();
  });

  $("#toggle-raw").addEventListener("click", () => {
    $("#state").classList.toggle("hidden");
  });

  $("#theme-toggle").addEventListener("click", () => {
    document.body.classList.toggle("dark");
    localStorage.setItem("ghost-mate-theme", document.body.classList.contains("dark") ? "dark" : "light");
  });

  document.querySelectorAll("[data-hardware]").forEach((btn) => {
    btn.addEventListener("click", () => {
      runHardwareCommand(btn.dataset.hardware, btn.dataset.scan === "true");
    });
  });

  document.querySelectorAll("[data-quick-move]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const move = btn.dataset.quickMove;
      $("#uci").value = move;
      submitHumanMove(move);
    });
  });
}

async function boot() {
  if (localStorage.getItem("ghost-mate-theme") === "dark") {
    document.body.classList.add("dark");
  }

  bindEvents();
  renderEvents();
  renderBoard();
  renderSnapshot();
  updateClock();
  window.setInterval(updateClock, 1000);

  await healthCheck();
  await refreshState();
  await refreshSnapshot();
  connectWebSocket();
}

boot();

/* =========================================================
   Axis-label polish patch
   Makes file/rank labels follow Flip correctly
   ========================================================= */

function renderAxisLabels() {
  const rankBox = document.querySelector(".rank-labels");
  const fileBox = document.querySelector(".file-labels");

  if (rankBox) {
    rankBox.innerHTML = getVisibleRanks().map((rank) => `<span>${rank}</span>`).join("");
  }

  if (fileBox) {
    fileBox.innerHTML = getVisibleFiles().map((file) => `<span>${file}</span>`).join("");
  }
}

const originalRenderBoardWithAxisLabels = renderBoard;

renderBoard = function patchedRenderBoard() {
  renderAxisLabels();
  originalRenderBoardWithAxisLabels();
};

renderBoard();
