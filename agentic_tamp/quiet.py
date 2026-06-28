"""Silence OMPL's C++ logging so harness/agent output stays readable.

OMPL writes Info/Debug lines directly to the process's stderr from C++, which
bypasses Python's ``contextlib.redirect_stdout``. Lowering its log level once
keeps the comparison output and the captured motion diagnostics clean.
"""


def quiet_ompl() -> None:
    """Set OMPL's log level to errors-only (best effort)."""
    try:
        from ompl import util as ou

        ou.setLogLevel(ou.LogLevel.LOG_ERROR)
    except Exception:  # noqa: BLE001 - logging suppression is non-critical
        pass
