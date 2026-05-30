# Running the tests

## Prerequisites

Activate the project virtual environment before running any commands:

```bash
source venv/bin/activate
```

Install the test dependencies if you have not done so already:

```bash
pip install pytest pytest-qt pytest-cov
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
# Terminal summary
python -m pytest tests/ --cov=. --cov-report=term-missing

# HTML report (opens at htmlcov/index.html)
python -m pytest tests/ --cov=. --cov-report=html
```

---

## Markers

| Marker        | When to use                                                                                                                                                                     |
|---------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `unit`        | Pure logic — no filesystem access, no Qt, fully synchronous.                                                                                                                    |
| `integration` | Touches the filesystem. Uses the `isolated_cwd` fixture from `tests/conftest.py` to sandbox all I/O inside a temporary directory; the real `Projects/` tree is never written to. |
| `qt`          | Requires a live `QApplication`. Use the `qtbot` fixture provided by **pytest-qt**.                                                                                              |

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

## Writing new tests

1. Mirror the source layout: `compendium/foo.py` → `tests/compendium/test_foo.py`.
2. Add `tests/<package>/__init__.py` if it does not exist yet.
3. Use the shared fixtures from `tests/conftest.py`:
   - `isolated_cwd` — changes the working directory to a temp sandbox for the duration of the test.
   - `compendium_manager` — a ready-to-use `CompendiumManager` wired to a fresh project directory inside the sandbox.
4. Mark every test with the appropriate marker (`unit`, `integration`, or `qt`).
5. Verify the new tests pass before committing: `python -m pytest tests/`.

