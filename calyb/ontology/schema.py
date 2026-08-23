from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EntityType(str, Enum):
    USER = "USER"
    ROLE = "ROLE"
    TEAM = "TEAM"
    SYSTEM = "SYSTEM"
    POLICY = "POLICY"
    TICKET = "TICKET"


class RelationType(str, Enum):
    HAS_ROLE = "HAS_ROLE"                # USER -> ROLE
    MEMBER_OF = "MEMBER_OF"              # USER -> TEAM
    GRANTS_ACCESS_TO = "GRANTS_ACCESS_TO"  # USER -> SYSTEM
    REQUIRES_ROLE = "REQUIRES_ROLE"      # POLICY -> ROLE
    GOVERNS = "GOVERNS"                  # POLICY -> SYSTEM
    ASSIGNED_TO = "ASSIGNED_TO"          # TICKET -> USER
    FILED_BY = "FILED_BY"                # TICKET -> USER
    BLOCKS = "BLOCKS"                    # TICKET -> TICKET


@dataclass(frozen=True)
class Entity:
    id: str
    type: EntityType
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Relation:
    source_id: str
    type: RelationType
    target_id: str
    attributes: dict[str, Any] = field(default_factory=dict)


class OntologyViolation(Exception):
    """Raised when adding a relation would violate an ontology rule
    (a type constraint, a structural invariant, or a policy)."""


# A rule inspects the graph-in-progress and a candidate relation, returning
# None if the relation is acceptable or a human-readable reason if not.
# Typed as Any (not KnowledgeGraph) to avoid a schema<->graph import cycle.
RuleFn = Callable[[Any, Relation], "str | None"]
