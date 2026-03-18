"""Qt proxy layer for cross-thread access from kernel to Qt main thread."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject

if TYPE_CHECKING:
    from collections.abc import Callable


class _InvokeEvent(QEvent):
    """Custom QEvent carrying a callable to execute on the main thread."""

    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(
        self,
        func: Callable,
        args: tuple,
        kwargs: dict,
        result_event: threading.Event,
        result_box: list,
    ) -> None:
        """Store the callable and synchronisation primitives for later execution."""
        super().__init__(self.EVENT_TYPE)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result_event = result_event
        self.result_box = result_box  # [value, exception]


class _Receiver(QObject):
    """Receives _InvokeEvents and executes them on the main thread."""

    def event(self, event: QEvent) -> bool:
        """Execute an _InvokeEvent's callable and store the result."""
        if isinstance(event, _InvokeEvent):
            try:
                event.result_box[0] = event.func(*event.args, **event.kwargs)
            except Exception as e:  # noqa: BLE001
                event.result_box[1] = e
            finally:
                event.result_event.set()
            return True
        return super().event(event)


class MainThreadInvoker:
    """Invokes callables on the Qt main thread from any thread."""

    def __init__(self) -> None:
        """Create the internal QObject receiver that processes invoke events."""
        self._receiver = _Receiver()

    def __call__(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Call func on the Qt main thread, blocking until it returns."""
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)

        result_event = threading.Event()
        result_box: list = [None, None]
        event = _InvokeEvent(func, args, kwargs, result_event, result_box)
        QCoreApplication.postEvent(self._receiver, event)
        result_event.wait()

        if result_box[1] is not None:
            raise result_box[1]
        return result_box[0]


class QtProxy:
    """Wraps a QObject, dispatching all access to the Qt main thread."""

    def __init__(self, target: Any, invoker: MainThreadInvoker) -> None:
        """Bind the proxy to target, using invoker for main-thread dispatch."""
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_invoke", invoker)

    def __getattr__(self, name: str) -> Any:
        invoke = object.__getattribute__(self, "_invoke")
        target = object.__getattribute__(self, "_target")

        attr = invoke(getattr, target, name)
        if callable(attr):

            def caller(*args: Any, **kwargs: Any) -> Any:
                result = invoke(attr, *args, **kwargs)
                if isinstance(result, QObject):
                    return QtProxy(result, invoke)
                return result

            return caller
        return attr

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"QtProxy({target!r})"
