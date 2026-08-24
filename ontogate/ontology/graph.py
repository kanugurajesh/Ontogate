from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

from .schema import Entity, EntityType, OntologyViolation, Relation, RelationType, RuleFn


class KnowledgeGraph:
    """A small in-memory, typed property graph with pluggable validation
    rules run on every write. This is the "ontology engine": entities and
    relations are grounded, typed, and constrained rather than free-form
    text, so an agent's actions can be validated before they execute."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._out: dict[str, list[Relation]] = defaultdict(list)
        self._in: dict[str, list[Relation]] = defaultdict(list)
        self._rules: list[RuleFn] = []

    def add_rule(self, rule: RuleFn) -> None:
        self._rules.append(rule)

    def add_entity(self, entity: Entity) -> None:
        if entity.id in self._entities:
            raise ValueError(f"entity {entity.id!r} already exists")
        self._entities[entity.id] = entity

    def has_entity(self, entity_id: str) -> bool:
        return entity_id in self._entities

    def get_entity(self, entity_id: str) -> Entity:
        try:
            return self._entities[entity_id]
        except KeyError:
            raise KeyError(f"unknown entity {entity_id!r}") from None

    def add_relation(self, relation: Relation, *, check_rules: bool = True) -> None:
        if relation.source_id not in self._entities:
            raise ValueError(f"unknown source entity {relation.source_id!r}")
        if relation.target_id not in self._entities:
            raise ValueError(f"unknown target entity {relation.target_id!r}")
        if check_rules:
            for rule in self._rules:
                reason = rule(self, relation)
                if reason:
                    raise OntologyViolation(reason)
        self._out[relation.source_id].append(relation)
        self._in[relation.target_id].append(relation)

    def neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        direction: str = "out",
    ) -> list[Entity]:
        rels = self._out[entity_id] if direction == "out" else self._in[entity_id]
        result: list[Entity] = []
        for r in rels:
            if relation_type is not None and r.type != relation_type:
                continue
            other_id = r.target_id if direction == "out" else r.source_id
            result.append(self._entities[other_id])
        return result

    def relations_from(self, entity_id: str, relation_type: RelationType | None = None) -> list[Relation]:
        rels = self._out[entity_id]
        return list(rels) if relation_type is None else [r for r in rels if r.type == relation_type]

    def find_entities(self, type: EntityType | None = None, **attrs: Any) -> list[Entity]:
        out = []
        for e in self._entities.values():
            if type is not None and e.type != type:
                continue
            if all(e.attributes.get(k) == v for k, v in attrs.items()):
                out.append(e)
        return out

    def path_exists(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType | None = None,
        max_depth: int = 10,
    ) -> bool:
        """BFS reachability check - used to detect cycles before an edge
        that should be acyclic (e.g. team membership) is added."""
        if source_id == target_id:
            return True
        seen = {source_id}
        queue: deque[tuple[str, int]] = deque([(source_id, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for r in self._out[node]:
                if relation_type is not None and r.type != relation_type:
                    continue
                if r.target_id == target_id:
                    return True
                if r.target_id not in seen:
                    seen.add(r.target_id)
                    queue.append((r.target_id, depth + 1))
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [
                {"id": e.id, "type": e.type.value, "attributes": e.attributes}
                for e in self._entities.values()
            ],
            "relations": [
                {
                    "source_id": r.source_id,
                    "type": r.type.value,
                    "target_id": r.target_id,
                    "attributes": r.attributes,
                }
                for rels in self._out.values()
                for r in rels
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
