"""Scheduler for parallel node execution management."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from ari.config import BFTSConfig
from ari.orchestrator.node import Node


@dataclass
class SchedulerStats:
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    currently_running: int = 0


class Scheduler:
    def __init__(self, config: BFTSConfig) -> None:
        self.config = config
        self.max_parallel = config.max_parallel_nodes
        self._pending: list[Node] = []
        self._completed: list[Node] = []
        self.stats = SchedulerStats()

    def submit(self, node: Node) -> None:
        """Submit a node for execution."""
        self._pending.append(node)
        self.stats.total_submitted += 1

    async def run_all(
        self,
        execute_fn: Callable[[Node], Node],
    ) -> list[Node]:
        """Run all pending nodes with concurrency limits."""
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def _run_node(node: Node) -> Node:
            async with semaphore:
                self.stats.currently_running += 1
                node.mark_running()
                try:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, execute_fn, node)
                    self.stats.total_completed += 1
                    return result
                except Exception as e:
                    node.mark_failed(error_log=str(e))
                    self.stats.total_failed += 1
                    return node
                finally:
                    self.stats.currently_running -= 1

        tasks = [asyncio.create_task(_run_node(node)) for node in self._pending]
        results = await asyncio.gather(*tasks)
        self._completed.extend(results)
        self._pending.clear()
        return list(results)

    def get_pending(self) -> list[Node]:
        return list(self._pending)

    def get_completed(self) -> list[Node]:
        return list(self._completed)
