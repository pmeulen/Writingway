# Running the tests

## Prerequisites

Activate the project virtual environment before running any commands:

```bash
source venv/bin/activate
```

Install the dev dependencies if you have not done so already:

```bash
pip install ".[dev]"
```

---

## Running the full test suite

From the repository root:

```bash
python -m pytest tests/
```

Pytest is configured in `pytest.ini`. By default every run is verbose (`-v`), uses short tracebacks (`--tb=short`), and enforces declared markers (`--strict-markers`).

---

## Filtering tests

### By directory or file

```bash
# All tests for the compendium package
python -m pytest tests/compendium/

# A single test file
python -m pytest tests/settings/test_settings_manager.py
```

### By marker

```bash
# Only pure unit tests (no filesystem I/O, no Qt)
python -m pytest -m unit

# Only filesystem integration tests
python -m pytest -m integration

# Only Qt widget tests (requires a display)
python -m pytest -m qt
```

### By name (substring match)

```bash
python -m pytest -k "rename"        # any test whose name contains "rename"
python -m pytest -k "category and not remove"
```

---

## Coverage report

```bash
# Terminal summary, including missing lines
python -m pytest tests/ --cov=. --cov-report=term-missing

# Terminal summary, coverage only
python -m pytest tests/ --cov=. --cov-report=term

# Report coverage for a specific package (e.g. compendium)
python -m pytest tests/ --cov=compendium --cov-report=term

# Report coverage for a specific directory (e.g. ./project_window)
python -m pytest tests/ --cov=./project_window --cov-report=term


# HTML report (opens at htmlcov/index.html)
python -m pytest tests/ --cov=. --cov-report=html
```

---

## Markers

| Marker                     | When to use                                                                                                                                                                      |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `@pytest.mark.unit`        | Pure logic — no filesystem access, no Qt, fully synchronous.                                                                                                                     |
| `@pytest.mark.integration` | Touches the filesystem. Uses the `isolated_cwd` fixture from `tests/conftest.py` to sandbox all I/O inside a temporary directory; the real `Projects/` tree is never written to. |
| `@pytest.mark.qt`          | Requires a live `QApplication`. Use the `qtbot` fixture provided by pytest-qt.                                                                                                   |

Apply markers to individual tests or whole classes:

```python
@pytest.mark.unit
def test_sanitize_strips_special_characters():
    ...

@pytest.mark.integration
class TestCategoryCRUD:
    ...
```

---

## Writing tests
- Mirror the source layout: `compendium/foo.py` → `tests/compendium/test_foo.py`.
- Add `tests/<package>/__init__.py` if it does not exist yet.
- Mark every test with the appropriate marker (`unit`, `integration`, or `qt`).
- Use the shared fixtures from `tests/conftest.py`:
  - `isolated_cwd` — changes the working directory to a temp sandbox for the duration of the test. Required for every `integration` test.
  - `compendium_manager` — a ready-to-use `CompendiumManager` wired to a fresh project directory inside the sandbox.
- Waiting for Qt events in `qt` tests:
  - `qtbot.waitSignal(signal, timeout=1000)`: use when waiting for a specific async result (debounced save, event bus update, etc.). Fails fast and deterministically if the signal never fires.
  - `qtbot.wait(100)`: use only to let the event loop flush already-queued events (repaints, layout passes, deferred deletions) when there is no signal to wait on.
  - `qtbot.waitExposed(widget)`: use when waiting for a window or dialog to become visible.
- Verify new tests pass before committing: `python -m pytest tests/`.

