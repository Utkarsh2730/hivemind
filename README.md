# Company Brain — Track 03 (WeMakeDevs × FalkorDB)

**In one sentence:** a map of the company, where people, projects, documents and chats are dots and the lines show how they connect. You ask a question, it follows the lines to the answer, and it shows you where the answer came from.

1. **Everything is connected.** Who wrote what, who owns what, and which meeting a decision came from.
2. **Ask a question.** The brain follows the connections, like asking around the office, only instantly.
3. **See the proof.** Every answer links to the original doc, ticket or message, and the map highlights the path.
4. **It stays current.** Post a new message and it's connected right away. If it changes an old decision, the old one is marked outdated.

---

An agent that understands how a company works. People, teams, projects, systems, docs, tickets, chat messages, meeting notes and decisions all live in one **FalkorDB** graph. The agent answers questions with clickable sources, shows the path it took through the graph, and keeps the graph current as new messages arrive. When a decision is reversed, the older decision is marked as superseded.

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
| `company_data.py` | Sample company data for "Lumen Pay" (fictional) |
| `brain_ingest.py` | Builds the graph, links entities, ingests live sources and handles superseding |
| `brain_tools.py` | Agent tools: `search_knowledge`, `entity_profile`, `who_knows`, `decision_trail`, `run_cypher`, plus the trace |
| `brain_agent.py` | Claude agent (tool runner) and the graph-only planner. CLI: `python brain_agent.py "question"` |
| `server.py`, `static/index.html` | FastAPI app and the UI (vis-network graph) |
| `track1_blast_radius/` | Earlier Track 01 prototype (not part of this submission) |

## 3-minute demo script

1. **Problem (20s).** Company knowledge is scattered across docs, tickets and chat. New people can't find who knows what or why a choice was made.
2. **Why Postgres? (30s).** Click the first question. Show the answer with citations, the trace, and the decision node lighting up alongside MEET-1, DOC-1 and MSG-1. Click `[MEET-1]` to open the source.
3. **Who should I ask about Kafka? (30s).** Tomas ranks first, with evidence. Point out that Priya *owns* the Event Bus but Tomas *knows* Kafka. Ownership and know-how are different edges in the graph.
4. **What changed about login? (30s).** DEC-3 (Auth0) is shown as superseded by DEC-4 (Keycloak), with the reason and the sources.
5. **Keeping it current (40s).** Post the prefilled message from Maya. The toast shows that DEC-8 was created and DEC-1 superseded. Ask the Postgres question again: the answer now shows the change.
6. **Close (20s).** It's one graph with clear sources, it traces decisions to their origin, and it stays current.

Click **Reset data** before recording.
