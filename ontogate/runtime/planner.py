from __future__ import annotations

import json
import os
from typing import Any

from ..ontology.graph import KnowledgeGraph
from ..ontology.schema import EntityType
from .dag import DAGValidationError, Plan, Step
from .memory import Memory
from .tools import ToolRegistry


class PlannerError(Exception):
    pass


ROLE_KEYWORDS = {
    "software engineer": "role:engineer",
    "engineer": "role:engineer",
    "data analyst": "role:data_analyst",
    "analyst": "role:data_analyst",
    "manager": "role:manager",
    "administrator": "role:admin",
    "admin": "role:admin",
}
TEAM_KEYWORDS = {"platform": "team:platform", "data": "team:data", "sales": "team:sales"}
SYSTEM_KEYWORDS = {
    "data warehouse": "system:data_warehouse",
    "warehouse": "system:data_warehouse",
    "github": "system:github",
    "vpn": "system:vpn",
    "billing": "system:billing",
    "crm": "system:crm",
}
SYSTEMS_BY_ROLE = {
    "role:engineer": ["system:github", "system:vpn"],
    "role:admin": ["system:github", "system:vpn", "system:billing", "system:data_warehouse"],
    "role:manager": ["system:billing"],
    "role:data_analyst": ["system:data_warehouse"],
}


class RuleBasedPlanner:
    """Deterministic, dependency-free fallback planner. It pattern-matches
    a handful of canned enterprise-workflow phrasings ("onboard...",
    "investigate access...", "grant access...") into a validated DAG
    grounded in real ontology entities. No network access and no API key,
    which is what keeps the test suite and `ontogate demo` fully
    reproducible."""

    def __init__(self, graph: KnowledgeGraph, tools: ToolRegistry, memory: Memory | None = None) -> None:
        self.graph = graph
        self.tools = tools
        self.memory = memory

    def plan(self, task: str) -> Plan:
        text = task.lower()
        user_id = self._find_user(text)
        if user_id is None:
            raise PlannerError(f"could not find a known user mentioned in task: {task!r}")

        if "onboard" in text:
            return self._plan_onboarding(task, user_id, text)
        if "investigate" in text or "can't access" in text or "cannot access" in text or "ticket" in text:
            return self._plan_investigation(task, user_id, text)
        if "grant" in text or "access to" in text or "give" in text:
            return self._plan_direct_grant(task, user_id, text)
        raise PlannerError(
            f"RuleBasedPlanner could not classify task: {task!r} "
            "(try phrasing with 'onboard', 'investigate access', or 'grant access'; or pass --planner llm)"
        )

    def _find_user(self, text: str) -> str | None:
        for entity in self.graph.find_entities(type=EntityType.USER):
            name = entity.attributes.get("name", "")
            first_name = name.split()[0].lower() if name else ""
            if first_name and first_name in text:
                return entity.id
            if entity.id.split(":")[-1] in text:
                return entity.id
        return None

    def _find_role(self, text: str) -> str | None:
        for kw, role_id in sorted(ROLE_KEYWORDS.items(), key=lambda x: -len(x[0])):
            if kw in text:
                return role_id
        return None

    def _find_team(self, text: str) -> str | None:
        for kw, team_id in TEAM_KEYWORDS.items():
            if kw in text:
                return team_id
        return None

    def _find_system(self, text: str) -> str | None:
        for kw, sys_id in sorted(SYSTEM_KEYWORDS.items(), key=lambda x: -len(x[0])):
            if kw in text:
                return sys_id
        return None

    def _plan_onboarding(self, task: str, user_id: str, text: str) -> Plan:
        role_id = self._find_role(text) or "role:engineer"
        team_id = self._find_team(text) or "team:platform"
        systems = SYSTEMS_BY_ROLE.get(role_id, [])

        steps = [
            Step("lookup", "lookup_user", {"user_id": user_id}),
            Step("assign_role", "assign_role", {"user_id": user_id, "role_id": role_id}, depends_on=["lookup"]),
            Step("join_team", "join_team", {"user_id": user_id, "team_id": team_id}, depends_on=["lookup"]),
        ]
        grant_ids = []
        for i, sys_id in enumerate(systems):
            sid = f"grant_{i}"
            steps.append(Step(sid, "grant_access", {"user_id": user_id, "system_id": sys_id}, depends_on=["assign_role"]))
            grant_ids.append(sid)
        steps.append(
            Step(
                "notify",
                "notify_user",
                {"user_id": user_id, "message": f"Welcome! You've been onboarded as {role_id} on {team_id}."},
                depends_on=grant_ids or ["assign_role", "join_team"],
            )
        )
        return Plan.from_steps(task, steps)

    def _plan_investigation(self, task: str, user_id: str, text: str) -> Plan:
        system_id = self._find_system(text) or "system:data_warehouse"
        steps = [
            Step("lookup", "lookup_user", {"user_id": user_id}),
            Step("policy", "check_policy", {"system_id": system_id}),
            Step("kb", "search_knowledge_base", {"query": task}),
            Step("grant", "grant_access", {"user_id": user_id, "system_id": system_id}, depends_on=["lookup", "policy"]),
            Step(
                "notify",
                "notify_user",
                {"user_id": user_id, "message": f"Access to {system_id} has been resolved."},
                depends_on=["grant"],
            ),
        ]
        return Plan.from_steps(task, steps)

    def _plan_direct_grant(self, task: str, user_id: str, text: str) -> Plan:
        system_id = self._find_system(text)
        if system_id is None:
            raise PlannerError(f"could not find a known system mentioned in task: {task!r}")
        steps = [
            Step("lookup", "lookup_user", {"user_id": user_id}),
            Step("policy", "check_policy", {"system_id": system_id}),
            Step("grant", "grant_access", {"user_id": user_id, "system_id": system_id}, depends_on=["lookup", "policy"]),
            Step(
                "notify",
                "notify_user",
                {"user_id": user_id, "message": f"You now have access to {system_id}."},
                depends_on=["grant"],
            ),
        ]
        return Plan.from_steps(task, steps)


