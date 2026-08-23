from __future__ import annotations

from .graph import KnowledgeGraph
from .rules import default_rules
from .schema import Entity, EntityType, Relation, RelationType

KNOWLEDGE_BASE = [
    {
        "id": "kb-1",
        "title": "Requesting VPN access",
        "keywords": ["vpn", "remote", "access", "connect"],
        "body": (
            "VPN access is governed by the Engineering Systems Policy and requires the "
            "Engineer or Admin role. Employees without that role should first request a "
            "role change from their manager."
        ),
    },
    {
        "id": "kb-2",
        "title": "Data warehouse access requirements",
        "keywords": ["data", "warehouse", "analytics", "sql", "access"],
        "body": (
            "The data warehouse is governed by the Data Access Policy and requires the "
            "Data Analyst or Admin role. Requests from users who already hold that role "
            "should be granted directly."
        ),
    },
    {
        "id": "kb-3",
        "title": "New hire onboarding checklist",
        "keywords": ["onboarding", "new", "hire", "employee", "setup"],
        "body": (
            "Onboarding involves: creating the user record, assigning a role appropriate "
            "to their job, adding them to their team, and granting access to every system "
            "their role entitles them to."
        ),
    },
    {
        "id": "kb-4",
        "title": "Billing system access",
        "keywords": ["billing", "finance", "invoice", "payment"],
        "body": (
            "Billing system access is restricted by the Finance Policy to Managers and "
            "Admins to preserve segregation of duties."
        ),
    },
]


def build_graph() -> KnowledgeGraph:
    g = KnowledgeGraph()
    for rule in default_rules():
        g.add_rule(rule)

    for role in ("engineer", "data_analyst", "manager", "admin"):
        g.add_entity(Entity(f"role:{role}", EntityType.ROLE, {"name": role}))

    teams = {"platform": "Platform Engineering", "data": "Data & Analytics", "sales": "Sales"}
    for tid, name in teams.items():
        g.add_entity(Entity(f"team:{tid}", EntityType.TEAM, {"name": name}))

    systems = {
        "github": "GitHub",
        "vpn": "Corporate VPN",
        "billing": "Billing System",
        "data_warehouse": "Data Warehouse",
        "crm": "CRM",
    }
    for sid, name in systems.items():
        g.add_entity(Entity(f"system:{sid}", EntityType.SYSTEM, {"name": name}))

    policies = [
        ("eng_policy", "Engineering Systems Policy", ["github", "vpn"], ["engineer", "admin"]),
        ("finance_policy", "Finance Policy", ["billing"], ["manager", "admin"]),
        ("data_policy", "Data Access Policy", ["data_warehouse"], ["data_analyst", "admin"]),
    ]
    for pid, name, governed_systems, required_roles in policies:
        g.add_entity(Entity(f"policy:{pid}", EntityType.POLICY, {"name": name}))
        for sid in governed_systems:
            g.add_relation(Relation(f"policy:{pid}", RelationType.GOVERNS, f"system:{sid}"))
        for role in required_roles:
            g.add_relation(Relation(f"policy:{pid}", RelationType.REQUIRES_ROLE, f"role:{role}"))

    # (user id, display name, role, team, pre-granted systems)
    # crm is ungoverned (open access) so everyone gets it up front; the
    # governed systems are deliberately left partly ungranted so the demo
    # scenarios have real onboarding/access-request work to do.
    users = [
        ("alice", "Alice Kim", "admin", "platform", ["github", "vpn", "billing", "data_warehouse", "crm"]),
        ("bob", "Bob Singh", "engineer", "platform", ["github", "vpn", "crm"]),
        ("carol", "Carol Nguyen", "data_analyst", "data", ["crm"]),
        ("dave", "Dave Ortiz", "manager", "sales", ["crm"]),
    ]
    for uid, name, role, team, pre_granted in users:
        g.add_entity(Entity(f"user:{uid}", EntityType.USER, {"name": name}))
        g.add_relation(Relation(f"user:{uid}", RelationType.HAS_ROLE, f"role:{role}"))
        g.add_relation(Relation(f"user:{uid}", RelationType.MEMBER_OF, f"team:{team}"))
        for sid in pre_granted:
            g.add_relation(Relation(f"user:{uid}", RelationType.GRANTS_ACCESS_TO, f"system:{sid}"))

    # Erin: a brand new hire with no role/team/access yet - the subject of
    # the onboarding and access-guardrail demo scenarios.
    g.add_entity(Entity("user:erin", EntityType.USER, {"name": "Erin Walsh"}))

    g.add_entity(
        Entity(
            "ticket:t100",
            EntityType.TICKET,
            {
                "subject": "Cannot access data warehouse",
                "description": "I need SQL access to the data warehouse to build a report.",
                "status": "open",
            },
        )
    )
    g.add_relation(Relation("ticket:t100", RelationType.FILED_BY, "user:carol"))

    return g


def knowledge_base_search(query: str, limit: int = 3) -> list[dict]:
    tokens = {t.strip(".,!?").lower() for t in query.split()}
    scored = []
    for article in KNOWLEDGE_BASE:
        score = len(tokens & set(article["keywords"]))
        if score:
            scored.append((score, article))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:limit]]
