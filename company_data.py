"""Sample company knowledge for "Lumen Pay" (fictional fintech). Raw sources are ingested by brain_ingest.py.

Entities are declared up front; sources (docs, tickets, chat messages, meeting notes) are linked to
entities automatically by the same linker that handles live ingestion.
"""

TEAMS = {
    "team:platform": "Platform",
    "team:payments": "Payments",
    "team:data": "Data",
    "team:growth": "Growth",
}

PEOPLE = [  # key, name, role, team, aliases
    ("person:maya", "Maya Chen", "CTO", "team:platform", ["maya", "@maya"]),
    ("person:priya", "Priya Nair", "Platform Engineering Manager", "team:platform", ["priya", "@priya"]),
    ("person:tomas", "Tomas Silva", "Senior Platform Engineer", "team:platform", ["tomas", "@tomas"]),
    ("person:noor", "Noor Haddad", "Security Engineer", "team:platform", ["noor", "@noor"]),
    ("person:diego", "Diego Ramos", "Site Reliability Engineer", "team:platform", ["diego", "@diego"]),
    ("person:lena", "Lena Fischer", "Payments Engineering Manager", "team:payments", ["lena", "@lena"]),
    ("person:arjun", "Arjun Rao", "Staff Engineer", "team:payments", ["arjun", "@arjun"]),
    ("person:zara", "Zara Ahmed", "Payments Engineer", "team:payments", ["zara", "@zara"]),
    ("person:jules", "Jules Martin", "Data Engineering Lead", "team:data", ["jules", "@jules"]),
    ("person:sam", "Sam Okafor", "Data Engineer", "team:data", ["sam", "@sam"]),
    ("person:kenji", "Kenji Watanabe", "Product Manager, Growth", "team:growth", ["kenji", "@kenji"]),
    ("person:ella", "Ella Brooks", "Frontend Engineer", "team:growth", ["ella", "@ella"]),
]

PROJECTS = [  # key, name, status, owning team, lead, aliases
    ("project:ledger", "Ledger Service", "active", "team:payments", "person:arjun", ["ledger"]),
    ("project:gateway", "Payments Gateway", "active", "team:payments", "person:lena", ["gateway", "payments gateway"]),
    ("project:eventbus", "Event Bus", "active", "team:platform", "person:priya", ["event bus", "eventbus"]),
    ("project:auth", "Auth Service", "migrating", "team:platform", "person:noor", ["auth service", "customer login", "login"]),
    ("project:warehouse", "Analytics Warehouse", "active", "team:data", "person:jules", ["warehouse", "analytics"]),
    ("project:checkout", "Checkout Redesign", "blocked", "team:growth", "person:kenji", ["checkout"]),
]

SYSTEMS = [  # key, name, aliases
    ("system:postgres", "Postgres", ["postgres", "postgresql"]),
    ("system:cockroach", "CockroachDB", ["cockroachdb", "cockroach"]),
    ("system:mongo", "MongoDB", ["mongodb", "mongo"]),
    ("system:kafka", "Kafka", ["kafka"]),
    ("system:redis", "Redis", ["redis"]),
    ("system:auth0", "Auth0", ["auth0"]),
    ("system:keycloak", "Keycloak", ["keycloak"]),
    ("system:snowflake", "Snowflake", ["snowflake"]),
    ("system:dbt", "dbt", ["dbt"]),
    ("system:stripe", "Stripe", ["stripe"]),
    ("system:k8s", "Kubernetes", ["kubernetes", "k8s"]),
]

USES = [
    ("project:ledger", "system:postgres"), ("project:ledger", "system:kafka"),
    ("project:gateway", "system:stripe"), ("project:gateway", "system:redis"), ("project:gateway", "system:kafka"),
    ("project:eventbus", "system:kafka"), ("project:eventbus", "system:k8s"),
    ("project:auth", "system:keycloak"), ("project:auth", "system:auth0"),
    ("project:warehouse", "system:snowflake"), ("project:warehouse", "system:dbt"), ("project:warehouse", "system:kafka"),
    ("project:checkout", "system:stripe"), ("project:checkout", "system:redis"),
]

