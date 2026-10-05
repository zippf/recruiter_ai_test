import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import BackgroundTasks


def schedule_background_task(
    background_tasks: BackgroundTasks,
    task: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Keep FastAPI's existing post-response task behavior behind one adapter."""
    background_tasks.add_task(task, *args, **kwargs)


def schedule_async_task(awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
    return asyncio.create_task(awaitable)
