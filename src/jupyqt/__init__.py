"""jupyqt — Embed JupyterLab in PySide6 applications."""

from __future__ import annotations

__all__: list[str] = ["EmbeddedJupyter", "QtProxy"]


def __getattr__(name: str) -> object:
    if name == "EmbeddedJupyter":
        from jupyqt.api import EmbeddedJupyter  # noqa: PLC0415
        return EmbeddedJupyter
    if name == "QtProxy":
        from jupyqt.qt.proxy import QtProxy  # noqa: PLC0415
        return QtProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
