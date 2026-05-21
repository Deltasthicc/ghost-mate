from pathlib import Path
import re

app_path = Path("host/app/ui/static/app.js")
css_path = Path("host/app/ui/static/style.css")

app = app_path.read_text(encoding="utf-8")

# Use normal chess-piece glyphs again.
# These render much cleaner than forcing all pieces into the black-piece glyph set.
app = re.sub(
    r'const pieces = \{[\s\S]*?\};',
    '''const pieces = {
  P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};''',
    app,
)

# Replace the oversized marker definition inside ensureAnnotationLayer.
app = re.sub(
    r'svg\.innerHTML = `[\s\S]*?<defs>[\s\S]*?</defs>[\s\S]*?`;',
    '''svg.innerHTML = `
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
  `;''',
    app,
)

app_path.write_text(app, encoding="utf-8")

css = css_path.read_text(encoding="utf-8")

# Remove older bad piece/annotation patches if present.
css = re.sub(
    r'\n/\* ===== Solid chess piece rendering patch ===== \*/[\s\S]*?(?=\n/\*|$)',
    "\n",
    css,
)

css = re.sub(
    r'\n/\* === GhostMate tactical overlay and piece outline patch START === \*/[\s\S]*?/\* === GhostMate tactical overlay and piece outline patch END === \*/\n?',
    "\n",
    css,
)

css += r'''

/* === GhostMate clean chess-piece and annotation fix START === */

/* Clean, readable pieces without ugly heavy strokes */
.piece {
  opacity: 1 !important;
  line-height: 1 !important;
  font-family:
    "Segoe UI Symbol",
    "Noto Sans Symbols 2",
    "Arial Unicode MS",
    "DejaVu Sans",
    serif !important;
  font-weight: 400 !important;
  transform: translateY(-1px);
  filter: none !important;
}

/* White pieces: crisp ivory with a subtle dark halo */
.piece.white {
  color: #fffaf0 !important;
  -webkit-text-stroke: 0 !important;
  text-shadow:
    0 0 1px rgba(8, 12, 22, 0.92),
    0 1px 2px rgba(8, 12, 22, 0.72),
    0 5px 12px rgba(8, 12, 22, 0.24) !important;
}

/* Black pieces: solid charcoal with a tiny soft light edge */
.piece.black {
  color: #10141f !important;
  -webkit-text-stroke: 0 !important;
  text-shadow:
    0 0 1px rgba(255, 255, 255, 0.72),
    0 1px 2px rgba(255, 255, 255, 0.24),
    0 5px 11px rgba(0, 0, 0, 0.22) !important;
}

.square:hover .piece {
  transform: translateY(-3px) scale(1.035) !important;
}

/* Slightly calmer board colors so pieces remain readable */
.square.light-square {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.18), transparent 50%),
    #f1eee6 !important;
}

.square.dark-square {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.10), transparent 50%),
    #aeb9c8 !important;
}

/* Evaluation text */
.eval-inline {
  display: inline-block;
  margin-top: 4px;
  color: #bebdff;
  font-weight: 850;
  letter-spacing: 0.01em;
}

#eval-detail-value {
  color: #ffffff;
}

/* Chess-analysis annotation layer */
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

/* Clean arrow/line style: thin, soft, readable */
.annotation-line {
  fill: none !important;
  stroke: rgba(95, 150, 255, 0.82) !important;
  stroke-width: 0.95 !important;
  stroke-linecap: round !important;
  stroke-linejoin: round !important;
  filter:
    drop-shadow(0 1px 2px rgba(5, 8, 18, 0.28))
    drop-shadow(0 0 4px rgba(95, 150, 255, 0.20)) !important;
}

.annotation-line.draft {
  stroke: rgba(255, 255, 255, 0.72) !important;
  stroke-width: 0.8 !important;
  stroke-dasharray: 1.8 1.4 !important;
}

.annotation-knight {
  stroke: rgba(178, 181, 255, 0.88) !important;
}

.annotation-arrow-head {
  fill: rgba(95, 150, 255, 0.82) !important;
}

/* Make the selected square and legal targets cleaner too */
.square.selected {
  box-shadow:
    inset 0 0 0 3px rgba(126, 181, 255, 0.92),
    inset 0 0 0 999px rgba(126, 181, 255, 0.10) !important;
}

.square.target::after {
  width: 20% !important;
  height: 20% !important;
  background: rgba(69, 190, 130, 0.72) !important;
  box-shadow: 0 0 0 5px rgba(69, 190, 130, 0.12) !important;
}

/* === GhostMate clean chess-piece and annotation fix END === */
'''

css_path.write_text(css, encoding="utf-8")
