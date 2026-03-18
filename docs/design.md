# jupyqt — Embed JupyterLab in PySide6 Applications

**Date:** 2026-03-18
**Status:** Draft

## Problem

Embedding an IPython kernel inside a Qt application is fragile. SciQLop currently uses ipykernel in-process on the Qt main thread, with a QTimer-based poller calling `do_one_iteration()` through qasync. This creates:

- **Reentrancy crashes:** Any `processEvents()` call in user code can re-trigger the kernel poller via qasync.
- **UI freezes:** Long-running cells block the Qt main thread.
- **Accumulating workarounds:** `pause_kernel_poller()`, qasync monkey-patches, two-phase shutdown, ipykernel version pins.
- **Tight coupling to ipykernel/ZMQ internals** that break across versions.

## Solution

A standalone Python package (`jupyqt`) that provides a clean, batteries-included way to embed JupyterLab in any PySide6 application. No ZMQ, no ipykernel, no qasync.

### Key design decisions

1. **Background-thread kernel** — The IPython shell runs on a dedicated thread with its own asyncio event loop. The Qt main thread is never blocked by cell execution.
2. **IPython InteractiveShell, not ipykernel** — Use IPython's core `InteractiveShell` directly. Implement the Jupyter wire protocol ourselves over anyio memory streams.
3. **jupyverse as the Jupyter server** — Replaces jupyter-server. Connects to the kernel via memory streams (no ZMQ). Serves JupyterLab over HTTP/WebSocket.
4. **Qt proxy layer** — Notebook code accesses Qt objects through proxy objects that marshal calls to the main thread.
5. **JupyterLab widget** — A QWebEngineView embedding JupyterLab, plus external browser option.

## Architecture

```
+-------------------------------------+
|  JupyterLabWidget (QWebEngineView)  |  <- Qt main thread
+---------------+---------------------+
                | HTTP/WebSocket
+---------------+---------------------+
|  jupyverse (uvicorn + FastAPI)      |  <- background thread
+---------------+---------------------+
                | anyio MemoryObjectStreams
+---------------+---------------------+
|  Wire Protocol (protocol.py)        |
|  InteractiveShell (IPython core)    |  <- kernel thread
+---------------+---------------------+
                | QtProxy (blocking invoke)
+---------------+---------------------+
|  Host Qt Application                |  <- Qt main thread
+-------------------------------------+
```

### Threads

| Thread | Owns | Event loop |
|--------|------|------------|
| Qt main thread | QApplication, all widgets, JupyterLabWidget | Qt event loop |
| Kernel thread | InteractiveShell, wire protocol dispatcher | asyncio event loop |
| Server thread | jupyverse (uvicorn) | asyncio/uvloop |

The kernel's async message dispatch runs within jupyverse's anyio task group (since `Kernel.start()` is called there), so the kernel and server share the same async context. The `InteractiveShell.run_cell()` calls are synchronous and run in the kernel thread's context — the async dispatch awaits them via `anyio.to_thread.run_sync()` or similar.

## Package Structure

```
jupyqt/
    kernel/
        shell.py        # InteractiveShell setup & configuration
        protocol.py     # Jupyter wire protocol message handling
        thread.py       # KernelThread — background thread + asyncio loop
    server/
        plugin.py       # jupyverse kernel plugin (memory streams)
        launcher.py     # jupyverse server lifecycle
    qt/
        proxy.py        # QtProxy for cross-thread Qt access
        widget.py       # JupyterLabWidget (QWebEngineView)
    api.py              # Public API entry point
```

## Components

### 1. Public API (`api.py`)

Single entry point for host applications.

```python
class EmbeddedJupyter:
    def __init__(self, parent: QWidget = None): ...

    @property
    def shell(self) -> InteractiveShell:
        """Full IPython shell for registering magics, completions, etc."""

    def push(self, variables: dict):
        """Thread-safe variable injection into the kernel namespace."""

    def wrap_qt(self, obj) -> QtProxy:
        """Wrap a QObject for safe access from notebook cells."""

    def widget(self) -> JupyterLabWidget:
        """QWebEngineView embedding JupyterLab."""

    def open_in_browser(self):
        """Open JupyterLab in the default browser."""

    def start(self, port: int = 0):
        """Start kernel thread + jupyverse server."""

    def shutdown(self):
        """Stop everything cleanly."""
```

- `shell` is accessible before `start()` for registering magics and pushing initial variables.
- After `start()`, use `push()` for thread-safe variable injection.
- The host app registers its own magics and completers directly on `shell`.

