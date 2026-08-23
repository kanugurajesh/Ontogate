import pytest

from calyb.ontology.graph import KnowledgeGraph
from calyb.ontology.rules import default_rules, rule_no_membership_cycles
from calyb.ontology.schema import Entity, EntityType, OntologyViolation, Relation, RelationType
from calyb.ontology.seed_data import build_graph


def make_graph() -> KnowledgeGraph:
    g = KnowledgeGraph()
    for rule in default_rules():
        g.add_rule(rule)
    return g


def test_relation_endpoint_type_mismatch_is_rejected():
    g = make_graph()
    g.add_entity(Entity("user:a", EntityType.USER))
    g.add_entity(Entity("user:b", EntityType.USER))
    with pytest.raises(OntologyViolation):
        g.add_relation(Relation("user:a", RelationType.HAS_ROLE, "user:b"))


def test_membership_cycle_rule_detects_cycles():
    # MEMBER_OF is schema-restricted to USER->TEAM, so a literal cycle can
    # never reach the rule through the normal add_relation pipeline (the
    # endpoint-type rule would reject the reverse edge first). The cycle
    # rule is still a general-purpose graph utility (path_exists-based), so
    # it's tested directly against the underlying primitive it relies on.
    g = KnowledgeGraph()
    g.add_entity(Entity("user:a", EntityType.USER))
    g.add_entity(Entity("team:x", EntityType.TEAM))
    g.add_relation(Relation("user:a", RelationType.MEMBER_OF, "team:x"))

    would_be_cyclic = Relation("team:x", RelationType.MEMBER_OF, "user:a")
    assert rule_no_membership_cycles(g, would_be_cyclic) is not None


def test_grants_access_requires_governing_policy_role():
    g = build_graph()
    # Erin has no role at all, and the VPN is governed by a policy requiring
    # engineer/admin - this must be rejected.
    with pytest.raises(OntologyViolation, match="requires one of roles"):
        g.add_relation(Relation("user:erin", RelationType.GRANTS_ACCESS_TO, "system:vpn"))


def test_grants_access_allowed_when_role_satisfies_policy():
    g = build_graph()
    # Carol is a data_analyst and the data warehouse policy allows that role.
    g.add_relation(Relation("user:carol", RelationType.GRANTS_ACCESS_TO, "system:data_warehouse"))
    systems = {s.id for s in g.neighbors("user:carol", RelationType.GRANTS_ACCESS_TO)}
    assert "system:data_warehouse" in systems


def test_ungoverned_system_has_no_access_restriction():
    g = build_graph()
    # crm is not governed by any policy in the seed data.
    g.add_relation(Relation("user:erin", RelationType.GRANTS_ACCESS_TO, "system:crm"))


def test_seed_graph_builds_without_violations():
    g = build_graph()
    assert g.get_entity("user:alice").attributes["name"] == "Alice Kim"
    assert len(g.find_entities(type=EntityType.USER)) == 5
