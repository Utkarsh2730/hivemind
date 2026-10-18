"""Render branded blog images (diagrams + crisp app screenshots) with headless Chrome.

Usage: .venv/bin/python scripts/make_blog_images.py   (Hivemind must be running at BASE, default http://localhost:8000)
Writes PNGs to docs/blog/.
"""
import os
import subprocess
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "blog")
BASE = os.environ.get("BASE", "http://localhost:8000")
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

CSS = """
<link href="BASE/static/vendor/fonts.css" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0}
body{width:1600px;height:900px;overflow:hidden;font-family:Inter,sans-serif;color:#ecebff;
  background:radial-gradient(900px 520px at 85% 10%,rgba(99,102,241,.32),transparent 65%),
             radial-gradient(700px 420px at 0% 100%,rgba(245,158,11,.12),transparent 70%),linear-gradient(180deg,#13112b,#1b1842);}
body:after{content:"";position:fixed;inset:0;background-image:radial-gradient(rgba(255,255,255,.06) 1px,transparent 1px);background-size:28px 28px;pointer-events:none}
.wrap{position:relative;z-index:1;padding:56px 72px;height:100%}
.k{font:500 15px "JetBrains Mono",monospace;letter-spacing:.08em;color:#f59e0b;text-transform:uppercase;margin-bottom:12px}
h1{font-family:Fraunces,serif;font-weight:600;font-size:52px;letter-spacing:-.02em;line-height:1.05;color:#fff}
h1 em{color:#f59e0b;font-style:italic;font-weight:500}
.sub{color:#b9b5e6;font-size:20px;margin-top:12px;max-width:1100px;line-height:1.45}
.brand{position:absolute;right:72px;bottom:40px;display:flex;align-items:center;gap:10px;font-weight:600;color:#d9d6fb;font-size:18px;z-index:2}
.brand i{width:28px;height:28px;border-radius:7px;background:#f59e0b;display:grid;place-items:center}
svg text{font-family:Inter,sans-serif}
.mono{font-family:"JetBrains Mono",monospace}
</style>
"""
BRAND = '<div class="brand"><i><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#13112b" stroke-width="2.2"><path d="M12 2.5 20.2 7.2v9.6L12 21.5 3.8 16.8V7.2z"/></svg></i>Hivemind</div>'

C = {"person": "#818cf8", "team": "#c4b5fd", "project": "#34d399", "system": "#38bdf8", "source": "#cbd5e1", "decision": "#fb7185", "amber": "#f59e0b"}


def node(x, y, label, kind, r=38, sub=None):
    col = C[kind]
    s = (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{col}22" stroke="{col}" stroke-width="3"/>'
         f'<text x="{x}" y="{y + 6}" text-anchor="middle" font-size="19" font-weight="600" fill="#fff">{label}</text>')
    if sub:
        s += f'<text x="{x}" y="{y + r + 26}" text-anchor="middle" font-size="15" fill="#a9a5d8">{sub}</text>'
    return s