# Sources. kind: doc | ticket | message | meeting
SOURCES = [
    # ---- Docs / ADRs ----
    dict(key="DOC-1", kind="doc", title="ADR-007: Ledger storage engine", author="person:arjun", date="2026-03-05",
         text="Decision: the Ledger Service will store balances and journal entries in Postgres. We evaluated MongoDB "
              "and Postgres. Mongo's multi-document transactions added latency and the team has deep Postgres "
              "experience. Double-entry invariants need serializable transactions. Approved by Maya in the "
              "architecture review."),
    dict(key="DOC-2", kind="doc", title="ADR-004: Company event bus", author="person:priya", date="2026-02-11",
         text="Decision: Kafka becomes the company event bus, run on Kubernetes with Strimzi. Every service publishes "
              "domain events to Kafka. Tomas wrote the reference consumer library and the partitioning guide."),
    dict(key="DOC-3", kind="doc", title="Kafka consumer runbook", author="person:tomas", date="2026-04-20",
         text="Runbook for Kafka consumer lag: check partition skew first, then rebalance storms. Use cooperative "
              "sticky assignment. Escalate to Tomas or Diego. Covers the ledger and warehouse consumers."),
    dict(key="DOC-4", kind="doc", title="RFC: Move customer login off Auth0", author="person:noor", date="2026-06-02",
         text="Proposal: migrate the Auth Service from Auth0 to self-hosted Keycloak. Auth0 pricing at 2M monthly "
              "active users is 4x our budget, and EU customers need data residency we cannot get on our current "
              "Auth0 plan. Migration in three phases, dual-running for 60 days."),
    dict(key="DOC-5", kind="doc", title="Warehouse modelling guide", author="person:jules", date="2026-04-09",
         text="All warehouse transforms now live in dbt models on Snowflake. Sam owns the payments marts. Raw events "
              "land from Kafka through the Snowflake connector."),
    dict(key="DOC-6", kind="doc", title="Payments Gateway retry policy", author="person:lena", date="2026-09-10",
         text="Gateway retries Stripe calls with exponential backoff and an idempotency key per payment intent. "
              "Zara found that the current policy retries on client timeouts too, which caused the retry storm."),
    # ---- Meetings ----
    dict(key="MEET-1", kind="meeting", title="Architecture review: ledger storage", author="person:maya", date="2026-03-04",
         text="Attendees: Maya, Arjun, Lena, Priya. Arjun presented Postgres vs MongoDB for the ledger. Decision: "
              "go with Postgres. Maya approved. Action: Arjun to write ADR-007."),
    dict(key="MEET-2", kind="meeting", title="Platform sync: event bus", author="person:priya", date="2026-02-10",
         text="Attendees: Priya, Tomas, Diego, Maya. Agreed Kafka is the event bus. Tomas will own the consumer "
              "library. Diego will run Kafka on Kubernetes."),
    dict(key="MEET-3", kind="meeting", title="Security review: customer auth", author="person:noor", date="2026-06-12",
         text="Attendees: Noor, Maya, Priya, Lena. Reviewed the Auth0 to Keycloak RFC. Decision: approved, migrate "
              "customer login to Keycloak by Q4. This replaces the November decision to use Auth0."),
    # ---- Tickets ----
    dict(key="AUTH-3", kind="ticket", title="Integrate Auth0 for customer login", author="person:noor", date="2025-11-20",
         status="done", assignee="person:noor",
         text="We decided to use Auth0 for customer login to ship fast. Set up tenant and social logins."),
    dict(key="AUTH-12", kind="ticket", title="Keycloak migration phase 1", author="person:noor", date="2026-06-15",
         status="in_progress", assignee="person:noor",
         text="Stand up Keycloak on Kubernetes, import users from Auth0, dual-run login. Diego to help with infra."),
    dict(key="PAY-31", kind="ticket", title="BIN lookup latency", author="person:zara", date="2026-05-01",
         status="done", assignee="person:zara",
         text="Card BIN lookups to Stripe add 120ms p95 to the gateway. Proposal: cache in Redis with 24h TTL. "
              "Lena approved: we will cache BIN lookups in Redis."),
    dict(key="PAY-52", kind="ticket", title="Gateway retry storm on Stripe timeouts", author="person:lena", date="2026-09-08",
         status="in_progress", assignee="person:zara",
         text="During the 7 Sep incident the gateway retried Stripe timeouts aggressively, tripling load. Fix the "
              "retry policy and add a circuit breaker. Blocks the checkout launch."),
    dict(key="GRW-7", kind="ticket", title="Launch checkout redesign", author="person:kenji", date="2026-08-30",
         status="blocked", assignee="person:ella",
         text="Roll out the new checkout to 100% of users. Blocked until the gateway retry fix lands."),
    dict(key="DATA-9", kind="ticket", title="Consumer lag on payments topic", author="person:sam", date="2026-07-02",
         status="done", assignee="person:sam",
         text="Warehouse Kafka consumer fell 2h behind. Tomas helped diagnose partition skew; fixed by rekeying."),
    dict(key="PLAT-21", kind="ticket", title="Upgrade Kafka to 3.8", author="person:tomas", date="2026-08-12",
         status="todo", assignee="person:tomas",
         text="Upgrade the Kafka cluster on Kubernetes. Coordinate with ledger and warehouse consumers."),
    # ---- Chat messages ----
    dict(key="MSG-1", kind="message", channel="#arch", author="person:arjun", date="2026-03-03",
         text="Benchmarks are in: Postgres serializable txns beat Mongo transactions by 35% on our ledger workload."),
    dict(key="MSG-2", kind="message", channel="#platform", author="person:tomas", date="2026-03-18",
         text="Published the Kafka consumer library v1. Idempotent consumers, retries, dead letter topic built in."),
    dict(key="MSG-3", kind="message", channel="#platform", author="person:tomas", date="2026-05-22",
         text="PSA: if you see Kafka rebalance storms, switch to cooperative sticky assignment. Happy to pair."),
    dict(key="MSG-4", kind="message", channel="#data", author="person:sam", date="2026-07-02",
         text="Thanks @tomas, the Kafka partition skew fix brought warehouse lag from 2h to 30s."),
    dict(key="MSG-5", kind="message", channel="#payments", author="person:zara", date="2026-05-02",
         text="Redis BIN cache is live on the gateway. p95 down 110ms."),
    dict(key="MSG-6", kind="message", channel="#incidents", author="person:diego", date="2026-09-07",
         text="Incident: gateway retry storm against Stripe after a timeout spike. Mitigated by scaling down retries. "
              "Follow up in PAY-52."),
    dict(key="MSG-7", kind="message", channel="#growth", author="person:kenji", date="2026-09-15",
         text="Decision with Lena: we freeze the checkout redesign launch until PAY-52 retry fix ships."),
    dict(key="MSG-8", kind="message", channel="#security", author="person:noor", date="2026-06-13",
         text="Keycloak migration approved. Auth0 stays live until dual-run finishes. Questions about login go to me."),
    dict(key="MSG-9", kind="message", channel="#data", author="person:jules", date="2026-04-08",
         text="We're moving all warehouse transforms to dbt. Sam will lead the payments marts."),
    dict(key="MSG-10", kind="message", channel="#platform", author="person:diego", date="2026-06-20",
         text="Keycloak is up on Kubernetes in staging. Noor, ready for the Auth0 user import test."),
    dict(key="MSG-11", kind="message", channel="#payments", author="person:arjun", date="2026-08-02",
         text="Ledger Postgres is at 70% CPU at peak. Fine for now, but multi-region writes will need a rethink."),
]

