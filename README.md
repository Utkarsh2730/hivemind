# Company Brain — Track 03 (WeMakeDevs × FalkorDB)

**In one sentence:** any company can turn its docs, tickets, meeting notes and chats into one connected map, then ask who owns what, who knows what, and why decisions were made, with every answer linked to its source.

1. **Register your company.** You get a private workspace with its own FalkorDB graph and a secret access link.
2. **Add your people and projects.** Type them in, or upload a file.
3. **Add your knowledge.** Paste docs, meeting notes, tickets and chats, or upload `.txt`, `.md`, `.csv` or `.json` files. Each item is linked to the right people, projects and tools.
4. **Ask anything.** The brain follows the connections to the answer, shows the sources, and highlights the path on the map.
5. **Write a PRD or sprint plan** for any project in one click, built from the company's own decisions, open tickets, blockers and experts. Every line is cited. Blockers are scheduled first, owners come from assignees or from whoever has hands-on experience, and single-expert risks are flagged. Download as Markdown or save as PDF.
6. **It stays current.** When a new message records a decision that replaces an older one, the older one is marked outdated.

A public demo company, **Lumen Pay**, is included so judges can try everything without setting anything up.

---

## Live demo

**[link goes here after deploy]** — open it in any browser. Nothing to install.

## Deploy online (FalkorDB Cloud + Render, both free)

1. **FalkorDB Cloud:** create a free instance at https://app.falkordb.cloud, then copy its host, port, username and password.
2. **Render:** go to https://dashboard.render.com and choose **New → Blueprint**. Pick this GitHub repo (it reads `render.yaml`).
3. Fill in `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`, and optionally `ANTHROPIC_API_KEY`. Deploy.
4. On first start the app builds the company graph in FalkorDB Cloud itself. Open the Render URL.

Because the demo is public, it has per-visitor rate limits and length caps on questions and posts. Visitor posts are cleared automatically after 50. If the AI is unavailable, answers come straight from the graph instead.

## Run locally (macOS)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py            # open http://localhost:8000 (uses embedded FalkorDB)
```

Without `ANTHROPIC_API_KEY`, a rule-based planner calls the same graph tools, so every demo question still works. With a key, Claude Opus 5.5 decides which tools to call and writes the answer.

## How it maps to Track 03

| Key focus | What we built |
|---|---|
| Knowledge from docs, tickets and chats in one graph | 27 sources (ADRs, RFCs, runbooks, tickets, Slack-style messages, meeting notes) are linked automatically to 33 people, teams, projects and systems |
| Who owns what, and who knows what | `who_knows` ranks hands-on expertise (authored sources, assigned tickets, being named or thanked by colleagues, decisions made) separately from formal `LEADS`/`OWNS` edges. Example: Priya owns the Event Bus, but Tomas is the person to ask about Kafka |
| Tracing decisions back to their source | `Decision` nodes link through `DECIDED_IN` to the meeting, ADR and chat message they came from, and through `MADE` to the people who made them |
| Keeping knowledge current as things change | Live ingestion links a new message, detects a decision, and adds `SUPERSEDES` to the older decision (Claude extraction when a key is set, rules otherwise) |
| Answers with clear sources | Every claim cites `[KEY]`. Clicking a citation opens the source and focuses that node in the graph |

## Graph model

```
(Person)-[:MEMBER_OF]->(Team)-[:OWNS]->(Project)<-[:LEADS]-(Person)
(Project)-[:USES]->(System)
(Person)-[:AUTHORED]->(Source)-[:MENTIONS]->(Person|Project|System|Team)
(Source)-[:ASSIGNED_TO]->(Person)   (Source)-[:BLOCKS|REFERENCES]->(Source)
(Person)-[:MADE]->(Decision)-[:DECIDED_IN]->(Source)
(Decision)-[:AFFECTS]->(Project|System)   (Decision)-[:SUPERSEDES]->(Decision)
```

FalkorDB full-text indexes on `Source(text, title)` and `Decision(title, summary)` handle retrieval. Cypher traversals produce the reasoning. Agent queries run on FalkorDB's read-only path, and write keywords are rejected.

## Files

| File | Purpose |
|---|---|
| `brain_docs.py` | PRD and sprint plan generator: collects project facts from the graph, then Claude writes the document (or a template, without a key) |
| `static/app.js` | Workspace page logic: ask, write docs, add info, file import, map |
| `workspaces.py` | Company registration. Each company gets its own graph (`cb_<slug>`) and an access key; only the key's SHA-256 hash is stored |
| `static/landing.html` | Home page: register a company or open the demo |
| `company_data.py` | Data for the demo company "Lumen Pay" (fictional) |
| `brain_ingest.py` | Works for any workspace: adds people, projects and tools, adds knowledge, detects decisions and replaces outdated ones, bulk import, demo build |
| `brain_tools.py` | Agent tools: `search_knowledge`, `entity_profile`, `who_knows`, `decision_trail`, `run_cypher`, plus the trace |
| `brain_agent.py` | Claude agent (tool runner) and the graph-only planner. CLI: `python brain_agent.py "question"` |
| `server.py`, `static/index.html` | FastAPI app and the UI (vis-network graph) |
| `track1_blast_radius/` | Earlier Track 01 prototype (not part of this submission) |

## 3-minute demo script

1. **Problem (20s).** Company knowledge is scattered across docs, tickets and chat. New people can't find who knows what or why a choice was made, and planning starts from scratch every sprint.
2. **Ask (45s).** In the demo (`/w/demo`), tap "Why did we choose Postgres?": a cited answer, and the map lights up. Then tap "Who should I ask about Kafka?": Tomas *knows* Kafka even though Priya *owns* the Event Bus.
3. **Write a sprint plan (40s).** Open **Write a PRD or sprint plan**, choose Sprint plan and Checkout Redesign. The blocker PAY-52 is scheduled first, owners are filled in, and every line is cited. Switch to PRD for Auth Service.
4. **Stays current (30s).** Open **+ Add info** and post the prefilled message from Maya. DEC-1 is marked outdated, and the Ledger sprint plan now includes the CockroachDB rollout.
5. **Your own company (30s).** On the home page, create a workspace, paste two people and a project, and upload the CSV template. It's ready to ask and plan.
6. **Close (15s).** Each company gets its own graph in FalkorDB. Answers and plans come with sources, and the knowledge stays current.

Before recording, use the menu (···) → Reset data in the demo.
