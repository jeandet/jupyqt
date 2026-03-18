"""Manages jupyverse server lifecycle in a background thread."""

from __future__ import annotations

import asyncio
import secrets
import socket
import threading
from typing import Any

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.thread import KernelThread


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _build_config(port: int) -> dict[str, Any]:
    """Build the fps config dict for jupyverse with our kernel module."""
    from importlib.metadata import entry_points

    jupyverse_modules = {
        ep.name: {"type": ep.value}
        for ep in entry_points(group="jupyverse.modules")
        # We replace kernel_subprocess with our in-process kernel
        if ep.name != "kernel_subprocess"
    }
    jupyverse_modules["jupyqt_kernel"] = {
        "type": "jupyqt.server.plugin:JupyQtKernelModule",
    }
    return {
        "jupyverse": {
            "type": "jupyverse_api.main:JupyverseModule",
            "config": {
                "host": "127.0.0.1",
                "port": port,
            },
            "modules": jupyverse_modules,
        }
    }


class ServerLauncher:
    """Starts and stops a jupyverse server in a background thread."""

    def __init__(
        self,
        shell: InteractiveShell,
        kernel_thread: KernelThread | None = None,
        port: int = 0,
        token: str | None = None,
    ) -> None:
        self._shell = shell
        self._kernel_thread = kernel_thread
        self._port = port if port != 0 else _find_free_port()
        self._token = token or secrets.token_hex(16)
        self._thread: threading.Thread | None = None
        self._root_module: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}/lab?token={self._token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-server")
        self._thread.start()
        self._started.wait(timeout=30)

    def stop(self) -> None:
        if self._root_module is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._root_module._exit.set)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self) -> None:
        """Start jupyverse via fps. Runs in the server thread."""
        from jupyqt.server.plugin import JupyQtKernelModule

        JupyQtKernelModule.set_shell(self._shell, self._kernel_thread)

        import fps

        config = _build_config(self._port)
        self._root_module = fps.get_root_module(config)
        # Increase timeouts — jupyverse has many modules to prepare
        self._root_module._prepare_timeout = 30
        self._root_module._start_timeout = 30

        # Run the module, signalling _started once the event loop is up
        import anyio

        async def _main() -> None:
            self._loop = asyncio.get_running_loop()
            async with self._root_module:
                self._started.set()
                await self._root_module._exit.wait()

        anyio.run(_main)
