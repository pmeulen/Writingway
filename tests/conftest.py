"""
Shared pytest fixtures for the Writingway test suite.

This conftest.py is placed at the repo root so that all sub-packages under
``tests/`` can import it automatically.  It provides:

* ``tmp_projects_dir``  – a temporary "Projects/" tree that isolates each test
  from the real project data.
* ``isolated_cwd``      – changes the working directory to the tmp directory
  so that ``WWSettingsManager`` path helpers produce paths inside the sandbox.
* ``compendium_manager`` – a ready-to-use ``CompendiumManager`` wired to a
  temporary project directory.
"""

import pytest

# ---------------------------------------------------------------------------
# Filesystem isolation helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_projects_dir(tmp_path):
    """
    Create a temporary Projects/<project>/ directory tree and return the
    path to the root (the directory that contains the "Projects" folder).

    The fixture does NOT change the working directory; use ``isolated_cwd``
    when code under test calls ``os.getcwd()`` to locate project files.
    """
    projects_root = tmp_path / "Projects"
    projects_root.mkdir()
    return tmp_path


@pytest.fixture()
def isolated_cwd(tmp_projects_dir, monkeypatch):
    """
    Change the process working directory to *tmp_projects_dir* for the
    duration of a single test, then restore it automatically.

    Modules that call ``os.getcwd()`` at import time are not affected; only
    calls made *during* the test will see the sandboxed directory.
    """
    monkeypatch.chdir(tmp_projects_dir)
    return tmp_projects_dir


# ---------------------------------------------------------------------------
# CompendiumManager fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def compendium_manager(isolated_cwd):
    """
    Return a ``CompendiumManager`` instance pointing at a fresh, empty project
    directory inside the temporary sandbox.

    The instance uses the project name ``"TestProject"`` and has no event bus
    so that tests remain fully synchronous and side-effect free.
    """
    from compendium.compendium_manager import CompendiumManager

    project_name = "TestProject"
    # Ensure the project directory exists before creating the manager.
    project_dir = isolated_cwd / "Projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    return CompendiumManager(project_name=project_name, event_bus=None)

