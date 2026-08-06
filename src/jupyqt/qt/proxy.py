"""Qt proxy layer for cross-thread access from kernel to Qt main thread."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, SignalInstance

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


def unwrap(obj: Any) -> Any:
    """Return the object a QtProxy stands for, or obj itself if not proxied."""
    if isinstance(obj, QtProxy):
        return object.__getattribute__(obj, "_target")
    return obj


def _wrap(value: Any, invoke: MainThreadInvoker) -> Any:
    """Proxy a QObject, recursing into the containers Qt methods commonly return."""
    if isinstance(value, QObject):
        return QtProxy(value, invoke)
    if isinstance(value, (list, tuple, set)):
        return type(value)(_wrap(v, invoke) for v in value)
    if isinstance(value, dict):
        return {k: _wrap(v, invoke) for k, v in value.items()}
    return value


class QtProxy:
    """Wraps a QObject, dispatching all access to the Qt main thread.

    QObjects reachable through the proxy are proxied in turn, including those
    returned inside a list, tuple, set or dict — `app.topLevelWidgets()[0]` is
    otherwise a raw widget, and calling it from the kernel thread aborts the
    process.

    Only attribute access is marshaled: dunder protocols (`len(obj)`, `obj[i]`)
    reach the target directly and are not thread-safe.
    """

    def __init__(self, target: Any, invoker: MainThreadInvoker) -> None:
        """Bind the proxy to target, using invoker for main-thread dispatch."""
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_invoke", invoker)

    def __getattr__(self, name: str) -> Any:
        invoke = object.__getattribute__(self, "_invoke")
        target = object.__getattribute__(self, "_target")

        attr = invoke(getattr, target, name)
        if isinstance(attr, SignalInstance):
            return attr  # callable, but Qt already marshals queued connections
        if callable(attr):

            def caller(*args: Any, **kwargs: Any) -> Any:
                args = tuple(unwrap(a) for a in args)
                kwargs = {k: unwrap(v) for k, v in kwargs.items()}
                return _wrap(invoke(attr, *args, **kwargs), invoke)

            return caller
        return _wrap(attr, invoke)

    def __setattr__(self, name: str, value: Any) -> None:
        """Assign on the target from the main thread, not on the proxy itself."""
        invoke = object.__getattribute__(self, "_invoke")
        target = object.__getattribute__(self, "_target")
        invoke(setattr, target, name, unwrap(value))

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"QtProxy({target!r})"
