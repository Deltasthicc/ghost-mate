from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

ROOT = Path.cwd()
FILES = {
    "game_state": ROOT / "host" / "app" / "domain" / "game_state.py",
    "config": ROOT / "host" / "app" / "config.py",
    "ws": ROOT / "host" / "app" / "api" / "ws.py",
    "env": ROOT / ".env",
    "env_example": ROOT / ".env.example",
}

def fail(msg: str) -> None:
    raise SystemExit(f"\nERROR: {msg}\nRun this script from the Ghost-mate project root, e.g.\n"
                     f"  cd C:\\Users\\shash\\Downloads\\Ghost-mate\n"
                     f"  python fix_ghost_mate_all.py\n")

def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"Missing file: {path}")

def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")

def backup(path: Path) -> None:
    if path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)

def patch_game_state() -> None:
    path = FILES["game_state"]
    text = read(path)
    backup(path)

    if "from uuid import uuid4" not in text:
        text = text.replace("import os\n", "import os\nfrom uuid import uuid4\n", 1)

    pattern = r"def make_game_id\(\) -> str:\n(?:    .*\n)+?\n(?=def _material_score_cp)"
    replacement = """def make_game_id() -> str:
    \"\"\"Return a unique, human-readable game id.

    The timestamp keeps saved games easy to inspect, while the UUID suffix
    prevents collisions when tests or API calls create multiple games inside
    the same system-clock tick. This matters on Windows, where back-to-back
    datetime calls can sometimes return the same microsecond value.
    \"\"\"
    timestamp = datetime.now(timezone.utc).strftime("game-%Y%m%d-%H%M%S-%f")
    return f"{timestamp}-{uuid4().hex[:8]}"


"""
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        fail("Could not patch make_game_id() in host/app/domain/game_state.py")
    write(path, new_text)

def patch_config() -> None:
    path = FILES["config"]
    text = read(path)
    backup(path)

    if "from pydantic import Field" not in text:
        text = text.replace("from pathlib import Path\n", "from pathlib import Path\nfrom pydantic import Field\n", 1)

    text = re.sub(
        r"^\s*debug:\s*bool\s*=\s*(?:True|False)\s*$",
        '    # Use APP_DEBUG instead of DEBUG. Some tools set DEBUG to values like "release",\n'
        '    # which Pydantic cannot parse as a boolean during app/test startup.\n'
        '    debug: bool = Field(default=True, validation_alias="APP_DEBUG")',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    write(path, text)

def patch_env_file(path: Path) -> None:
    if not path.exists():
        return
    text = read(path)
    backup(path)
    text = re.sub(r"(?m)^DEBUG=", "APP_DEBUG=", text)
    write(path, text)

def patch_ws() -> None:
    path = FILES["ws"]
    text = read(path)
    backup(path)

    if "from fastapi.encoders import jsonable_encoder" not in text:
        text = text.replace(
            "from fastapi import APIRouter, WebSocket, WebSocketDisconnect\n",
            "from fastapi import APIRouter, WebSocket, WebSocketDisconnect\n"
            "from fastapi.encoders import jsonable_encoder\n",
            1,
        )

    text = text.replace("await websocket.send_json(event)", "await websocket.send_json(jsonable_encoder(event))")
    write(path, text)

def clear_caches() -> None:
    for dirname in ["__pycache__", ".pytest_cache"]:
        for path in ROOT.rglob(dirname):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

def verify_source_text() -> None:
    text = read(FILES["game_state"])
    if "from uuid import uuid4" not in text or "uuid4().hex[:8]" not in text:
        fail("Verification failed: game_state.py still does not contain the UUID game_id fix.")

    cfg = read(FILES["config"])
    if 'validation_alias="APP_DEBUG"' not in cfg:
        fail("Verification failed: config.py still reads generic DEBUG instead of APP_DEBUG.")

    ws = read(FILES["ws"])
    if "jsonable_encoder(event)" not in ws:
        fail("Verification failed: ws.py still sends raw Event objects instead of JSON-safe data.")

def main() -> None:
    for key in ("game_state", "config", "ws"):
        if not FILES[key].exists():
            fail(f"Missing required project file: {FILES[key]}")

    patch_game_state()
    patch_config()
    patch_env_file(FILES["env"])
    patch_env_file(FILES["env_example"])
    patch_ws()
    clear_caches()
    verify_source_text()

    print("\nPatched successfully.")
    print("Now run:")
    print("  pytest host/tests/ -q")
    print("\nA correct game_id should now look like:")
    print("  game-20260523-141602-508658-a1b2c3d4")
    print("not:")
    print("  game-20260523-141602-508658")

if __name__ == "__main__":
    main()
