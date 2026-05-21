from __future__ import annotations

import sys
from host.app.chesscore.replay import PgnReplay


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/replay_pgn.py game.pgn")
    for uci in PgnReplay().load_moves(sys.argv[1]):
        print(uci)