def edge(x1, y1, x2, y2, label="", color="#8f8ad6", width=2.5, dash=False, lx=0, ly=-10, arrow="a"):
    d = ' stroke-dasharray="8 7"' if dash else ""
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"{d} marker-end="url(#{arrow})"/>'
    if label:
        mx, my = (x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly
        s += (f'<rect x="{mx - len(label) * 5.4 - 8}" y="{my - 17}" width="{len(label) * 10.8 + 16}" height="26" rx="6" fill="#1d1a45" stroke="{color}55"/>'
              f'<text x="{mx}" y="{my + 2}" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="{color}">{label}</text>')
    return s


def defs():
    m = ""
    for name, col in [("a", "#8f8ad6"), ("amb", "#f59e0b"), ("red", "#fb7185"), ("grn", "#34d399")]:
        m += (f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
              f'<path d="M0 0L10 5L0 10z" fill="{col}"/></marker>')
    return f"<defs>{m}</defs>"


def page(kicker, title, sub, svg):
    return (f"<!doctype html><html><head><meta charset='utf-8'>{CSS.replace('BASE', BASE)}</head><body><div class='wrap'>"
            f"<div class='k'>{kicker}</div><h1>{title}</h1><div class='sub'>{sub}</div>{svg}</div>{BRAND}</body></html>")


def graph_model():
    s = '<svg width="1456" height="660" style="position:absolute;left:72px;top:220px">' + defs()
    s += edge(240, 262, 240, 135, "MEMBER_OF", lx=-70, ly=0)
    s += edge(278, 95, 680, 95, "OWNS")
    s += edge(758, 95, 1160, 95, "USES")
    s += edge(272, 280, 688, 112, "LEADS", lx=-60, ly=-22)
    s += edge(278, 330, 680, 330, "AUTHORED", ly=-14)
    s += edge(720, 292, 720, 135, "MENTIONS", lx=62, ly=0)
    s += edge(752, 308, 1168, 117, "MENTIONS", lx=30, ly=-18)
    s += edge(758, 330, 1160, 330, "ASSIGNED_TO", ly=-14)
    s += edge(268, 356, 684, 540, "MADE", lx=-40, ly=16)
    s += edge(720, 518, 720, 372, "DECIDED_IN", lx=-76, ly=0)
    # AFFECTS routed around the right side so it crosses nothing
    s += ('<path d="M 760 560 C 1380 560, 1380 300, 1228 128" fill="none" stroke="#fb7185" stroke-width="2.5" marker-end="url(#red)"/>'
          '<rect x="1262" y="455" width="96" height="26" rx="6" fill="#1d1a45" stroke="#fb718555"/>'
          '<text x="1310" y="473" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#fb7185">AFFECTS</text>')
    # SUPERSEDES self-loop on the decision's lower-left
    s += ('<path d="M 690 588 C 600 660, 560 560, 682 556" fill="none" stroke="#fb7185" stroke-width="2.5" stroke-dasharray="8 7" marker-end="url(#red)"/>'
          '<text x="560" y="642" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#fb7185">SUPERSEDES</text>')
    # BLOCKS / REFERENCES self-loop on the source's upper-left
    s += ('<path d="M 688 312 C 610 300, 640 230, 700 296" fill="none" stroke="#8f8ad6" stroke-width="2.5" marker-end="url(#a)"/>'
          '<text x="600" y="246" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#8f8ad6">BLOCKS · REFERENCES</text>')
    s += node(240, 95, "Team", "team") + node(720, 95, "Project", "project") + node(1200, 95, "System", "system", r=40)
    s += node(240, 330, "Person", "person", r=40) + node(720, 330, "Source", "source", r=40)
    s += '<text x="772" y="392" font-size="15" fill="#a9a5d8">doc · ticket · message · meeting</text>'
    s += node(720, 560, "Decision", "decision", r=42) + node(1200, 330, "Person", "person", r=40)
    s += "</svg>"
    return page("Graph model", "One graph for the <em>whole company</em>",
                "People, teams, projects, systems, every document, ticket and message, and the decisions that connect them.", s)


def architecture():
    def box(x, y, w, h, title, lines, col):
        t = "".join(f'<text x="{x + 22}" y="{y + 70 + i * 26}" font-size="17" fill="#c9c6ea">{l}</text>' for i, l in enumerate(lines))
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="#1d1a45" stroke="{col}" stroke-width="2.5"/>'
                f'<text x="{x + 22}" y="{y + 40}" font-size="22" font-weight="700" fill="#fff">{title}</text>{t}')
    s = '<svg width="1456" height="620" style="position:absolute;left:72px;top:220px">' + defs()
    s += box(0, 20, 330, 130, "Web app", ["Ask · Documents · Risks", "live steps + graph view"], "#818cf8")
    s += box(0, 175, 330, 130, "Slack · Teams · Discord", ["events · /hivemind", "decision alerts"], "#818cf8")
    s += box(0, 330, 330, 130, "Jira · Linear · GitHub", ["webhooks · repo import"], "#818cf8")
    s += box(0, 485, 330, 120, "Claude Desktop / Cursor", ["via MCP server"], "#818cf8")
    s += box(470, 230, 300, 160, "FastAPI server", ["workspaces · auth", "rate limits · streaming"], "#f59e0b")
    for y in (85, 240, 395, 545):
        s += edge(330, y, 466, 310, color="#8f8ad6")
    s += box(900, 40, 300, 150, "Agent", ["Claude tool use", "or graph-only planner", "read-only tools"], "#34d399")
    s += box(900, 235, 300, 150, "Planner", ["PRDs · sprint plans", "from BLOCKS chains"], "#34d399")
    s += box(900, 430, 300, 150, "Ingestion", ["entity linking", "decision detection"], "#34d399")
    for y in (115, 310, 505):
        s += edge(770, 310, 896, y, color="#f59e0b", arrow="amb")
    s += ('<ellipse cx="1360" cy="190" rx="92" ry="26" fill="#2b2770" stroke="#f59e0b" stroke-width="2.5"/>'
          '<path d="M1268 460 A 92 26 0 0 0 1452 460" fill="#2b2770" stroke="#f59e0b" stroke-width="2.5"/>'
          '<rect x="1268" y="190" width="184" height="270" fill="#2b2770"/><line x1="1268" y1="190" x2="1268" y2="460" stroke="#f59e0b" stroke-width="2.5"/>'
          '<line x1="1452" y1="190" x2="1452" y2="460" stroke="#f59e0b" stroke-width="2.5"/>'
          '<ellipse cx="1360" cy="190" rx="92" ry="26" fill="#352f86" stroke="#f59e0b" stroke-width="2.5"/>'
          '<text x="1360" y="280" text-anchor="middle" font-size="24" font-weight="700" fill="#fff">FalkorDB</text>'
          '<text x="1360" y="310" text-anchor="middle" font-size="16" fill="#c9c6ea">one graph</text>'
          '<text x="1360" y="332" text-anchor="middle" font-size="16" fill="#c9c6ea">per company</text>'
          '<text x="1360" y="372" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#f59e0b">Cypher · full-text</text>'
          '<text x="1360" y="394" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#f59e0b">graph algorithms</text>')
    for y in (115, 310, 505):
        s += edge(1200, y, 1262, 310, color="#f59e0b", arrow="amb")
    s += "</svg>"
    return page("Architecture", "Every answer is a <em>graph traversal</em>",
                "Clients talk to one API; the agent, planner and ingestion all read and write the same FalkorDB graph.", s)


def expertise():
    s = '<svg width="1456" height="640" style="position:absolute;left:72px;top:268px">' + defs()
    tom = (150, 290)
    kaf = (820, 290)
    s += node(*kaf, "Kafka", "system", r=50)
    ev = [(430, 80, "DOC-3", "runbook", "AUTHORED"), (430, 290, "MSG-2", "library v1", "AUTHORED"),
          (430, 500, "MSG-4", "\u201cThanks @tomas\u201d", "THANKED"), (620, 545, "PLAT-21", "upgrade ticket", "ASSIGNED")]
    for x, y, k, sub, rel in ev:
        s += edge(tom[0] + 48, tom[1], x - 42, y, rel, color="#f59e0b", arrow="amb", width=3,
                  lx=(-40 if k != "PLAT-21" else 60) if y != 290 else 0, ly=-14 if y <= 290 else (18 if k == "MSG-4" else 30))
        s += edge(x + 42, y, kaf[0] - 52, kaf[1], "MENTIONS" if k == "DOC-3" else "", color="#8f8ad6", ly=-14)
        s += node(x, y, k, "source", r=40, sub=sub)
    s += node(*tom, "Tomas", "person", r=48, sub="Senior Platform Engineer")
    s += node(1290, 120, "Priya", "person", r=46)
    s += '<text x="1232" y="126" text-anchor="end" font-size="15" fill="#a9a5d8">Platform Eng. Manager</text>'
    s += node(1290, 450, "Event Bus", "project", r=52)
    s += edge(1290, 168, 1290, 396, "LEADS", lx=48, ly=0, dash=True)
    s += edge(1238, 436, 872, 302, "USES", dash=True, ly=-14)
    s += ('<rect x="980" y="0" width="200" height="40" rx="20" fill="#f59e0b"/>'
          '<text x="1080" y="27" text-anchor="middle" font-size="18" font-weight="700" fill="#13112b">knows: Tomas</text>'
          '<rect x="1200" y="0" width="200" height="40" rx="20" fill="none" stroke="#8f8ad6" stroke-width="2"/>'
          '<text x="1300" y="27" text-anchor="middle" font-size="18" font-weight="600" fill="#c9c6ea">owns: Priya</text>')
    s += "</svg>"
    return page("Deep dive · who_knows", "Knowing is not <em>owning</em>",
                "Expertise is scored from evidence paths — what someone wrote, was assigned and was thanked for — and shown next to formal ownership.", s)


def decisions():
    s = '<svg width="1456" height="620" style="position:absolute;left:72px;top:230px">' + defs()
    s += '<line x1="40" y1="300" x2="1400" y2="300" stroke="#3b3680" stroke-width="3"/>'
    s += '<text x="40" y="332" font-size="16" font-family="JetBrains Mono" fill="#a9a5d8">MAR 2026</text>'
    s += '<text x="1400" y="332" text-anchor="end" font-size="16" font-family="JetBrains Mono" fill="#a9a5d8">OCT 2026</text>'
    s += ('<rect x="80" y="130" width="380" height="140" rx="18" fill="#1d1a45" stroke="#64618f" stroke-width="2.5"/>'
          '<text x="104" y="172" font-size="16" font-family="JetBrains Mono" fill="#a9a5d8">DEC-1 · OUTDATED</text>'
          '<text x="104" y="210" font-size="22" font-weight="700" fill="#a9a5d8" text-decoration="line-through">Use Postgres for the ledger</text>'
          '<text x="104" y="244" font-size="16" fill="#8f8ad6">by Arjun Rao, Maya Chen</text>')
    s += ('<rect x="880" y="130" width="440" height="140" rx="18" fill="#1d1a45" stroke="#f59e0b" stroke-width="3"/>'
          '<text x="904" y="172" font-size="16" font-family="JetBrains Mono" fill="#f59e0b">DEC-8 · CURRENT</text>'
          '<text x="904" y="210" font-size="22" font-weight="700" fill="#fff">Move the ledger to CockroachDB</text>'
          '<text x="904" y="244" font-size="16" fill="#c9c6ea">by Maya Chen</text>')
    s += ('<path d="M 878 200 C 720 120, 620 120, 464 196" fill="none" stroke="#fb7185" stroke-width="3" stroke-dasharray="9 8" marker-end="url(#red)"/>'
          '<rect x="590" y="108" width="170" height="30" rx="8" fill="#13112b" stroke="#fb718566"/>'
          '<text x="675" y="129" text-anchor="middle" font-size="15" font-family="JetBrains Mono" fill="#fb7185">SUPERSEDES</text>')
    for i, (k, t) in enumerate([("MEET-1", "Architecture review"), ("DOC-1", "ADR-007"), ("MSG-1", "Benchmarks")]):
        x = 60 + i * 150
        s += (f'<rect x="{x}" y="420" width="136" height="70" rx="12" fill="#1d1a45" stroke="#cbd5e155"/>'
              f'<text x="{x + 68}" y="450" text-anchor="middle" font-size="15" font-family="JetBrains Mono" fill="#e2e8f0">{k}</text>'
              f'<text x="{x + 68}" y="474" text-anchor="middle" font-size="13" fill="#a9a5d8">{t}</text>')
        s += edge(x + 68, 418, 200 + (i - 1) * 60, 274, "", color="#8f8ad6")
    s += ('<rect x="980" y="420" width="240" height="70" rx="12" fill="#1d1a45" stroke="#cbd5e155"/>'
          '<text x="1100" y="450" text-anchor="middle" font-size="15" font-family="JetBrains Mono" fill="#e2e8f0">LIVE message</text>'
          '<text x="1100" y="474" text-anchor="middle" font-size="13" fill="#a9a5d8">“we decided to move…”</text>')
    s += edge(1100, 418, 1100, 274, "DECIDED_IN", lx=70, ly=0)
    s += ('<rect x="480" y="352" width="120" height="26" rx="6" fill="#1d1a45" stroke="#8f8ad655"/>'
          '<text x="540" y="370" text-anchor="middle" font-size="14" font-family="JetBrains Mono" fill="#8f8ad6">DECIDED_IN</text>')
    s += ('<text x="40" y="600" font-size="18" fill="#c9c6ea">New decision on the same system → the old one is marked outdated automatically.  '
          '<tspan fill="#f59e0b">Wrong? Remove it and DEC-1 is restored.</tspan></text>')
    s += "</svg>"
    return page("Deep dive · decision_trail", "Decisions that <em>stay current</em>",
                "Every decision links to the meeting, doc or message that recorded it — and to the decision that replaced it.", s)


def pipeline():
    steps = [("git push / release", "#818cf8"), ("21 tests + 10/10 eval\nvs real FalkorDB", "#34d399"),
             ("docker compose up\n+ smoke test", "#34d399"), ("build offline\nbundle (204 MB)", "#f59e0b"),
             ("delete images,\nreinstall like a judge", "#f59e0b"), ("smoke test again\n→ attach to release", "#34d399")]
    s = '<svg width="1456" height="560" style="position:absolute;left:72px;top:260px">' + defs()
    w, gap = 210, 39
    for i, (t, col) in enumerate(steps):
        x = i * (w + gap)
        s += f'<rect x="{x}" y="120" width="{w}" height="170" rx="18" fill="#1d1a45" stroke="{col}" stroke-width="2.5"/>'
        s += f'<circle cx="{x + 34}" cy="154" r="17" fill="{col}"/><text x="{x + 34}" y="160" text-anchor="middle" font-size="16" font-weight="700" fill="#13112b">{i + 1}</text>'
        for j, line in enumerate(t.split("\n")):
            s += f'<text x="{x + 20}" y="{216 + j * 28}" font-size="19" font-weight="600" fill="#fff">{line}</text>'
        if i < len(steps) - 1:
            s += edge(x + w + 2, 205, x + w + gap - 4, 205, color="#8f8ad6")
    checks = ["health check", "landing page", "bundled assets (offline)", "demo data (27 sources)", "cited answer (Tomas, DOC-3)",
              "knowledge risks (graph algorithms)", "sprint plan (PAY-52 first)", "new workspace"]
    for i, c in enumerate(checks):
        x, y = (i % 4) * 360, 360 + (i // 4) * 48
        s += f'<text x="{x}" y="{y}" font-size="19" fill="#c9c6ea"><tspan fill="#34d399" font-weight="700">✓</tspan>  {c}</text>'
    s += "</svg>"
    return page("Shipping offline", "Verified <em>like a judge</em> would run it",
                "GitHub Actions builds the air-gapped bundle, reinstalls it from scratch and smoke-tests it before it reaches a release.", s)


def chrome_shot(url_or_file, out, w=1600, h=900, scale=2, light=True, budget=12000):
    prof = tempfile.mkdtemp(prefix="cb-blog-")
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-color-profile=srgb",
            f"--force-device-scale-factor={scale}", f"--user-data-dir={prof}", f"--window-size={w},{h}",
            f"--virtual-time-budget={budget}", f"--screenshot={out}"]
    if light:
        args.append("--blink-settings=preferredColorScheme=1")
    subprocess.run(args + [url_or_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    print("  ", os.path.relpath(out, ROOT), os.path.getsize(out) // 1024, "KB")


def main():
    os.makedirs(OUT, exist_ok=True)
    urllib.request.urlopen(urllib.request.Request(BASE + "/api/w/demo/reset", data=b"{}", method="POST",
                                                  headers={"Content-Type": "application/json"}), timeout=60)
    tmp = tempfile.mkdtemp(prefix="cb-blog-html-")
    print("Diagrams:")
    for name, fn in [("01-graph-model", graph_model), ("02-architecture", architecture), ("03-knowing-vs-owning", expertise),
                     ("04-decisions-stay-current", decisions), ("05-offline-pipeline", pipeline)]:
        path = os.path.join(tmp, name + ".html")
        open(path, "w").write(fn())
        chrome_shot("file://" + path, os.path.join(OUT, name + ".png"), light=False, budget=3000)
    print("Screenshots:")
    q = urllib.parse.quote
    shots = [("10-ask-kafka", f"/w/demo?ask={q('Who should I ask about Kafka consumer lag?')}"),
             ("11-decision-history", f"/w/demo?ask={q('What changed about customer login, and why?')}"),
             ("12-knowledge-risks", f"/w/demo?ask={q('Where are our biggest knowledge risks?')}"),
             ("13-sprint-plan", "/w/demo?write=sprint&project=project:checkout"),
             ("14-landing", "/")]
    for name, path in shots:
        chrome_shot(BASE + path, os.path.join(OUT, name + ".png"), w=1440, h=900, scale=2, light=True, budget=15000)


if __name__ == "__main__":
    import urllib.parse
    main()
