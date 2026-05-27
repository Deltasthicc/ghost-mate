"""Sanity / hygiene tests for the UI templates, static assets, and source.

These guard the contract between the HTML template, the static JS/CSS,
and the backend. They are intentionally cheap so they run on every commit.

Coverage:
- Index template renders and contains every element the JS depends on
- Static JS file declares every function the dashboard binds
- Static CSS file declares the layout selectors the board support layout needs
- The coach module source contains *none* of the boilerplate phrases the
  user explicitly rejected
- The JS no longer appends 'Source: ...' to the visible coach answer body
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "host" / "app" / "ui" / "static"
TEMPLATE_DIR = REPO_ROOT / "host" / "app" / "ui" / "templates"
COACH_SRC = REPO_ROOT / "host" / "app" / "ai" / "coach.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Index template via HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexTemplateHttp:
    def test_root_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.parametrize("needle", [
        "GhostMate",
        "move-history",
        "fen-copy-field",
        "pgn-copy-field",
        "copy-fen",
        "copy-pgn",
        "download-pgn",
        "refresh-pgn",
        "ai-coach-panel",
        "coach-question",
        "coach-answer",
        "coach-source-pill",
        "position-loader",
        "load-fen",
        "load-pgn",
        "board-support-grid",
        "study-history",
        "study-tools",
        "study-coach",
    ])
    def test_rendered_index_contains_required_id_or_class(self, client, needle):
        body = client.get("/").text
        assert needle in body, f"Expected '{needle}' in the rendered index"


# ─────────────────────────────────────────────────────────────────────────────
# Index template file contents
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexTemplateFile:
    @pytest.fixture(scope="class")
    def html(self) -> str:
        return _read(TEMPLATE_DIR / "index.html")

    @pytest.mark.parametrize("needle", [
        '<section class="board-support-grid"',
        'id="move-history"',
        'id="fen-copy-field"',
        'id="pgn-copy-field"',
        'id="copy-fen"',
        'id="copy-pgn"',
        'id="download-pgn"',
        'id="ai-coach-panel"',
        'id="coach-style"',
        'id="coach-source-pill"',
        'id="position-loader"',
    ])
    def test_template_has_required_anchor(self, html, needle):
        assert needle in html

    def test_template_does_not_contain_forbidden_boilerplate(self, html):
        # The dynamic coach panel previously appended "Source: ${result.source}"
        # — make sure it never sneaks back into the static template.
        for phrase in ("advisory only", "tactical anchor", "Source: ${"):
            assert phrase not in html


# ─────────────────────────────────────────────────────────────────────────────
# Static JS
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticJsContract:
    @pytest.fixture(scope="class")
    def js(self) -> str:
        return _read(STATIC_DIR / "app.js")

    @pytest.mark.parametrize("symbol", [
        "renderMoveHistory",
        "renderCopyFields",
        "refreshPgn",
        "copyToClipboard",
        "copyFen",
        "copyPgn",
        "downloadPgn",
        "askCoach",
        "loadFenFromInput",
        "loadPgnFromInput",
        "reconnectWebSocket",
        "applyEngineAnalysis",
        "queuePgnRefresh",
        "loadEngineSettings",
        "saveEngineSettings",
        "applyEngineSettings",
        "bindEngineSettingControls",
    ])
    def test_js_declares_required_symbol(self, js, symbol):
        assert symbol in js, f"Expected '{symbol}' to be defined in app.js"

    def test_js_uses_state_pgn_endpoint(self, js):
        assert "/api/state/pgn" in js

    def test_js_uses_ai_coach_endpoint(self, js):
        assert "/api/ai/coach" in js

    def test_js_uses_engine_settings_endpoint(self, js):
        assert "/api/engine/settings" in js

    def test_js_bind_block_wires_new_buttons(self, js):
        for binding in (
            'el("copy-fen")?.addEventListener',
            'el("copy-pgn")?.addEventListener',
            'el("download-pgn")?.addEventListener',
            'el("ask-coach")?.addEventListener',
            'el("load-fen")?.addEventListener',
            'el("load-pgn")?.addEventListener',
            'el("ask-coach")?.addEventListener',
        ):
            assert binding in js

    def test_js_does_not_paste_source_into_coach_answer(self, js):
        # Old behaviour: `Source: ${result.source}` was appended to the answer
        # body. The new code only uses a pill chip — make sure the regression
        # cannot return.
        assert "Source: ${result.source}" not in js
        assert "`${result.answer}\\n\\nSource:" not in js

    def test_js_websocket_uses_engine_param(self, js):
        assert "engine=1" in js
        assert "max_depth=${state.engineMaxDepth}" in js


# ─────────────────────────────────────────────────────────────────────────────
# Static CSS
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticCssContract:
    @pytest.fixture(scope="class")
    def css(self) -> str:
        return _read(STATIC_DIR / "style.css")

    @pytest.mark.parametrize("selector", [
        ".board-support-grid",
        ".study-history",
        ".study-tools",
        ".study-coach",
        ".move-history",
        ".move-history-row",
        ".move-cell",
        ".status-chip",
        ".copy-field",
        ".copy-input",
        ".copy-textarea",
        ".tool-row",
        ".panel.inset",
        ".position-loader-card",
        ".engine-controls",
        ".engine-stat-grid",
        ".coach-toolbar",
        ".select-input",
        ".coach-answer",
    ])
    def test_css_defines_selector(self, css, selector):
        assert selector in css

    def test_css_has_responsive_breakpoint(self, css):
        assert "@media (max-width: 1280px)" in css


# ─────────────────────────────────────────────────────────────────────────────
# Coach source hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestCoachSourceHygiene:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        return _read(COACH_SRC)

    @pytest.mark.parametrize("forbidden", [
        # The exact paragraph the user objected to.
        "use the Stockfish line as the tactical anchor",
        "This coach is advisory only",
        "robot commands still go through the host",
        # Pre-formatted "Source: local_fallback" line — must never live in
        # the answer body itself; the API exposes it as a separate field.
        '"Source: local_fallback"',
    ])
    def test_source_contains_no_boilerplate(self, src, forbidden):
        assert forbidden not in src
