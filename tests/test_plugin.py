from __future__ import annotations

import anyio

from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.server.plugin import JupyQtKernel


def test_kernel_start_and_kernel_info(shell):
    async def main():
        kernel = JupyQtKernel(shell)
        async with anyio.create_task_group() as tg:
            await tg.start(kernel.start)
            msg = create_message("kernel_info_request")
            await kernel.shell_stream.send(serialize_message(msg, kernel.key))
            reply_raw = await kernel.shell_stream.receive()
            _, parts = feed_identities(reply_raw)
            reply = deserialize_message(parts)
            assert reply["msg_type"] == "kernel_info_reply"
            await kernel.stop()
            tg.cancel_scope.cancel()

    anyio.run(main)


def test_kernel_execute_cell(shell):
    async def main():
        kernel = JupyQtKernel(shell)
        async with anyio.create_task_group() as tg:
            await tg.start(kernel.start)
            msg = create_message("execute_request", content={
                "code": "result = 6 * 7",
                "silent": False,
                "store_history": True,
                "allow_stdin": False,
                "stop_on_error": True,
            })
            await kernel.shell_stream.send(serialize_message(msg, kernel.key))
            reply_raw = await kernel.shell_stream.receive()
            _, parts = feed_identities(reply_raw)
            reply = deserialize_message(parts)
            assert reply["content"]["status"] == "ok"
            assert shell.user_ns["result"] == 42
            await kernel.stop()
            tg.cancel_scope.cancel()

    anyio.run(main)
