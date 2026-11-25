@echo off
REM Starts FinAI C on http://localhost:8006
cd /d "%~dp0"
if not exist .venv (
  echo First start: creating the Python environment and installing the libraries...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python -m scripts.seed_examples
start "" http://localhost:8006
uvicorn app.main:app --port 8006
pause