### 2. Kernel Thread (`kernel/thread.py`)

Background thread owning the `InteractiveShell` and the wire protocol dispatcher.

**Shell instantiation:** The `InteractiveShell` is created eagerly in `EmbeddedJupyter.__init__()` on the main thread. This allows the host app to register magics, completers, and push initial variables before `start()`. Once `start()` is called, all shell interaction moves to the kernel thread — the shell is "handed off." After `start()`, direct shell access from the main thread is not safe; use `push()` instead.

Lifecycle:
1. **Construction:** Creates the `InteractiveShell` on the main thread. Creates the background thread (not started).
2. **Pre-start:** Shell is directly accessible for setup (magics, variables, config) — all on the main thread.
3. **`start()`:** Starts the background thread. From this point, the shell belongs to the kernel thread.
4. **Running:** Processes messages from jupyverse via memory streams, executes cells on the kernel thread.
5. **`shutdown()`:** Cancels async tasks, stops the event loop, joins the thread.

Thread-safe `push()` posts to the kernel thread's event loop via `loop.call_soon_threadsafe()`.

### 3. Shell Setup (`kernel/shell.py`)

Creates and configures `InteractiveShell.instance()`:
- stdout/stderr capture: custom streams routing output to the iopub channel.
- Display publisher: hooks into IPython's `display_pub` for `display_data` and `execute_result` messages.
- Configurable options: colors, autocall, history, etc.

Does NOT use `IPKernelApp` or any ipykernel machinery.

### 4. Wire Protocol (`kernel/protocol.py`)

Server-side Jupyter messaging protocol over anyio memory streams.

**Serialization layer:** Jupyverse's `Kernel` ABC exchanges messages as `list[bytes]` (the standard Jupyter wire format: identities, delimiter, HMAC signature, JSON-encoded header/parent_header/metadata/content, and optional binary buffers). The protocol layer must deserialize incoming `list[bytes]` into structured messages (using `feed_identities()` + `deserialize_message()` from jupyverse's `fps_kernels.kernel_driver.message` or our own implementation), dispatch to handlers, and serialize replies back to `list[bytes]` with HMAC signing. Even though there's no ZMQ network transport, the wire format and signing are required by jupyverse's `KernelServer`.

**Channels (anyio streams, `list[bytes]` wire format):**
- `shell` — `StapledObjectStream`: request/reply for execution, completion, inspection
- `control` — `StapledObjectStream`: shutdown, interrupt
- `iopub` — send-only from kernel's perspective (`MemoryObjectSendStream`): stdout, stderr, results, errors, status. The kernel publishes via the internal send stream; jupyverse's `KernelServer` reads from the corresponding receive stream to broadcast to WebSocket clients.
- `stdin` — `StapledObjectStream`: for Python's `input()` in cells

**Message types by implementation phase:**

Phase 1 — Minimum viable kernel:
- `kernel_info_request` — static response
- `execute_request` — `shell.run_cell()`, capture output, handle errors
- `status` (iopub) — busy/idle around execution
- `stream` (iopub) — stdout/stderr
- `execute_result` / `display_data` (iopub) — rich output
- `error` (iopub) — formatted tracebacks
- `shutdown_request` — signal kernel to stop

Phase 2 — Full interactive experience:
- `complete_request` — `shell.complete()`
- `inspect_request` — `shell.object_inspect()`
- `is_complete_request` — multiline input detection
- `history_request` — history search
- `input_request` / `input_reply` — `input()` support
- `interrupt_request` — raise `KeyboardInterrupt` in the kernel thread via `signal.pthread_kill()` (Linux/macOS) or `ctypes.pythonapi.PyThreadState_SetAsyncExc()` (cross-platform fallback)

Phase 3 — Widgets and comms:
- `comm_info_request`, `comm_open`, `comm_msg`, `comm_close`

**Message dispatch:**
```python
async def dispatch_shell(self, channel):
    async for raw_msg in channel:  # list[bytes]
        msg = deserialize_message(raw_msg)
        handler = self._handlers[msg["header"]["msg_type"]]
        await self._publish_status("busy", msg)
        # Handlers may publish multiple iopub messages (stream, display_data, etc.)
        # before returning the shell reply
        reply = await handler(msg)
        await channel.send(serialize_message(reply))
        await self._publish_status("idle", msg)
```

### 5. Jupyverse Kernel Integration (`server/plugin.py`)

A subclass of jupyverse's `Kernel` ABC, provided to jupyverse via a custom `KernelFactory`. The factory is registered with jupyverse's `_Kernels` router via `register_kernel_factory()` (or as the `DefaultKernelFactory`).

