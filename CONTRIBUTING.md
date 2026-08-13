# Contributing

## Development setup

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,browser]"
.\.venv\Scripts\python.exe -m playwright install chromium
```

Before opening a pull request, run:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m pip check
```

Keep core filesystem logic in `scanner.py`, `analyzer.py`, and `duplicates.py`;
CLI and GUI code should depend on `service.py`, not on each other. Do not add
automatic deletion behavior. Use focused commits with Conventional Commit
messages and include tests for behavior changes.

Dashboard changes must preserve the `/api/v1` contract or document an explicit
compatibility path. Add API tests for status codes/error codes and Chromium tests
for user-visible workflows. Never expose the local service on a non-loopback
address. Operational details live in `docs/api.md` and `docs/operations.md`.
