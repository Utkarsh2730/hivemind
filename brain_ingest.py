"""Build and grow a company brain graph. Works for any workspace (the current one is set in graph_db).

- init_graph(): indexes for a new, empty workspace
- add_entities(): people, teams, projects, systems/tools
- add_knowledge(): a doc, ticket, chat message or meeting note. Links it to known entities, detects
  decisions, and marks older decisions as superseded.
- build_demo(): the sample company "Lumen Pay"

Run: python brain_ingest.py   (rebuilds the demo workspace)
"""
import json
import os
import re
from datetime import date

from graph_db import get_graph, workspace

# Phrases that record a choice. Kept narrow on purpose: "approved" or "we'll look" alone are not decisions.
DECISION_RE = re.compile(
    r"\b(decided|decision:|we're moving|we are moving|(?:we will|we'll) (?:use|move|switch|adopt|go with|migrate)|"
    r"go with|going with|agreed (?:to|on)|we freeze|switching to|we chose|we picked|we've chosen)\b",
    re.IGNORECASE,
)
# Common tools and technologies, recognised even without an AI key.
TECH = ["Postgres", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "RabbitMQ", "Elasticsearch", "OpenSearch",
        "Snowflake", "BigQuery", "Redshift", "dbt", "Airflow", "Spark", "Kubernetes", "Docker", "Terraform", "Helm",
        "AWS", "GCP", "Azure", "S3", "Lambda", "CloudFront", "Cloudflare", "Vercel", "Netlify", "Heroku", "Render",
        "React", "React Native", "Next.js", "Vue", "Angular", "Svelte", "Node.js", "Deno", "Python", "Django", "FastAPI",
        "Flask", "Rails", "Go", "Rust", "Java", "Spring", "Kotlin", "Swift", "Flutter", "GraphQL", "gRPC", "REST",
        "Stripe", "Auth0", "Okta", "Keycloak", "Firebase", "Supabase", "Datadog", "Sentry", "Grafana", "Prometheus",
        "PagerDuty", "Jenkins", "GitHub Actions", "CircleCI", "ArgoCD", "Nginx", "Envoy", "Istio", "CockroachDB",
        "DynamoDB", "Cassandra", "ClickHouse", "FalkorDB", "Neo4j", "OpenAI", "Claude", "Anthropic", "LangChain",
        "PyTorch", "TensorFlow", "Jetson", "ROS 2", "Segment", "Mixpanel", "Amplitude", "Twilio", "SendGrid",
        "Salesforce", "HubSpot", "Zendesk", "Jira", "Linear", "Notion", "Figma", "Slack", "Webpack", "Vite", "TypeScript"]
