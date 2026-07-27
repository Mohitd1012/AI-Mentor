"""
Cancellation token for in-flight AI responses.

Pattern:
    token = CancellationToken()
    async for chunk in stream(token):
        if token.cancelled: break
    ...
    token.cancel()   # from another coroutine
"""

import asyncio
from typing import Optional


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()

    async def wait(self) -> None:
        """Coroutine that resolves when cancelled."""
        await self._event.wait()