_PLANNER_INSTRUCTIONS = """You are the planning module of an enterprise workflow agent runtime.
Decompose the user's task into a JSON object: {"steps": [...]} where each
step is {"id": str, "tool": str, "args": {...}, "depends_on": [str, ...]}.

Rules:
- Only use tools from this list: __TOOLS__
- Reference another step's output with the placeholder "$steps.<id>.output.<field>"
  and declare that step's id in depends_on.
- Steps with no dependency on each other should be left independent so they
  run in parallel - keep the DAG as shallow as possible.
- Ground every user_id/system_id/role_id/team_id argument in the ontology
  snapshot below; never invent an id that isn't listed.

Ontology snapshot:
__ONTOLOGY__

Relevant past runs (context only, do not copy blindly):
__MEMORY__
"""


class LLMPlanner:
    """Plans via an LLM (OpenAI Chat Completions), constrained to a JSON DAG
    schema and grounded in the live ontology + tool registry, with one
    self-correction retry if the model's plan fails DAG validation."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        tools: ToolRegistry,
        memory: Memory | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.graph = graph
        self.tools = tools
        self.memory = memory
        self.model = model

    def plan(self, task: str) -> Plan:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise PlannerError("LLMPlanner requires the 'openai' package: pip install openai") from exc

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PlannerError("OPENAI_API_KEY is not set; use --planner rule instead")

        client = OpenAI(api_key=api_key)
        system_prompt = (
            _PLANNER_INSTRUCTIONS.replace("__TOOLS__", json.dumps(self.tools.describe()))
            .replace("__ONTOLOGY__", self._ontology_snapshot())
            .replace("__MEMORY__", self._memory_snapshot(task))
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        last_error: Exception | None = None
        for _ in range(2):
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = response.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
                steps = [
                    Step(id=s["id"], tool=s["tool"], args=s.get("args", {}), depends_on=s.get("depends_on", []))
                    for s in data["steps"]
                ]
                return Plan.from_steps(task, steps)
            except (KeyError, TypeError, json.JSONDecodeError, DAGValidationError) as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"That plan was invalid: {exc}. Return corrected JSON only."})
        raise PlannerError(f"LLM failed to produce a valid plan after retries: {last_error}")

    def _ontology_snapshot(self) -> str:
        return "\n".join(f"- {e.id} ({e.type.value}): {e.attributes}" for e in self.graph.find_entities())

    def _memory_snapshot(self, task: str) -> str:
        if self.memory is None:
            return "(none)"
        similar = self.memory.recall_similar(task)
        if not similar:
            return "(none)"
        return "\n".join(f"- {m['task']} -> {m['outcome']}" for m in similar)


def get_planner(name: str, graph: KnowledgeGraph, tools: ToolRegistry, memory: Memory | None = None) -> Any:
    if name == "auto":
        name = "llm" if os.environ.get("OPENAI_API_KEY") else "rule"
    if name == "rule":
        return RuleBasedPlanner(graph, tools, memory)
    if name == "llm":
        return LLMPlanner(graph, tools, memory)
    raise PlannerError(f"unknown planner {name!r}")
