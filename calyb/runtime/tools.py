from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..ontology.graph import KnowledgeGraph
from ..ontology.schema import Entity, EntityType, OntologyViolation, Relation, RelationType
from ..ontology.seed_data import knowledge_base_search


class ToolError(Exception):
    """A tool call failed. Retryable by default."""


class PermanentToolError(ToolError):
    """A tool failure that retrying will never fix - e.g. an ontology/policy
    guardrail rejection. The orchestrator does not retry these."""


@dataclass
class ToolSpec:
    name: str
    fn: Callable[..., Awaitable[Any]]
    idempotent: bool
    description: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, idempotent: bool, description: str):
        def decorator(fn):
            self._tools[name] = ToolSpec(name, fn, idempotent, description)
            return fn

        return decorator

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolError(f"unknown tool {name!r}")
        return self._tools[name]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "idempotent": t.idempotent, "description": t.description}
            for t in self._tools.values()
        ]


def build_tool_registry(graph: KnowledgeGraph, *, failure_rate: float = 0.0) -> ToolRegistry:
    """Wires the tool registry to mock enterprise-system APIs that act on a
    real KnowledgeGraph. `failure_rate` injects simulated transient
    failures so retry/circuit-breaker/cache behavior is actually exercised
    in the demo, not just theoretical."""
    registry = ToolRegistry()

    async def _flaky(latency: float = 0.05) -> None:
        await asyncio.sleep(latency)
        if random.random() < failure_rate:
            raise ToolError("transient upstream error - please retry")

    @registry.register("lookup_user", idempotent=True, description="Look up a user and their roles/teams/access by id.")
    async def lookup_user(user_id: str) -> dict[str, Any]:
        await _flaky()
        entity = graph.get_entity(user_id)
        roles = [r.id for r in graph.neighbors(user_id, RelationType.HAS_ROLE)]
        teams = [t.id for t in graph.neighbors(user_id, RelationType.MEMBER_OF)]
        access = [s.id for s in graph.neighbors(user_id, RelationType.GRANTS_ACCESS_TO)]
        return {"id": entity.id, "name": entity.attributes.get("name"), "roles": roles, "teams": teams, "system_access": access}

    @registry.register("search_knowledge_base", idempotent=True, description="Search internal KB articles by keyword.")
    async def search_knowledge_base(query: str) -> dict[str, Any]:
        await _flaky()
        return {"query": query, "results": knowledge_base_search(query)}

    @registry.register("check_policy", idempotent=True, description="List the policies/required roles governing a system.")
    async def check_policy(system_id: str) -> dict[str, Any]:
        await _flaky()
        policies = graph.neighbors(system_id, RelationType.GOVERNS, direction="in")
        out = [
            {"policy": p.id, "requires_any_role": [r.id for r in graph.neighbors(p.id, RelationType.REQUIRES_ROLE)]}
            for p in policies
        ]
        return {"system": system_id, "policies": out}

    @registry.register("assign_role", idempotent=True, description="Assign a role to a user (idempotent).")
    async def assign_role(user_id: str, role_id: str) -> dict[str, Any]:
        await _flaky()
        if not graph.has_entity(role_id):
            raise PermanentToolError(f"unknown role {role_id!r}")
        existing = {r.id for r in graph.neighbors(user_id, RelationType.HAS_ROLE)}
        if role_id not in existing:
            graph.add_relation(Relation(user_id, RelationType.HAS_ROLE, role_id))
        return {"user": user_id, "role": role_id, "granted": True}

    @registry.register("join_team", idempotent=True, description="Add a user to a team (idempotent).")
    async def join_team(user_id: str, team_id: str) -> dict[str, Any]:
        await _flaky()
        existing = {t.id for t in graph.neighbors(user_id, RelationType.MEMBER_OF)}
        if team_id not in existing:
            graph.add_relation(Relation(user_id, RelationType.MEMBER_OF, team_id))
        return {"user": user_id, "team": team_id, "joined": True}

    @registry.register(
        "grant_access",
        idempotent=True,
        description="Grant a user access to a system. Enforced by the ontology's policy rules.",
    )
    async def grant_access(user_id: str, system_id: str) -> dict[str, Any]:
        await _flaky()
        existing = {s.id for s in graph.neighbors(user_id, RelationType.GRANTS_ACCESS_TO)}
        if system_id in existing:
            return {"user": user_id, "system": system_id, "granted": True, "already_had_access": True}
        try:
            graph.add_relation(Relation(user_id, RelationType.GRANTS_ACCESS_TO, system_id))
        except OntologyViolation as exc:
            raise PermanentToolError(f"access denied by ontology: {exc}") from exc
        return {"user": user_id, "system": system_id, "granted": True, "already_had_access": False}

    @registry.register("create_ticket", idempotent=False, description="File a new support ticket.")
    async def create_ticket(subject: str, description: str, filed_by: str) -> dict[str, Any]:
        await _flaky()
        ticket_id = f"ticket:t{random.randint(1000, 9999)}"
        graph.add_entity(Entity(ticket_id, EntityType.TICKET, {"subject": subject, "description": description, "status": "open"}))
        graph.add_relation(Relation(ticket_id, RelationType.FILED_BY, filed_by))
        return {"ticket_id": ticket_id, "subject": subject, "status": "open"}

    @registry.register("notify_user", idempotent=False, description="Send a notification message to a user.")
    async def notify_user(user_id: str, message: str) -> dict[str, Any]:
        await _flaky()
        return {"user": user_id, "message": message, "delivered": True}

    return registry
