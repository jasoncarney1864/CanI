# CanI

## Local test run

Use the project test virtual environment so dependencies and import paths match CI.

```powershell
.\.venv-test\Scripts\python.exe -m pytest -q
```

If you need to rebuild the test environment:

```powershell
python -m venv .venv-test
.\.venv-test\Scripts\python.exe -m pip install --upgrade pip
.\.venv-test\Scripts\python.exe -m pip install -r requirements-dev.txt
```