"""jupyqt — Embed JupyterLab in PySide6 applications."""

from __future__ import annotations

__all__: list[str] = ["EmbeddedJupyter", "QtProxy"]


def __getattr__(name: str):
    if name == "EmbeddedJupyter":
        from jupyqt.api import EmbeddedJupyter
        return EmbeddedJupyter
    if name == "QtProxy":
        from jupyqt.qt.proxy import QtProxy
        return QtProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
