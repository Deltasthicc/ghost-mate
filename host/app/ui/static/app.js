/* GhostMate UI — optimized.
 *
 * Design principles:
 * - The WebSocket is the source of truth. We never poll /api/state after
 *   receiving an event; the server pushes the new state in the event payload.
 * - The 8x8 board is built once at boot. Subsequent renders mutate the same
 *   DOM nodes (text content + classes) instead of recreating buttons.
 * - One click delegate per surface. No 64 listeners.
 * - Stockfish analysis is debounced + tied to actual position changes. No
 *   3-second polling loop. Server pushes ENGINE_UPDATE when relevant.
 * - All re-renders coalesce into a single requestAnimationFrame.
 *
 * IMPORTANT: tests assert that the literal strings "DOMContentLoaded" and
 * "UI boot failed" exist in this file. Do not remove them.
 */
(() => {
  "use strict";

  const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
  const RANKS = ["8", "7", "6", "5", "4", "3", "2", "1"];
  const PIECE_GLYPHS = {
    P: "\u2659", N: "\u2658", B: "\u2657", R: "\u2656", Q: "\u2655", K: "\u2654",
    p: "\u265F", n: "\u265E", b: "\u265D", r: "\u265C", q: "\u265B", k: "\u265A",
  };

  const state = {
    game: null,
    snapshot: null,
    selected: null,
    pendingMove: "",
    lastMove: null,
    flipped: false,
    ws: null,
    wsBackoff: 250,
    shuttingDown: false,
    events: [],
    engine: null,
    engineLoading: false,
    engineError: null,
    engineReqId: 0,
    enginePosKey: null,
    engineMaxDepth: 15,
    annotations: [],
    annotationDraft: null,
    rendering: false,
    boardBuilt: false,
    showRaw: false,
    pgn: "",
  };

  // ----------------------------------------------------------------- helpers

  const el = (id) => document.getElementById(id);
  const q = (sel) => document.querySelector(sel);

  function setText(target, value) {
    const node = typeof target === "string"
      ? (target.startsWith("#") ? q(target) : el(target))
      : target;
    if (node && node.textContent !== value) node.textContent = value;
  }

  let toastTimer = null;
  function showToast(message) {
    const node = el("toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("show"), 2500);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let data = null;
    try { data = await response.json(); }
    catch { data = { detail: "Server returned non-JSON response" }; }
    if (!response.ok) {
      const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data);
      throw new Error(msg || `Request failed: ${response.status}`);
    }
    return data;
  }

  // ----------------------------------------------------------------- board

  function visibleFiles() { return state.flipped ? [...FILES].reverse() : FILES; }
  function visibleRanks() { return state.flipped ? [...RANKS].reverse() : RANKS; }

  function fenToMap(fen) {
    const map = Object.create(null);
    const boardFen = String(fen || "").split(" ")[0];
    const rows = boardFen.split("/");
    for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
      const row = rows[rowIndex];
      const rank = String(8 - rowIndex);
      let fileIndex = 0;
      for (let i = 0; i < row.length; i++) {
        const ch = row[i];
        const n = ch.charCodeAt(0);
        if (n >= 48 && n <= 57) fileIndex += (n - 48);
        else { map[FILES[fileIndex] + rank] = ch; fileIndex += 1; }
      }
    }
    return map;
  }

  function buildBoardOnce() {
    if (state.boardBuilt) return;
    const board = el("chessboard");
    if (!board) return;

    board.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "square";
        const pieceNode = document.createElement("span");
        pieceNode.className = "piece";
        btn.appendChild(pieceNode);
        const coordNode = document.createElement("span");
        coordNode.className = "coord";
        btn.appendChild(coordNode);
        frag.appendChild(btn);
      }
    }
    board.appendChild(frag);

    // Single delegated click listener.
    board.addEventListener("click", (event) => {
      const sq = event.target.closest(".square");
      if (!sq) return;
      const square = sq.dataset.square;
      if (!square) return;
      const piece = sq.dataset.piece || null;
      handleSquareClick(square, piece);
    });

    state.boardBuilt = true;
  }

  function renderAxisLabels() {
    const rankBox = el("rank-labels");
    const fileBox = el("file-labels");
    if (rankBox) {
      const ranks = visibleRanks();
      rankBox.innerHTML = ranks.map(r => `<span>${r}</span>`).join("");
    }
    if (fileBox) {
      const files = visibleFiles();
      fileBox.innerHTML = files.map(f => `<span>${f}</span>`).join("");
    }
  }

  function renderBoard() {
    buildBoardOnce();
    renderAxisLabels();

    const board = el("chessboard");
    if (!board) return;

    const pieceMap = fenToMap(state.game?.fen || "");
    const legalMoves = state.game?.legal_moves || [];

    let targets = null;
    if (state.selected) {
      targets = new Set();
      const sel = state.selected;
      for (let i = 0; i < legalMoves.length; i++) {
        const m = legalMoves[i];
        if (m.charCodeAt(0) === sel.charCodeAt(0) && m.charCodeAt(1) === sel.charCodeAt(1)) {
          targets.add(m.slice(2, 4));
        }
      }
    }

    const lastFrom = state.lastMove?.from;
    const lastTo = state.lastMove?.to;
    const ranks = visibleRanks();
    const files = visibleFiles();

    const squares = board.children;
    let idx = 0;
    for (let row = 0; row < 8; row++) {
      const rank = ranks[row];
      for (let col = 0; col < 8; col++) {
        const file = files[col];
        const square = file + rank;
        const btn = squares[idx++];
        const piece = pieceMap[square];

        const baseClass = (row + col) % 2 ? "dark-square" : "light-square";
        let className = "square " + baseClass;
        if (square === state.selected) className += " selected";
        if (targets && targets.has(square)) className += " target";
        if (square === lastFrom || square === lastTo) className += " last-move";
        if (btn.className !== className) btn.className = className;

        if (btn.dataset.square !== square) btn.dataset.square = square;

        const pieceNode = btn.firstChild;
        const coordNode = btn.lastChild;

        if (piece) {
          const glyph = PIECE_GLYPHS[piece] || piece;
          if (pieceNode.textContent !== glyph) pieceNode.textContent = glyph;
          const isWhite = piece === piece.toUpperCase();
          const pieceClass = "piece " + (isWhite ? "white" : "black");
          if (pieceNode.className !== pieceClass) pieceNode.className = pieceClass;
          if (btn.dataset.piece !== piece) btn.dataset.piece = piece;
        } else {
          if (pieceNode.textContent !== "") pieceNode.textContent = "";
          if (pieceNode.className !== "piece") pieceNode.className = "piece";
          if (btn.dataset.piece) delete btn.dataset.piece;
        }

        if (coordNode.textContent !== square) coordNode.textContent = square;
      }
    }

    setText("selected-move", state.pendingMove || "Click a piece, then a target square");
    renderAnnotations();
  }

  // ----------------------------------------------------------------- input

  async function handleSquareClick(square, piece) {
    if (!state.game) { showToast("Game state is still loading."); return; }
    if (!state.selected) {
      if (!piece) { showToast("Choose a piece first."); return; }
      state.selected = square;
      state.pendingMove = "";
      scheduleRender();
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
      state.selected = null; state.pendingMove = "";
      scheduleRender();
      return;
    }
    await sendHumanMove(move);
  }

  // ----------------------------------------------------------------- render

  function scheduleRender() {
    if (state.rendering) return;
    state.rendering = true;
    requestAnimationFrame(() => {
      state.rendering = false;
      renderGame();
    });
  }

  function renderGame() {
    if (!state.game) return;
    const g = state.game;

    setText("turn-value", g.turn || "--");
    setText("turn-helper", g.turn === "white" ? "White to move" : "Black to move");
    setText("legal-count", String(g.legal_moves?.length || 0));
    setText("game-status", g.is_game_over ? "Game Over" : g.is_check ? "Check" : "Active");
    setText("game-result", g.result || "No result yet");
    setText("robot-status", g.robot_busy ? "Busy" : "Ready");
    setText("robot-helper", g.last_error || "No robot error reported");
    setText("game-id", g.game_id || "--");
    setText("check-state", g.is_check ? "Yes" : "No");
    setText("fen-value", g.fen || "--");

    if (state.showRaw) {
      const raw = el("state");
      if (raw) raw.textContent = JSON.stringify(g, null, 2);
    }

    renderEvaluationUI();
    renderBoard();
    renderEnginePanel();
    renderMoveHistory();
    renderCopyFields();
    queuePgnRefresh();
  }

  let pgnRefreshTimer = null;
  function queuePgnRefresh(delay = 160) {
    clearTimeout(pgnRefreshTimer);
    pgnRefreshTimer = setTimeout(() => { refreshPgn().catch(() => {}); }, delay);
  }

  function renderEvaluationUI() {
    const evaluation = state.game?.evaluation;
    const display = evaluation?.display || "0.00";
    const source = evaluation?.source || "material";
    const mateText = (evaluation?.mate_in === null || evaluation?.mate_in === undefined)
      ? "Mate: \u2014"
      : `Mate: ${evaluation.mate_in}`;

    const statusSmall = el("game-result");
    if (statusSmall) {
      const resultText = state.game?.result || "No result yet";
      statusSmall.innerHTML = `${resultText}<br><span class="eval-inline">Eval ${display} \u00B7 ${mateText}</span>`;
    }
    const details = q(".details-list");
    if (details && !el("eval-detail-row")) {
      const row = document.createElement("div");
      row.id = "eval-detail-row";
      row.innerHTML = `<span>Evaluation</span><strong id="eval-detail-value">--</strong>`;
      details.appendChild(row);
    }
    const evalDetail = el("eval-detail-value");
    if (evalDetail) {
      evalDetail.textContent = `${display} \u00B7 ${source}`;
      evalDetail.title = evaluation?.note || "Positive means White is better. Negative means Black is better.";
    }
  }

  // ----------------------------------------------------------------- engine UI

  function ensureEngineUI() {
    const list = el("legal-moves");
    if (!list) return;
    let summary = el("engine-summary");
    if (!summary) {
      summary = document.createElement("div");
      summary.id = "engine-summary";
      summary.className = "engine-summary";
      summary.textContent = "Stockfish analysis loading...";
      list.parentNode.insertBefore(summary, list);
    }
    if (!el("engine-controls")) {
      const controls = document.createElement("div");
      controls.id = "engine-controls";
      controls.className = "engine-controls";
      controls.innerHTML = `
        <label>
          Max depth
          <input id="engine-depth-limit" type="number" min="1" max="15" step="1" value="15" />
        </label>
        <small>Depth is capped at 15 for this project.</small>
      `;
      summary.parentNode.insertBefore(controls, summary.nextSibling);
      el("engine-depth-limit")?.addEventListener("change", handleEngineDepthChange);
    }
    list.classList.add("engine-move-list");

  }

  function renderEnginePanel() {
    ensureEngineUI();
    const summary = el("engine-summary");
    const box = el("legal-moves");
    if (!box) return;

    const filter = (el("move-filter")?.value || "").trim().toLowerCase();
    const analysis = state.engine;

    if (summary) {
      if (state.engineLoading && !analysis) {
        summary.textContent = "Stockfish is analyzing...";
      } else if (state.engineError) {
        summary.textContent = `Stockfish error: ${state.engineError}`;
      } else if (analysis) {
        const evalText = analysis.current_display || analysis.current_display_white || "\u2014";
        const mate = analysis.mate_display || "Mate: \u2014";
        const depth = analysis.depth ?? analysis.depth_requested ?? "?";
        const maxDepth = analysis.max_depth ?? state.engineMaxDepth;
        const elapsed = formatMs(analysis.elapsed_ms);
        const total = formatMs(analysis.search_elapsed_ms);
        const mode = analysis.is_final_depth ? "target reached" : "analyzing";
        summary.innerHTML = `
          <strong>Position:</strong> ${evalText}
          <span class="muted">(White POV)</span> \u00B7
          <strong>${analysis.turn} to move \u00B7 ${mate}</strong> \u00B7
          depth ${depth}/${maxDepth} \u00B7 ${elapsed} this depth \u00B7 ${total} total
          <span class="engine-live-badge">${mode}</span>
        `;
      } else {
        summary.textContent = "No engine analysis yet.";
      }
    }

    // Rebuild move cards only if the result set changed.
    box.innerHTML = "";
    if (state.engineLoading && !analysis) {
      box.innerHTML = `<span class="hint">Analyzing...</span>`; return;
    }
    if (state.engineError) {
      box.innerHTML = `<span class="hint">${state.engineError}</span>`; return;
    }
    const moves = (analysis?.best_moves || []).filter((m) => {
      if (!filter) return true;
      const hay = `${m.uci} ${m.san} ${(m.pv || []).join(" ")}`.toLowerCase();
      return hay.includes(filter);
    });
    if (!moves.length) {
      box.innerHTML = `<span class="hint">No Stockfish suggestions for this position.</span>`;
      return;
    }
    const frag = document.createDocumentFragment();
    for (const move of moves) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "engine-move-card";
      const score = move.score_display || move.score_display_white || "\u2014";
      const mate = (move.mate_display && move.mate_display !== "\u2014") ? ` \u00B7 ${move.mate_display}` : "";
      card.innerHTML = `
        <span class="engine-rank">#${move.rank}</span>
        <span class="engine-main"><strong>${move.san}</strong><code>${move.uci}</code></span>
        <span class="engine-score">${score}${mate}</span>
        <small>PV: ${(move.pv || []).join(" ") || "\u2014"}</small>
      `;
      card.title = "Click to play this Stockfish suggested move";
      card.addEventListener("click", () => sendHumanMove(move.uci));
      frag.appendChild(card);
    }
    box.appendChild(frag);
  }

  async function refreshEngine() {
    if (!state.game?.fen) return;
    const posKey = state.game.fen.split(" ").slice(0, 4).join(" ");
    if (state.engineLoading && state.enginePosKey === posKey) return;
    state.enginePosKey = posKey;
    const reqId = ++state.engineReqId;
    state.engineLoading = true;
    state.engineError = null;
    renderEnginePanel();
    try {
      const analysis = await api(`/api/engine/live?multipv=5&max_depth=${state.engineMaxDepth}`);
      if (reqId !== state.engineReqId) return;
      state.engineLoading = false;
      state.engineError = null;
      applyEngineAnalysis(analysis);
    } catch (err) {
      if (reqId !== state.engineReqId) return;
      state.engineLoading = false;
      state.engineError = err.message || String(err);
      renderEnginePanel();
    }
  }

  function applyEngineAnalysis(analysis) {
    if (!analysis) return;
    state.engine = analysis;
    state.engineError = null;
    const scoreCp = analysis.current_score_cp ?? analysis.current_score_cp_white ?? null;
    if (state.game) {
      state.game.evaluation = {
        display: analysis.current_display || analysis.current_display_white || "--",
        score_cp: scoreCp,
        score_pawns: scoreCp == null ? null : scoreCp / 100,
        mate_in: analysis.mate_in,
        source: analysis.cache_hit ? "stockfish cached" : "stockfish live",
        note: analysis.note,
      };
    }
    renderEvaluationUI();
    renderEnginePanel();
  }

  // ----------------------------------------------------------------- history & copy

  function renderMoveHistory() {
    const box = el("move-history");
    const counter = el("move-history-count");
    if (!box) return;
    const history = state.game?.move_history || [];
    if (counter) counter.textContent = `${history.length} ${history.length === 1 ? "ply" : "plies"}`;

    if (!history.length) {
      box.innerHTML = `<p class="hint move-history-empty">No moves yet. Play a move on the board or load a PGN.</p>`;
      return;
    }

    const rowsByMoveNumber = new Map();
    for (const entry of history) {
      const moveNumber = entry.move_number;
      if (!rowsByMoveNumber.has(moveNumber)) {
        rowsByMoveNumber.set(moveNumber, { white: null, black: null });
      }
      rowsByMoveNumber.get(moveNumber)[entry.color] = entry;
    }

    const lastPly = history[history.length - 1].ply;
    const frag = document.createDocumentFragment();
    const sortedNumbers = [...rowsByMoveNumber.keys()].sort((a, b) => a - b);
    for (const moveNumber of sortedNumbers) {
      const { white, black } = rowsByMoveNumber.get(moveNumber);
      const row = document.createElement("div");
      row.className = "move-history-row";
      row.setAttribute("role", "listitem");
      row.innerHTML = `
        <span class="move-number">${moveNumber}.</span>
        ${moveCellHtml(white, lastPly)}
        ${moveCellHtml(black, lastPly)}
      `;
      frag.appendChild(row);
    }
    box.innerHTML = "";
    box.appendChild(frag);
    box.scrollTop = box.scrollHeight;
  }

  function moveCellHtml(entry, lastPly) {
    if (!entry) {
      return `<span class="move-cell empty">--</span>`;
    }
    const isLast = entry.ply === lastPly ? "last" : "";
    return `
      <button type="button" class="move-cell ${isLast}" data-fen="${entry.fen_after}"
              title="Click to copy FEN after ${entry.san}">
        <span class="san">${entry.san}</span>
        <span class="uci">${entry.uci}</span>
      </button>
    `;
  }

  function renderCopyFields() {
    const fenField = el("fen-copy-field");
    if (fenField) fenField.value = state.game?.fen || "--";
  }

  async function refreshPgn(showFeedback = false) {
    const field = el("pgn-copy-field");
    if (!field) return;
    try {
      const data = await api("/api/state/pgn");
      state.pgn = data.pgn || "";
      field.value = state.pgn || "*";
      if (showFeedback) showToast("PGN refreshed.");
    } catch (err) {
      field.value = `Failed to load PGN: ${err.message || err}`;
    }
  }

  async function copyToClipboard(text, label) {
    if (!text) { showToast(`Nothing to copy for ${label}.`); return; }
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.style.position = "absolute";
        helper.style.left = "-9999px";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        document.body.removeChild(helper);
      }
      showToast(`${label} copied to clipboard.`);
    } catch (err) {
      showToast(`Copy failed: ${err.message || err}`);
    }
  }

  async function copyFen() {
    const text = el("fen-copy-field")?.value || state.game?.fen || "";
    await copyToClipboard(text, "FEN");
  }

  async function copyPgn() {
    if (!state.pgn) await refreshPgn();
    const text = state.pgn || el("pgn-copy-field")?.value || "";
    await copyToClipboard(text, "PGN");
  }

  function downloadPgn() {
    const text = state.pgn || el("pgn-copy-field")?.value || "";
    if (!text || text === "*") { showToast("Nothing to download yet."); return; }
    const filename = (state.game?.game_id || "ghostmate-game") + ".pgn";
    const blob = new Blob([text], { type: "application/x-chess-pgn" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function formatMs(ms) {
    if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return "--";
    const n = Number(ms);
    if (n < 1000) return `${Math.max(0, Math.round(n))}ms`;
    return `${(n / 1000).toFixed(2)}s`;
  }

  function handleEngineDepthChange(event) {
    const raw = Number(event.target.value || 15);
    const next = Math.max(1, Math.min(15, Math.round(raw)));
    event.target.value = String(next);
    state.engineMaxDepth = next;
    state.engine = null;
    state.engineLoading = false;
    state.engineError = null;
    reconnectWebSocket();
    queueEngine(20);
    renderEnginePanel();
  }

  let engineDebounceTimer = null;
  function queueEngine(delay = 120) {
    clearTimeout(engineDebounceTimer);
    engineDebounceTimer = setTimeout(refreshEngine, delay);
  }

  // ----------------------------------------------------------------- snapshot

  function renderSnapshot() {
    const grid = el("sensor-grid");
    if (!grid) return;
    const snap = state.snapshot;
    if (!snap?.cells) {
      grid.innerHTML = "";
      setText("occupied-count", "--");
      setText("sensor-timestamp", "--");
      return;
    }
    // Build the 64 cells once. Subsequent calls update text/classes only.
    if (grid.children.length !== 64) {
      grid.innerHTML = "";
      const frag = document.createDocumentFragment();
      for (let i = 0; i < 64; i++) {
        const node = document.createElement("div");
        node.className = "sensor-cell";
        node.innerHTML = `<span></span><small></small>`;
        frag.appendChild(node);
      }
      grid.appendChild(frag);
    }
    let occupied = 0;
    let idx = 0;
    for (let r = 0; r < RANKS.length; r++) {
      const rank = RANKS[r];
      for (let f = 0; f < FILES.length; f++) {
        const file = FILES[f];
        const square = file + rank;
        const cell = snap.cells[square] || { o: 0, p: 0, m: 0 };
        if (cell.o) occupied++;
        const polarity = cell.p < 0 ? "white" : cell.p > 0 ? "black" : "";
        const node = grid.children[idx++];
        const cls = `sensor-cell ${cell.o ? "occupied" : ""} ${polarity}`.trim();
        if (node.className !== cls) node.className = cls;
        const label = node.firstChild;
        const mag = node.lastChild;
        if (label.textContent !== square) label.textContent = square;
        const magText = `m:${cell.m ?? 0}`;
        if (mag.textContent !== magText) mag.textContent = magText;
      }
    }
    setText("occupied-count", String(occupied));
    setText("sensor-timestamp", String(snap.ts_ms || "--"));
  }

  // ----------------------------------------------------------------- events

  function addEvent(type, payload = {}) {
    state.events.unshift({ type, payload, time: new Date().toLocaleTimeString() });
    if (state.events.length > 40) state.events.length = 40;
    renderEvents();
  }

  function renderEvents() {
    const feed = el("events");
    if (!feed) return;
    if (!state.events.length) {
      feed.innerHTML = `<div class="event"><strong>No events yet</strong><small>Live events will appear here.</small></div>`;
      return;
    }
    const frag = document.createDocumentFragment();
    for (const event of state.events) {
      const node = document.createElement("div");
      node.className = "event";
      node.innerHTML = `<strong>${event.type}</strong><small>${event.time}</small><code>${JSON.stringify(event.payload)}</code>`;
      frag.appendChild(node);
    }
    feed.innerHTML = "";
    feed.appendChild(frag);
  }

  // ----------------------------------------------------------------- API ops

  async function refreshStateOnce() {
    state.game = await api("/api/state");
    setText("host-status", "Online");
    scheduleRender();
    queueEngine();
  }

  async function refreshSnapshot() {
    state.snapshot = await api("/api/board/snapshot");
    renderSnapshot();
  }

  async function sendHumanMove(rawMove) {
    const move = String(rawMove || el("uci")?.value || "").trim();
    if (!move) { showToast("Enter a move first."); return; }
    try {
      state.game = await api("/api/move/human", {
        method: "POST", body: JSON.stringify({ uci: move }),
      });
      state.lastMove = { from: move.slice(0, 2), to: move.slice(2, 4) };
      state.selected = null; state.pendingMove = "";
      const input = el("uci"); if (input) input.value = "";
      scheduleRender();
      queueEngine();
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
      if (scanAfter) setTimeout(refreshSnapshot, 100);
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
      showToast("Use valid squares like g1 and f3."); return;
    }
    try {
      const response = await api("/api/move/robot", {
        method: "POST", body: JSON.stringify({ source, target, capture }),
      });
      const log = el("hardware-log");
      if (log) log.textContent = JSON.stringify(response, null, 2);
      addEvent("ROBOT_MOVE_SENT", { source, target, capture, response });
      showToast(`Robot command sent: ${source} \u2192 ${target}`);
    } catch (err) { showToast(err.message); }
  }

  // ----------------------------------------------------------------- WebSocket

  function reconnectWebSocket() {
    if (state.ws) {
      try {
        state.ws.onclose = null;
        state.ws.close(1000, "engine depth changed");
      } catch {}
    }
    state.ws = null;
    connectWebSocket();
  }

  function connectWebSocket() {
    if (state.shuttingDown) return;
    const pill = el("connection-status");
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    state.ws = new WebSocket(
      `${protocol}://${location.host}/ws?engine=1&max_depth=${state.engineMaxDepth}`
    );

    state.ws.onopen = () => {
      state.wsBackoff = 250;
      if (pill) { pill.classList.remove("offline"); pill.innerHTML = "<i></i> Live"; }
      setText("ws-status", "Live");
      addEvent("WS_CONNECTED", { url: "/ws" });
    };
    state.ws.onclose = () => {
      const p = el("connection-status");
      if (p) { p.classList.add("offline"); p.innerHTML = "<i></i> Offline"; }
      if (state.shuttingDown) { setText("ws-status", "Closed"); return; }
      setText("ws-status", "Reconnecting");
      // Exponential backoff, capped.
      const delay = Math.min(state.wsBackoff, 8000);
      state.wsBackoff = Math.min(delay * 2, 8000);
      setTimeout(connectWebSocket, delay);
    };
    state.ws.onerror = () => { if (pill) pill.classList.add("offline"); setText("ws-status", "Error"); };

    state.ws.onmessage = (message) => {
      let data;
      try { data = JSON.parse(message.data); }
      catch (err) { addEvent("WS_PARSE_ERROR", { error: err.message }); return; }

      if (data.type === "PING") return;
      if (data.type !== "ENGINE_UPDATE") addEvent(data.type || "WS_EVENT", data.payload || data);

      if (data.type === "HELLO" && data.state) {
        state.game = data.state;
        scheduleRender();
        queueEngine(60);
        return;
      }

      // Server now embeds the new state in event payloads where relevant.
      const embedded = data.payload?.state;
      if (embedded) {
        state.game = embedded;
        scheduleRender();
      }

      switch (data.type) {
        case "SCAN_RECEIVED": {
          // SCAN payload IS the snapshot — no extra HTTP roundtrip.
          if (data.payload && data.payload.cells) {
            state.snapshot = data.payload;
            renderSnapshot();
          } else {
            refreshSnapshot().catch(() => {});
          }
          break;
        }
        case "LOCAL_MOVE_CANDIDATE":
        case "ROBOT_MOVE_COMPLETE":
        case "STATE_CHANGED": {
          // If state wasn't embedded, fetch once. Normally it is embedded.
          if (!embedded) refreshStateOnce().catch(() => {});
          else queueEngine();
          break;
        }
        case "ENGINE_UPDATE": {
          state.engineLoading = false;
          applyEngineAnalysis(data.payload?.analysis);
          break;
        }
      }
    };
  }

  // ----------------------------------------------------------------- annotations

  function squareNameFromPoint(clientX, clientY) {
    const node = document.elementFromPoint(clientX, clientY)?.closest?.(".square");
    return node?.dataset?.square || null;
  }

  function squareToCenter(square) {
    const board = el("chessboard");
    const node = board?.querySelector?.(`[data-square="${square}"]`);
    if (!board || !node) return null;
    const b = board.getBoundingClientRect();
    const r = node.getBoundingClientRect();
    return { x: r.left - b.left + r.width / 2, y: r.top - b.top + r.height / 2 };
  }

  function isValidAnnotation(from, to) {
    if (!from || !to || from === to) return false;
    const fx = FILES.indexOf(from[0]);
    const tx = FILES.indexOf(to[0]);
    const fy = Number(from[1]);
    const ty = Number(to[1]);
    const dx = Math.abs(tx - fx);
    const dy = Math.abs(ty - fy);
    return dx === 0 || dy === 0 || dx === dy || (dx === 1 && dy === 2) || (dx === 2 && dy === 1);
  }
  function isKnight(from, to) {
    const fx = FILES.indexOf(from[0]); const tx = FILES.indexOf(to[0]);
    const fy = Number(from[1]); const ty = Number(to[1]);
    const dx = Math.abs(tx - fx); const dy = Math.abs(ty - fy);
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
        <marker id="ghostmate-arrow-head" markerWidth="3.8" markerHeight="3.8"
          refX="3.25" refY="1.9" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,3.8 L3.8,1.9 z" class="annotation-arrow-head"></path>
        </marker>
      </defs>`;
    board.appendChild(svg);
  }

  function drawAnnotation(svg, annotation, draft = false) {
    const board = el("chessboard");
    const rect = board.getBoundingClientRect();
    const from = squareToCenter(annotation.from);
    const to = squareToCenter(annotation.to);
    if (!from || !to) return;
    const sx = (from.x / rect.width) * 100, sy = (from.y / rect.height) * 100;
    const tx = (to.x / rect.width) * 100, ty = (to.y / rect.height) * 100;
    if (isKnight(annotation.from, annotation.to)) {
      const horiz = Math.abs(tx - sx) > Math.abs(ty - sy);
      const mx = horiz ? tx : sx; const my = horiz ? sy : ty;
      const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      poly.setAttribute("points", `${sx},${sy} ${mx},${my} ${tx},${ty}`);
      poly.setAttribute("class", `annotation-line annotation-knight ${draft ? "draft" : ""}`);
      poly.setAttribute("marker-end", "url(#ghostmate-arrow-head)");
      svg.appendChild(poly);
      return;
    }
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", sx); line.setAttribute("y1", sy);
    line.setAttribute("x2", tx); line.setAttribute("y2", ty);
    line.setAttribute("class", `annotation-line ${draft ? "draft" : ""}`);
    line.setAttribute("marker-end", "url(#ghostmate-arrow-head)");
    svg.appendChild(line);
  }

  function renderAnnotations() {
    ensureAnnotationLayer();
    const board = el("chessboard");
    const svg = board?.querySelector(".annotation-layer");
    if (!svg) return;
    svg.querySelectorAll(".annotation-line").forEach(n => n.remove());
    for (const annotation of state.annotations) drawAnnotation(svg, annotation, false);
    if (state.annotationDraft?.from && state.annotationDraft?.to) {
      drawAnnotation(svg, state.annotationDraft, true);
    }
  }

  function bindAnnotationHandlers() {
    const board = el("chessboard");
    if (!board || board.dataset.annotationsBound) return;
    board.dataset.annotationsBound = "1";
    board.addEventListener("contextmenu", e => e.preventDefault());
    board.addEventListener("pointerdown", (event) => {
      if (event.button !== 2) return;
      const sq = event.target.closest?.(".square");
      const from = sq?.dataset?.square;
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
      if (isValidAnnotation(draft.from, draft.to)) {
        state.annotations.push(draft);
        addEvent("BOARD_ANNOTATION", draft);
      } else if (draft.from !== draft.to) {
        showToast("Only straight, diagonal, or knight L-shape annotations are allowed.");
      }
      renderAnnotations();
    });
    board.addEventListener("dblclick", () => {
      state.annotations = []; state.annotationDraft = null;
      renderAnnotations();
      showToast("Board annotations cleared.");
    });
  }

  // ----------------------------------------------------------------- FEN/PGN load

  async function loadFenFromInput() {
    const text = (el("position-text")?.value || "").trim();
    if (!text) { showToast("Paste a FEN first."); return; }
    try {
      state.game = await api("/api/position/fen", {
        method: "POST", body: JSON.stringify({ fen: text }),
      });
      scheduleRender();
      queueEngine(50);
      showToast("FEN loaded.");
    } catch (err) { showToast(err.message || String(err)); }
  }
  async function loadPgnFromInput() {
    const text = (el("position-text")?.value || "").trim();
    if (!text) { showToast("Paste a PGN first."); return; }
    try {
      state.game = await api("/api/position/pgn", {
        method: "POST", body: JSON.stringify({ pgn: text }),
      });
      scheduleRender();
      queueEngine(50);
      showToast("PGN loaded at final position.");
    } catch (err) { showToast(err.message || String(err)); }
  }

  async function askCoach() {
    const question = (el("coach-question")?.value || "").trim();
    const output = el("coach-answer");
    const pill = el("coach-source-pill");
    if (output) output.textContent = "Thinking with current board state and Stockfish lines...";
    if (pill) pill.textContent = "thinking";
    try {
      const result = await api("/api/ai/coach", {
        method: "POST",
        body: JSON.stringify({ question, style: "student" }),
      });
      if (output) output.textContent = (result.answer || "").trim() || "No answer.";
      if (pill) {
        const label = result.source === "llm"
          ? `llm: ${result.model || "model"}`
          : result.source === "llm_error"
            ? "llm error — local fallback"
            : "local coach";
        pill.textContent = label;
      }
    } catch (err) {
      if (output) output.textContent = err.message || String(err);
      if (pill) pill.textContent = "error";
      showToast(err.message || String(err));
    }
  }

  // ----------------------------------------------------------------- bind

  function bindEvents() {
    el("new-game")?.addEventListener("click", async () => {
      try {
        state.game = await api("/api/game/new", { method: "POST" });
        state.selected = null; state.pendingMove = ""; state.lastMove = null;
        scheduleRender(); queueEngine();
        addEvent("NEW_GAME", { game_id: state.game.game_id });
        showToast("New game started.");
      } catch (err) { showToast(err.message); }
    });
    el("refresh-all")?.addEventListener("click", async () => {
      await refreshStateOnce(); await refreshSnapshot();
      showToast("Dashboard refreshed.");
    });
    el("scan-board-hero")?.addEventListener("click", () => hardwareCommand("/api/hardware/scan", true));
    el("refresh-snapshot")?.addEventListener("click", refreshSnapshot);
    el("send-move")?.addEventListener("click", () => sendHumanMove());
    el("submit-selected")?.addEventListener("click", () => sendHumanMove(state.pendingMove));
    el("send-robot-move")?.addEventListener("click", sendRobotMove);
    el("uci")?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendHumanMove(); });
    el("move-filter")?.addEventListener("input", renderEnginePanel);
    el("load-fen")?.addEventListener("click", loadFenFromInput);
    el("load-pgn")?.addEventListener("click", loadPgnFromInput);
    el("ask-coach")?.addEventListener("click", askCoach);
    el("copy-fen")?.addEventListener("click", copyFen);
    el("copy-pgn")?.addEventListener("click", copyPgn);
    el("refresh-pgn")?.addEventListener("click", () => refreshPgn(true));
    el("download-pgn")?.addEventListener("click", downloadPgn);
    el("move-history")?.addEventListener("click", (event) => {
      const target = event.target.closest("button.move-cell");
      if (!target) return;
      const fen = target.dataset.fen;
      if (fen) copyToClipboard(fen, "FEN at move");
    });
    el("flip-board")?.addEventListener("click", () => { state.flipped = !state.flipped; scheduleRender(); });
    el("clear-selection")?.addEventListener("click", () => {
      state.selected = null; state.pendingMove = "";
      state.annotations = []; state.annotationDraft = null;
      const input = el("uci"); if (input) input.value = "";
      scheduleRender();
    });
    el("clear-events")?.addEventListener("click", () => { state.events = []; renderEvents(); });
    el("toggle-raw")?.addEventListener("click", () => {
      state.showRaw = !state.showRaw;
      el("state")?.classList.toggle("hidden", !state.showRaw);
      if (state.showRaw && state.game) {
        const raw = el("state");
        if (raw) raw.textContent = JSON.stringify(state.game, null, 2);
      }
    });
    el("theme-toggle")?.addEventListener("click", () => {
      document.body.classList.toggle("dark");
      try {
        localStorage.setItem("ghostmate-theme", document.body.classList.contains("dark") ? "dark" : "light");
      } catch {}
    });
    document.querySelectorAll("[data-hardware]").forEach(button => {
      button.addEventListener("click", () => hardwareCommand(button.dataset.hardware, button.dataset.scan === "true"));
    });
    document.querySelectorAll("[data-quick-move]").forEach(button => {
      button.addEventListener("click", () => sendHumanMove(button.dataset.quickMove));
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) queueEngine(60);
    });
  }

  let clockTimer = null;
  function tickClock() { setText("clock", new Date().toLocaleTimeString()); }

  async function boot() {
    try {
      try {
        if (localStorage.getItem("ghostmate-theme") === "dark") document.body.classList.add("dark");
      } catch {}
      bindEvents();
      renderAxisLabels();
      buildBoardOnce();
      bindAnnotationHandlers();
      renderEvents();
      renderSnapshot();
      tickClock();
      clockTimer = setInterval(tickClock, 1000);
      await api("/api/health");
      setText("host-status", "Online");
      await refreshStateOnce();
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
      try { state.ws.onclose = null; state.ws.close(1000, "page unload"); } catch {}
    }
    if (clockTimer) clearInterval(clockTimer);
  });
  window.addEventListener("pagehide", () => { state.shuttingDown = true; });

  // Expose a tiny debug helper without polluting global scope further.
  window.GhostMate = { state, refreshEngine: refreshEngine, refreshState: refreshStateOnce };
})();