The `Kernel` subclass:
- Owns the anyio MemoryObjectStreams for all four channels (created by the ABC).
- In its `start()` method (called within jupyverse's anyio task group): wires the stream endpoints to the wire protocol dispatcher, which runs as async tasks in the same task group.
- Reports kernel as always alive — refuses restart/shutdown from JupyterLab.
- Provides kernel info (language, display name, version).

The `KernelFactory`:
- Creates instances of our `Kernel` subclass on demand.
- Ensures all kernel instances share the single `InteractiveShell` (one kernel per app).

### 6. Server Launcher (`server/launcher.py`)

Manages jupyverse lifecycle:
- Starts jupyverse with uvicorn in a background thread.
- Configures plugins: kernel plugin + jupyterlab frontend plugin.
- Picks a free port (or uses specified one).
- Generates auth token for JupyterLab access.
- Provides URL: `http://localhost:{port}/lab?token={token}`.
- Stops uvicorn cleanly on shutdown.

### 7. Qt Proxy (`qt/proxy.py`)

Enables notebook code (kernel thread) to call Qt APIs (main thread).

```python
class QtProxy:
    def __init__(self, target, invoker):
        self._target = target
        self._invoke = invoker

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if callable(attr):
            def caller(*args, **kwargs):
                return self._invoke(attr, *args, **kwargs)
            return caller
        # Non-callable attributes also marshaled to main thread for thread safety
        return self._invoke(getattr, self._target, name)
```

**Invoker:** Posts a callable to the Qt main thread using a custom `QEvent` + `QCoreApplication.postEvent()`. A `threading.Event` blocks the kernel thread until the main thread processes the call. All attribute access (reads and calls) is marshaled — Qt objects are not thread-safe even for reads.

**Return values:** Primitives returned directly. QObject results automatically wrapped in a new `QtProxy`.

### 8. JupyterLab Widget (`qt/widget.py`)

`QWebEngineView` displaying JupyterLab:
- Isolated `QWebEngineProfile`.
- Navigates to jupyverse URL once server is ready.
- "Loading..." placeholder until JupyterLab loads.
- `ready` signal when loaded.
- `open_in_browser()` via `QDesktopServices.openUrl()`.

## Dependencies

- `IPython` — core interactive shell
- `jupyverse` — Jupyter server (with jupyterlab frontend plugin)
- `anyio` — async streams for kernel-server communication
- `PySide6` — Qt bindings (with WebEngine)
- `uvicorn` — ASGI server for jupyverse

**Not needed:** `ipykernel`, `pyzmq`, `qasync`, `tornado`, `jupyter-server`, `jupyter-client`.

## Integration with SciQLop

When jupyqt is ready, SciQLop replaces its current kernel stack:

**Deleted from SciQLop:**
- `SciQLop/components/jupyter/kernel/__init__.py` — `InternalIPKernel`, `SciQLopKernel`, `SciQLopKernelApp`, `_KernelPoller`
- `SciQLop/components/jupyter/kernel/manager.py` — `KernelManager`, `pause_kernel_poller()`
- `SciQLop/Jupyter/lab_kernel_manager.py` — `SciQLopProvisioner`, `ExternalMappingKernelManager`
- qasync monkey-patches for infinite timers
- `ipykernel` and `pyzmq` dependencies

**New SciQLop integration:**
```python
from jupyqt import EmbeddedJupyter

jupyter = EmbeddedJupyter()
register_sciqlop_magics(jupyter.shell)
jupyter.push({"main_window": jupyter.wrap_qt(main_window)})
jupyter.start()
dock.addWidget(jupyter.widget())
```

## Testing Strategy

**Unit tests (no Qt):**
- Wire protocol message handling — feed messages, verify replies.
- Shell setup — verify InteractiveShell configuration.

**Integration tests (Qt required):**
- `EmbeddedJupyter` lifecycle: start, execute cell, verify output, shutdown.
- `push()` thread safety.
- QtProxy: verify calls execute on main thread.
- Server: verify jupyverse starts and serves JupyterLab.

**Smoke test:**
- Minimal PySide6 app with embedded JupyterLab, run a cell, verify output.

## Out of Scope (v1)

- Concurrent cell execution
- Signal/slot connections from notebook code via proxy
- Async Qt operations (returning futures from proxy)
- ipywidgets / comm support (Phase 3)
- Multiple kernels
- Custom JupyterLab extensions bundling
