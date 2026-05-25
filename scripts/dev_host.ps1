# GhostMate host dev launcher (Windows PowerShell).
# uvloop is Linux/macOS only; on Windows we use the default selector loop.
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn host.app.main:app --host 127.0.0.1 --port 8000 --no-access-log --reload
