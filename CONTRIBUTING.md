# Contributing to Agentic Engram

## Development Setup

### Using uv

```bash
git clone https://github.com/sert-xx/agentic-engram.git
cd agentic-engram
uv sync --extra dev
```

### Using pip

```bash
git clone https://github.com/sert-xx/agentic-engram.git
cd agentic-engram
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
# Using uv
uv run pytest -v
uv run pytest tests/test_save.py

# Using pip (with virtualenv activated)
pytest -v                 # run all tests
pytest tests/test_save.py # run a specific module
```

## Code Style

- Follow existing patterns in the codebase.
- Type hints are expected on all public functions.
- Use `from __future__ import annotations` at the top of every module.
- Keep dependencies minimal -- no cloud services, no Docker.

## Pull Requests

1. Fork the repo and create a feature branch from `main`.
2. Add or update tests for any new functionality.
3. Ensure all tests pass (`pytest`).
4. Write a clear PR description explaining **what** and **why**.
5. Keep PRs focused -- one logical change per PR.

## Reporting Issues

Open a GitHub issue with:
- Steps to reproduce
- Expected vs. actual behavior
- Python version and OS