_TECH_RE = [(re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", re.IGNORECASE if len(t) > 3 else 0), t) for t in TECH]
KIND_PREFIX = {"doc": "DOC", "ticket": "TKT", "message": "MSG", "meeting": "MEET"}
KINDS = set(KIND_PREFIX)
LABELS = ["Person", "Team", "Project", "System", "Source", "Decision"]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "x"


def has_llm() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---------- schema ----------

def init_graph(wipe: bool = False):
    g = get_graph()
    if wipe:
        try:
            g.delete()
        except Exception:
            pass
        g = get_graph()
    g.query("RETURN 1")  # creates the graph key
    for stmt in ["CALL db.idx.fulltext.createNodeIndex('Source', 'text', 'title')",
                 "CALL db.idx.fulltext.createNodeIndex('Decision', 'title', 'summary')"] + \
                [f"CREATE INDEX FOR (n:{label}) ON (n.key)" for label in LABELS]:
        try:
            g.query(stmt)
        except Exception:
            pass  # index already exists
    return g


def counts() -> dict:
    rows = get_graph().ro_query("MATCH (n) RETURN labels(n)[0], count(n)").result_set
    return {label: c for label, c in rows}


# ---------- entity linking ----------

def _alias_table():
    """(compiled regex, entity key) for every alias, longest first so 'payments gateway' beats 'gateway'."""
    rows = get_graph().ro_query("MATCH (e) WHERE e:Person OR e:Project OR e:System OR e:Team "
                                "RETURN e.key, e.name, e.aliases").result_set
    pairs = []
    for key, name, aliases in rows:
        for a in set([name.lower()] + [x.lstrip("@").lower() for x in (aliases or []) if x]):
            if len(a) >= 2:
                pairs.append((a, key))
    pairs.sort(key=lambda p: -len(p[0]))
    return [(re.compile(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", re.IGNORECASE), k) for a, k in pairs]


def link_entities(text: str, table=None) -> list[str]:
    table = table if table is not None else _alias_table()
    found, taken = [], []
    for rx, key in table:
        for m in rx.finditer(text or ""):
            if any(s <= m.start() < e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            if key not in found:
                found.append(key)
    return found


# ---------- entities ----------

def _names(items):
    return [i.strip() for i in items if i and i.strip()]


def add_team(name: str) -> str:
    key = f"team:{slugify(name)}"
    get_graph().query("MERGE (t:Team {key: $k}) ON CREATE SET t.name = $n, t.aliases = [$l]",
                      {"k": key, "n": name.strip(), "l": name.strip().lower()})
    return key


def add_person(name: str, role: str = "", team: str = "", aliases=None, _skip_resolve=False) -> str:
    name = name.strip().lstrip("@")
    existing = None if _skip_resolve else resolve_person(name)
    key = existing or f"person:{slugify(name)}"
    first = name.split()[0].lower() if name.split() else name.lower()
    al = list(dict.fromkeys([first, name.lower()] + [a.lower() for a in _names(aliases or [])]))
    g = get_graph()
    g.query("MERGE (p:Person {key: $k}) ON CREATE SET p.name = $n, p.aliases = $a, p.role = $r "
            "ON MATCH SET p.role = CASE WHEN $r <> '' THEN $r ELSE p.role END",
            {"k": key, "n": name, "a": al, "r": role.strip()})
    if team.strip():
        tk = add_team(team)
        g.query("MATCH (p:Person {key: $p}), (t:Team {key: $t}) MERGE (p)-[:MEMBER_OF]->(t)", {"p": key, "t": tk})
    return key


def add_system(name: str, aliases=None) -> str:
    key = f"system:{slugify(name)}"
    al = list(dict.fromkeys([name.strip().lower()] + [a.lower() for a in _names(aliases or [])]))
    get_graph().query("MERGE (s:System {key: $k}) ON CREATE SET s.name = $n, s.aliases = $a",
                      {"k": key, "n": name.strip(), "a": al})
    return key


def add_project(name: str, team: str = "", lead: str = "", uses=None, status: str = "active", aliases=None) -> str:
    key = f"project:{slugify(name)}"
    al = list(dict.fromkeys([name.strip().lower()] + [a.lower() for a in _names(aliases or [])]))
    g = get_graph()
    g.query("MERGE (p:Project {key: $k}) ON CREATE SET p.name = $n, p.aliases = $a, p.status = $s",
            {"k": key, "n": name.strip(), "a": al, "s": status or "active"})
    if team.strip():
        tk = add_team(team)
        g.query("MATCH (t:Team {key: $t}), (p:Project {key: $p}) MERGE (t)-[:OWNS]->(p)", {"t": tk, "p": key})
    if lead.strip():
        lk = resolve_person(lead, create=True)
        g.query("MATCH (l:Person {key: $l}), (p:Project {key: $p}) MERGE (l)-[:LEADS]->(p)", {"l": lk, "p": key})
    for s in _names(uses or []):
        sk = add_system(s)
        g.query("MATCH (p:Project {key: $p}), (s:System {key: $s}) MERGE (p)-[:USES]->(s)", {"p": key, "s": sk})
    return key


def resolve_person(name_or_key: str, create: bool = False) -> str | None:
    """Find a person by key, name, alias or a unique first name, so 'Arjun', 'arjun' and 'Arjun Rao' are one person."""
    v = (name_or_key or "").strip().lstrip("@")
    if not v:
        return None
    g = get_graph()
    rows = g.ro_query("MATCH (p:Person) WHERE p.key = $v OR toLower(p.name) = toLower($v) OR toLower($v) IN p.aliases "
                      "RETURN p.key LIMIT 1", {"v": v}).result_set
    if rows:
        return rows[0][0]
    parts = v.split()
    same_first = g.ro_query("MATCH (p:Person) WHERE toLower(split(p.name, ' ')[0]) = toLower($f) RETURN p.key, p.name",
                            {"f": parts[0]}).result_set
    if len(same_first) == 1:
        key, name = same_first[0]
        existing = name.split()
        if len(parts) == 1:
            return key  # "Arjun" -> the only Arjun
        if len(existing) == 1:  # we only knew "Arjun"; now we learn the full name
            g.query("MATCH (p:Person {key: $k}) SET p.name = $n, p.aliases = p.aliases + [toLower($n)]", {"k": key, "n": v})
            return key
        if existing[-1].lower().startswith(parts[-1].lower().rstrip(".")):
            return key  # "Arjun R." -> "Arjun Rao"
    return add_person(v, _skip_resolve=True) if create else None


def add_entities(people=(), teams=(), projects=(), systems=()) -> dict:
    """people: [{name, role, team}], teams: [name], projects: [{name, team, lead, uses, status}],
    systems: [{name, aliases}]"""
    for t in teams:
        if str(t).strip():
            add_team(str(t))
    for s in systems:
        s = {"name": s} if isinstance(s, str) else s
        if s.get("name", "").strip():
            add_system(s["name"], s.get("aliases"))
    for p in people:
        if p.get("name", "").strip():
            add_person(p["name"], p.get("role", ""), p.get("team", ""), p.get("aliases"))
    for p in projects:
        if p.get("name", "").strip():
            add_project(p["name"], p.get("team", ""), p.get("lead", ""), p.get("uses"), p.get("status", "active"),
                        p.get("aliases"))
    return counts()


# ---------- knowledge ----------

def _next_key(g, prefix):
    rows = g.ro_query("MATCH (s:Source) WHERE s.key STARTS WITH $p RETURN s.key", {"p": prefix + "-"}).result_set
    nums = [int(k.split("-")[-1]) for (k,) in rows if k.split("-")[-1].isdigit()]
    return f"{prefix}-{max(nums, default=0) + 1}"


def _llm_extract(text, author, mentions, candidates, known_names):
    """One Claude call: new entities the text names, plus decision details. None if unavailable."""
    if not has_llm():
        return None
    try:
        import anthropic
        schema = {
            "type": "object", "additionalProperties": False,
            "required": ["people", "projects", "systems", "is_decision", "decision_title", "decision_summary", "supersedes"],
            "properties": {
                "people": {"type": "array", "items": {"type": "string"}},
                "projects": {"type": "array", "items": {"type": "string"}},
                "systems": {"type": "array", "items": {"type": "string"}},
                "is_decision": {"type": "boolean"},
                "decision_title": {"type": "string"},
                "decision_summary": {"type": "string"},
                "supersedes": {"type": "array", "items": {"type": "string"}},
            },
        }
        prompt = (
            f"Company knowledge item written by {author or 'unknown'}:\n<<<\n{text[:6000]}\n>>>\n\n"
            f"Entities already known: {known_names[:150]}\n"
            f"Entities already linked in this item: {mentions}\n"
            f"Active decisions touching the same entities: {json.dumps(candidates)}\n\n"
            "1. List people (full names), projects/products/initiatives, and systems/tools/technologies that this "
            "item names and that are NOT already known. Use the exact spelling from the text. Empty lists if none.\n"
            "2. Does it record a decision (a choice that was made, not a proposal or question)? If yes, give a short "
            "title (imperative, under 10 words), a one-sentence summary including the reason, and the keys of any "
            "active decisions it clearly reverses or replaces. If not, use empty strings and an empty list."
        )
        msg = anthropic.Anthropic().messages.create(
            model="claude-opus-5-5", max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads("".join(b.text for b in msg.content if b.type == "text"))
    except Exception as e:  # never break ingestion on the LLM path
        print("LLM extraction failed, using rule-based extraction:", e)
        return None


def _write_decision(g, key, title, summary, d, makers, affects, sources):
    g.query("CREATE (:Decision {key: $k, title: $t, summary: $s, date: $d, status: 'active'})",
            {"k": key, "t": title, "s": summary, "d": d})
    for m in makers:
        g.query("MATCH (p:Person {key: $p}), (d:Decision {key: $k}) MERGE (p)-[:MADE]->(d)", {"p": m, "k": key})
    for a in affects:
        g.query("MATCH (e {key: $a}), (d:Decision {key: $k}) MERGE (d)-[:AFFECTS]->(e)", {"a": a, "k": key})
    for s in sources:
        g.query("MATCH (s:Source {key: $s}), (d:Decision {key: $k}) MERGE (d)-[:DECIDED_IN]->(s)", {"s": s, "k": key})


def _supersede(g, new_key, old_key):
    g.query("MATCH (n:Decision {key: $n}), (o:Decision {key: $o}) "
            "SET o.status = 'superseded' MERGE (n)-[:SUPERSEDES]->(o)", {"n": new_key, "o": old_key})


def _rule_decision(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    first = next((x for x in sentences if DECISION_RE.search(x)), sentences[0])
    m = re.search(r"(?:decided to|we will|we'll|we're moving|we are moving|going with|go with|switching to|agreed to|"
                  r"we chose|we picked)\s+(.+)", first, re.I)
    clause = (m.group(1) if m else first).rstrip(".")
    if m and re.match(r"(?:we're moving|we are moving)", m.group(0), re.I):
        clause = "move " + clause
    return (clause[:1].upper() + clause[1:])[:90]


def add_knowledge(kind: str, text: str, author: str = "", title: str = "", date_: str = "", channel: str = "",
                  status: str = "", assignee: str = "", key: str = "", use_llm: bool = True,
                  detect_decisions: bool = True, _table=None) -> dict:
    """Add one source and connect it. Returns what changed."""
    g = get_graph()
    kind = kind if kind in KINDS else "doc"
    text = (text or "").strip()
    key = re.sub(r"[^A-Za-z0-9-]", "", key or "").upper()[:20]
    if not re.fullmatch(r"[A-Z]{2,5}-\d+", key) or g.ro_query("MATCH (s:Source {key: $k}) RETURN 1", {"k": key}).result_set:
        key = _next_key(g, KIND_PREFIX[kind])
    d = date_ or date.today().isoformat()
    author_key = resolve_person(author, create=True) if author else None
    title = (title or "").strip() or (text[:70] + ("..." if len(text) > 70 else ""))

    table = _table if _table is not None else _alias_table()
    # @mentions are people; known technologies are tools. Both work without an AI key.
    grew = False
    for handle in set(re.findall(r"(?<![\w.])@([A-Za-z][\w.-]{1,30})", text)):
        if not resolve_person(handle):
            add_person(handle); grew = True
    known_sys = {n.lower() for (n,) in g.ro_query("MATCH (s:System) RETURN s.name").result_set}
    for rx, tech in _TECH_RE:
        if tech.lower() not in known_sys and rx.search(title + " " + text):
            add_system(tech); known_sys.add(tech.lower()); grew = True
    if grew:
        table = _alias_table()
    pre_mentions = link_entities(title + "\n" + text, table)

    llm = None
    decision_hint = detect_decisions and DECISION_RE.search(text)
    if use_llm and has_llm():
        known = [r[0] for r in g.ro_query("MATCH (e) WHERE e:Person OR e:Project OR e:System RETURN e.name").result_set]
        cand = _candidates(g, [m for m in pre_mentions if m.startswith(("project:", "system:"))])
        llm = _llm_extract(text, author, pre_mentions, cand, known)
        if llm:
            new = False
            for n in llm["people"]:
                if not resolve_person(n):
                    add_person(n); new = True
            for n in llm["projects"]:
                add_project(n); new = True
            for n in llm["systems"]:
                add_system(n); new = True
            if new:
                table = _alias_table()

    g.query("CREATE (s:Source {key: $k, kind: $kind, title: $title, text: $text, date: $d, channel: $ch, status: $st})",
            {"k": key, "kind": kind, "title": title[:200], "text": text, "d": d, "ch": channel, "st": status})
    if author_key:
        g.query("MATCH (p:Person {key: $a}), (s:Source {key: $k}) MERGE (p)-[:AUTHORED]->(s)", {"a": author_key, "k": key})
    if assignee:
        ak = resolve_person(assignee, create=True)
        g.query("MATCH (p:Person {key: $a}), (s:Source {key: $k}) MERGE (s)-[:ASSIGNED_TO]->(p)", {"a": ak, "k": key})
    mentions = [m for m in dict.fromkeys(link_entities(title + "\n" + text, table)) if m != author_key]
    for m in mentions:
        g.query("MATCH (s:Source {key: $k}), (e {key: $m}) MERGE (s)-[:MENTIONS]->(e)", {"k": key, "m": m})
    for ref in set(re.findall(r"\b[A-Z]{2,5}-\d+\b", text)):
        if ref != key:
            g.query("MATCH (s:Source {key: $k}), (r:Source {key: $r}) MERGE (s)-[:REFERENCES]->(r)", {"k": key, "r": ref})
    if re.search(r"\bblock(s|ed|ing)?\b", text, re.I):
        for ref in set(re.findall(r"\b[A-Z]{2,5}-\d+\b", text)) - {key}:
            if re.search(r"blocked (?:by|until)[^.]*\b" + re.escape(ref), text, re.I):
                g.query("MATCH (b:Source {key: $b}), (s:Source {key: $k}) MERGE (b)-[:BLOCKS]->(s)", {"b": ref, "k": key})

    changed = {"source": key, "mentions": mentions, "decision": None, "superseded": []}
    is_decision = llm["is_decision"] if llm else bool(decision_hint)
    if not (detect_decisions and is_decision):
        return changed

    affects = [m for m in mentions if m.startswith(("project:", "system:"))]
    candidates = _candidates(g, affects)
    if llm and llm["decision_title"]:
        dtitle, summary, supersedes = llm["decision_title"], llm["decision_summary"] or text[:300], llm["supersedes"]
    else:
        dtitle, summary = _rule_decision(text), text[:400]
        new_proj = {a for a in affects if a.startswith("project:")}
        new_sys = {a for a in affects if a.startswith("system:")}
        # Stale if it touches the same system, and the same project when both name one.
        supersedes = []
        for c in candidates:
            c_proj = {a for a in c["affects"] if a.startswith("project:")}
            if new_sys & set(c["affects"]) and (new_proj & c_proj or not new_proj or not c_proj):
                supersedes.append(c["key"])
    nums = [int(k.split("-")[1]) for (k,) in g.ro_query("MATCH (d:Decision) RETURN d.key").result_set
            if k.split("-")[-1].isdigit()]
    dkey = f"DEC-{max(nums, default=0) + 1}"
    _write_decision(g, dkey, dtitle, summary, d, [author_key] if author_key else [], affects, [key])
    for old in supersedes:
        if old in {c["key"] for c in candidates}:
            _supersede(g, dkey, old)
            changed["superseded"].append(old)
    changed["decision"] = {"key": dkey, "title": dtitle, "summary": summary, "extraction": "claude" if llm else "rules"}
    return changed


def delete_source(key: str) -> dict:
    """Remove one item. Decisions recorded only in it are removed too, and anything they replaced is restored."""
    g = get_graph()
    if not g.ro_query("MATCH (s:Source {key: $k}) RETURN 1", {"k": key}).result_set:
        raise ValueError("Item not found.")
    only_here = [k for (k,) in g.ro_query(
        "MATCH (d:Decision)-[:DECIDED_IN]->(:Source {key: $k}) OPTIONAL MATCH (d)-[:DECIDED_IN]->(o:Source) "
        "WITH d, count(o) AS n WHERE n = 1 RETURN d.key", {"k": key}).result_set]
    restored = []
    for d in only_here:
        restored += remove_decision(d)["restored"]
    g.query("MATCH (s:Source {key: $k}) DETACH DELETE s", {"k": key})
    return {"deleted": key, "decisions_removed": only_here, "restored": restored}


def remove_decision(key: str) -> dict:
    """'This is not a decision': delete it and reactivate decisions it had marked outdated."""
    g = get_graph()
    old = [k for (k,) in g.ro_query("MATCH (:Decision {key: $k})-[:SUPERSEDES]->(o) RETURN o.key", {"k": key}).result_set]
    g.query("MATCH (d:Decision {key: $k}) DETACH DELETE d", {"k": key})
    restored = []
    for o in old:
        if not g.ro_query("MATCH (n:Decision)-[:SUPERSEDES]->(:Decision {key: $o}) RETURN 1", {"o": o}).result_set:
            g.query("MATCH (d:Decision {key: $o}) SET d.status = 'active'", {"o": o})
            restored.append(o)
    return {"removed": key, "restored": restored}


def _candidates(g, affects):
    if not affects:
        return []
    rows = g.ro_query("MATCH (d:Decision {status: 'active'})-[:AFFECTS]->(e) WHERE e.key IN $a "
                      "RETURN d.key, d.title, collect(e.key)", {"a": affects}).result_set
    return [{"key": k, "title": t, "affects": a} for k, t, a in rows]


def ingest(kind, author, text, channel="", title=""):
    """Live single message (kept for the UI's 'post a message' box)."""
    return add_knowledge(kind, text, author=author, title=title, channel=channel)


def bulk_import(sources: list[dict], llm_budget: int = 25) -> dict:
    """Import many sources. Oldest first so later decisions supersede earlier ones. Claude is used for the
    first `llm_budget` items when a key is set; the rest use rule-based linking."""
    out = {"added": 0, "decisions": 0, "superseded": 0, "errors": []}
    ordered = sorted(sources, key=lambda s: s.get("date") or "9999")
    cached = None
    for i, s in enumerate(ordered):
        use_llm = has_llm() and i < llm_budget
        if not use_llm and cached is None:
            cached = _alias_table()  # entities are stable from here on, so link with one table
        try:
            r = add_knowledge(s.get("kind", "doc"), s.get("text", ""), author=s.get("author", ""),
                              title=s.get("title", ""), date_=s.get("date", ""), channel=s.get("channel", ""),
                              status=s.get("status", ""), assignee=s.get("assignee", ""),
                              key=s.get("key", s.get("id", "")), use_llm=use_llm,
                              detect_decisions=s.get("detect_decisions", True),
                              _table=None if use_llm else cached)
            out["added"] += 1
            out["decisions"] += 1 if r["decision"] else 0
            out["superseded"] += len(r["superseded"])
        except Exception as e:
            out["errors"].append(f"{s.get('title') or s.get('text', '')[:30]}: {e}")
    out["counts"] = counts()
    return out


# ---------- demo company ----------

def build_demo():
    import company_data as cd
    with workspace("demo"):
        g = init_graph(wipe=True)
        for key, name in cd.TEAMS.items():
            g.query("CREATE (:Team {key: $k, name: $n, aliases: [$l]})", {"k": key, "n": name, "l": name.lower()})
        for key, name, role, team, aliases in cd.PEOPLE:
            g.query("MATCH (t:Team {key: $t}) CREATE (p:Person {key: $k, name: $n, role: $r, aliases: $a})-[:MEMBER_OF]->(t)",
                    {"t": team, "k": key, "n": name, "r": role, "a": [a.lstrip("@") for a in aliases]})
        for key, name, status, team, lead, aliases in cd.PROJECTS:
            g.query("MATCH (t:Team {key: $t}), (l:Person {key: $l}) "
                    "CREATE (p:Project {key: $k, name: $n, status: $s, aliases: $a}), (t)-[:OWNS]->(p), (l)-[:LEADS]->(p)",
                    {"t": team, "l": lead, "k": key, "n": name, "s": status, "a": aliases})
        for key, name, aliases in cd.SYSTEMS:
            g.query("CREATE (:System {key: $k, name: $n, aliases: $a})", {"k": key, "n": name, "a": aliases})
        for p, s in cd.USES:
            g.query("MATCH (p:Project {key: $p}), (s:System {key: $s}) CREATE (p)-[:USES]->(s)", {"p": p, "s": s})
        table = _alias_table()
        for src in cd.SOURCES:
            add_knowledge(src["kind"], src["text"], author=src["author"], title=src.get("title", ""),
                          date_=src["date"], channel=src.get("channel", ""), status=src.get("status", ""),
                          assignee=src.get("assignee", ""), key=src["key"], use_llm=False,
                          detect_decisions=False, _table=table)
        for a, b in cd.BLOCKS:
            g.query("MATCH (a:Source {key: $a}), (b:Source {key: $b}) MERGE (a)-[:BLOCKS]->(b)", {"a": a, "b": b})
        for key, title, summary, d, makers, affects, sources, supersedes in cd.DECISIONS:
            _write_decision(g, key, title, summary, d, makers, affects, sources)
            if supersedes:
                _supersede(g, key, supersedes)
        c = counts()
        edges = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    print("Demo workspace built:", c, "| edges:", edges)
    return c


build = build_demo  # backwards compatible name

if __name__ == "__main__":
    build_demo()
