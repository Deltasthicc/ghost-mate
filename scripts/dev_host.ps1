python -m venv venv
.\venv\Scripts\activate
pip install -e .[dev]
uvicorn host.app.main:app --reload
