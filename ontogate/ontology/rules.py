from __future__ import annotations

from typing import Any

from .schema import EntityType, Relation, RelationType

# Which (source type, target type) each relation type is allowed to connect.
RELATION_ENDPOINT_TYPES: dict[RelationType, tuple[EntityType, EntityType]] = {
    RelationType.HAS_ROLE: (EntityType.USER, EntityType.ROLE),
    RelationType.MEMBER_OF: (EntityType.USER, EntityType.TEAM),
    RelationType.GRANTS_ACCESS_TO: (EntityType.USER, EntityType.SYSTEM),
    RelationType.REQUIRES_ROLE: (EntityType.POLICY, EntityType.ROLE),
    RelationType.GOVERNS: (EntityType.POLICY, EntityType.SYSTEM),
    RelationType.ASSIGNED_TO: (EntityType.TICKET, EntityType.USER),
    RelationType.FILED_BY: (EntityType.TICKET, EntityType.USER),
    RelationType.BLOCKS: (EntityType.TICKET, EntityType.TICKET),
}


def rule_endpoint_types(graph: Any, relation: Relation) -> str | None:
    """Every relation type has a fixed (source type, target type) shape."""
    expected = RELATION_ENDPOINT_TYPES.get(relation.type)
    if expected is None:
        return None
    src_type, tgt_type = expected
    source = graph.get_entity(relation.source_id)
    target = graph.get_entity(relation.target_id)
    if source.type != src_type or target.type != tgt_type:
        return (
            f"{relation.type.value} must go from {src_type.value} to {tgt_type.value}, "
            f"got {source.type.value} -> {target.type.value}"
        )
    return None


def rule_no_membership_cycles(graph: Any, relation: Relation) -> str | None:
    """Team membership must stay acyclic."""
    if relation.type != RelationType.MEMBER_OF:
        return None
    if graph.path_exists(relation.target_id, relation.source_id, RelationType.MEMBER_OF):
        return (
            f"adding MEMBER_OF {relation.source_id} -> {relation.target_id} "
            "would create a membership cycle"
        )
    return None


def rule_access_requires_policy_role(graph: Any, relation: Relation) -> str | None:
    """The core guardrail: a user can only be granted access to a system if
    every policy governing that system is satisfied by at least one role the
    user already holds. This is what turns the ontology from documentation
    into an enforced constraint an agent cannot reason its way around."""
    if relation.type != RelationType.GRANTS_ACCESS_TO:
        return None
    system_id = relation.target_id
    user_id = relation.source_id
    governing_policies = graph.neighbors(system_id, RelationType.GOVERNS, direction="in")
    if not governing_policies:
        return None  # ungoverned system: open access

    user_role_ids = {r.id for r in graph.neighbors(user_id, RelationType.HAS_ROLE, direction="out")}
    for policy in governing_policies:
        required_roles = graph.neighbors(policy.id, RelationType.REQUIRES_ROLE, direction="out")
        if not required_roles:
            continue
        if not any(role.id in user_role_ids for role in required_roles):
            allowed = ", ".join(r.id for r in required_roles)
            return (
                f"policy {policy.id!r} governing {system_id!r} requires one of roles "
                f"[{allowed}], but {user_id!r} has none of them"
            )
    return None


def default_rules() -> list:
    return [rule_endpoint_types, rule_no_membership_cycles, rule_access_requires_policy_role]