# Decisions extracted from sources (ingestion also detects new ones live).
DECISIONS = [  # key, title, summary, date, makers, affects, sources, supersedes
    ("DEC-1", "Use Postgres for the Ledger Service",
     "Postgres over MongoDB for serializable transactions and team experience.", "2026-03-04",
     ["person:arjun", "person:maya"], ["project:ledger", "system:postgres"], ["MEET-1", "DOC-1", "MSG-1"], None),
    ("DEC-2", "Kafka is the company event bus",
     "All services publish domain events to Kafka on Kubernetes.", "2026-02-10",
     ["person:priya", "person:tomas"], ["project:eventbus", "system:kafka"], ["MEET-2", "DOC-2"], None),
    ("DEC-3", "Use Auth0 for customer login",
     "Ship login fast with a hosted provider.", "2025-11-20",
     ["person:noor"], ["project:auth", "system:auth0"], ["AUTH-3"], None),
    ("DEC-4", "Migrate customer login from Auth0 to Keycloak",
     "Auth0 cost at 2M MAU is 4x budget and EU data residency is required.", "2026-06-12",
     ["person:noor", "person:maya"], ["project:auth", "system:keycloak", "system:auth0"], ["MEET-3", "DOC-4", "MSG-8"], "DEC-3"),
    ("DEC-5", "Cache BIN lookups in Redis with 24h TTL",
     "Cuts gateway p95 by ~110ms.", "2026-05-01",
     ["person:lena", "person:zara"], ["project:gateway", "system:redis"], ["PAY-31", "MSG-5"], None),
    ("DEC-6", "Freeze checkout launch until the retry fix ships",
     "Gateway retry storm (PAY-52) must be fixed before the checkout redesign goes to 100%.", "2026-09-15",
     ["person:kenji", "person:lena"], ["project:checkout", "project:gateway"], ["MSG-7", "GRW-7"], None),
    ("DEC-7", "Warehouse transforms move to dbt",
     "Standardise modelling in dbt on Snowflake.", "2026-04-08",
     ["person:jules", "person:sam"], ["project:warehouse", "system:dbt"], ["MSG-9", "DOC-5"], None),
]

BLOCKS = [("PAY-52", "GRW-7")]

DEMO_QUESTIONS = [
    "Why did we choose Postgres for the ledger, and who made that call?",
    "Who should I ask about Kafka consumer lag?",
    "What changed about customer login, and why?",
    "Why is the checkout redesign blocked and who can unblock it?",
    "Who owns the Payments Gateway and what are they working on?",
]

DEMO_INGEST = {
    "kind": "message", "channel": "#arch", "author": "person:maya",
    "text": "After the multi-region load test, we decided to move the ledger from Postgres to CockroachDB. "
            "Arjun will lead the migration.",
}
