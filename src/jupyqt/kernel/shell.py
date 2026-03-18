"""InteractiveShell creation and output capture for jupyqt."""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

from IPython.core.interactiveshell import InteractiveShell

if TYPE_CHECKING:
    from collections.abc import Callable


def create_shell() -> InteractiveShell:
    """Create and return a fresh IPython InteractiveShell instance."""
    InteractiveShell.clear_instance()
    return InteractiveShell.instance(colors="neutral", autocall=0)


class OutputCapture:
    """Context manager that captures stdout/stderr and routes to callbacks."""

    def __init__(
        self,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> None:
        """Configure callbacks for captured stdout and stderr output."""
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr
        self._orig_stdout: io.TextIOBase | None = None
        self._orig_stderr: io.TextIOBase | None = None

    def __enter__(self) -> OutputCapture:  # noqa: PYI034
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        if self._on_stdout:
            sys.stdout = _CallbackWriter(self._on_stdout)
        if self._on_stderr:
            sys.stderr = _CallbackWriter(self._on_stderr)
        return self

    def __exit__(self, *exc: object) -> bool:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        return False

    def flush(self) -> None:
        """No-op flush to satisfy the stream interface."""


class _CallbackWriter(io.TextIOBase):
    """A writable stream that sends each write() to a callback."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        """Attach the given callback as the write target."""
        self._callback = callback

    def write(self, text: str) -> int:
        """Forward non-empty text to the callback and return its length."""
        if text:
            self._callback(text)
        return len(text)

    def flush(self) -> None:
        """No-op flush to satisfy the stream interface."""
