"""In-memory cache for a single simulation round. Flushed to DB at round end."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=False)
class RoundCache:
    """Mutable per-round cache for a single simulation round.

    Intentionally NOT frozen: entries are accumulated during the round and
    flushed to the database at round end.  This is the only mutable dataclass
    in the codebase — justified because a round cache is inherently transient
    write-accumulator state that would be awkward to model immutably.
    """

    _agents: dict[str, dict] = field(default_factory=dict)
    _trusts: dict[tuple[str, str], float] = field(default_factory=dict)
    _write_queue: list[tuple[str, tuple]] = field(default_factory=list)

    def set_agent(self, agent_id: str, data: dict) -> None:
        self._agents[agent_id] = data

    def get_agent(self, agent_id: str) -> dict | None:
        return self._agents.get(agent_id)

    def bulk_load_agents(self, agents: dict[str, dict]) -> None:
        self._agents = agents

    def set_trust(self, pair: tuple[str, str], score: float) -> None:
        self._trusts[pair] = score

    def get_trust(self, pair: tuple[str, str], default: float = 0.0) -> float:
        return self._trusts.get(pair, default)

    def bulk_load_trusts(self, trusts: dict[tuple[str, str], float]) -> None:
        self._trusts = trusts

    def queue_write(self, sql: str, params: tuple) -> None:
        self._write_queue.append((sql, params))

    def flush_writes(self) -> list[tuple[str, tuple]]:
        writes = list(self._write_queue)
        self._write_queue.clear()
        return writes

    def clear(self) -> None:
        self._agents.clear()
        self._trusts.clear()
        self._write_queue.clear()
