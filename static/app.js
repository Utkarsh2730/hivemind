// Company Brain workspace page: ask, write PRD / sprint plan, add info, and the company map.
const $ = id => document.getElementById(id);
const esc = s => (s ?? '').toString().replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ---------- workspace + API ----------
const SLUG = (location.pathname.match(/^\/w\/([a-z0-9-]+)/) || [null, 'demo'])[1];
const KEY_STORE = 'cb_key_' + SLUG;
let memKey = '', META = null;
function storeKey(k) { memKey = k; try { localStorage.setItem(KEY_STORE, k); } catch (e) {} }
function getKey() { try { return localStorage.getItem(KEY_STORE) || memKey; } catch (e) { return memKey; } }
(function () {
  const m = location.hash.match(/key=([A-Za-z0-9_-]+)/);
  if (m) { storeKey(m[1]); history.replaceState(null, '', location.pathname); }
})();
async function api(path, body) {
  const opts = { headers: { 'X-Workspace-Key': getKey() } };
  if (body !== undefined) { opts.method = 'POST'; opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const resp = await fetch(`/api/w/${SLUG}${path}`, opts);
  let data = {}; try { data = await resp.json(); } catch (e) {}
  if (resp.status === 401) { $('gate').classList.add('open'); throw new Error('locked'); }
  if (resp.status === 404) throw new Error('This workspace does not exist. Check the link.');
  if (!resp.ok) { const d = data.detail; throw new Error(typeof d === 'string' ? d : (Array.isArray(d) ? 'Some fields are too long or missing.' : 'Request failed.')); }
  return data;
}
function toast(html) { $('toast').innerHTML = html; $('toast').classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => $('toast').classList.remove('show'), 5000); }

// ---------- map ----------
const COLORS = { Person: css('--person'), Team: css('--team'), Project: css('--project'), System: css('--system'),
  doc: css('--doc'), ticket: css('--ticket'), message: css('--message'), meeting: css('--meeting'), Decision: css('--decision') };
const SHAPES = { Person: 'dot', Team: 'hexagon', Project: 'diamond', System: 'square', Source: 'dot', Decision: 'star' };
const SIZES = { Person: 16, Team: 18, Project: 18, System: 14, Source: 8, Decision: 15 };
let nodes, edges, network, raw = { nodes: [], edges: [] }, highlightSet = null, citedSet = new Set();
const colorOf = n => (n.type === 'Decision' && n.status === 'superseded') ? '#55556a' : (n.type === 'Source' ? COLORS[n.kind] : COLORS[n.type]);
function nodeView(n) {
  const c = colorOf(n), dim = highlightSet && !highlightSet.has(n.id), cited = citedSet.has(n.id);
  return { id: n.id, label: (n.type === 'Source' || n.type === 'Decision') ? n.id : n.name, shape: SHAPES[n.type] || 'dot',
    size: (SIZES[n.type] || 10) * (cited ? 1.6 : 1),
    color: { background: c, border: cited ? '#fff' : c, highlight: { background: c, border: '#fff' }, hover: { background: c, border: '#fff' } },
    borderWidth: cited ? 3 : 1, opacity: dim ? 0.12 : 1,
    font: { color: dim ? '#3a3a4a' : (n.type === 'Source' ? '#9a9ab0' : '#ececf4'), size: n.type === 'Source' ? 10 : 13, face: 'Inter', strokeWidth: 0 } };
}
function edgeView(e, i) {
  const on = !highlightSet || (highlightSet.has(e.source) && highlightSet.has(e.target));
  return { id: i, from: e.source, to: e.target, label: on && highlightSet ? e.rel.toLowerCase().replace(/_/g, ' ') : '',
    arrows: { to: { enabled: true, scaleFactor: .4 } },
    color: { color: on ? (highlightSet ? '#a99dffcc' : '#ffffff22') : '#ffffff08', highlight: '#a99dff' },
    width: on && highlightSet ? 1.6 : .7, dashes: e.rel === 'SUPERSEDES',
    font: { color: '#a99dff', size: 9, strokeWidth: 0, face: 'Inter', background: '#0b0b12' }, smooth: { type: 'continuous' } };
}
let mapMode = 'full';
async function loadGraph(data) {
  raw = data || await api('/graph');
  mapMode = data ? 'focus' : 'full';
  $('stats').textContent = !raw.nodes.length ? 'The map fills up as you add info' :
    data ? `Showing ${raw.nodes.length} connected things · Show everything to go back` :
    raw.truncated ? `Showing ${raw.nodes.length} of ${raw.total} things (newest) · click any dot` :
    `${raw.nodes.length} things, ${raw.edges.length} connections · click any dot`;
  if (network) { network.destroy(); network = null; }
  nodes = new vis.DataSet(raw.nodes.map(nodeView));
  edges = new vis.DataSet(raw.edges.map(edgeView));
  network = new vis.Network($('graph'), { nodes, edges }, {
    physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -55, springLength: 90, avoidOverlap: .4 }, stabilization: { iterations: 250 } },
    interaction: { hover: true }, layout: { improvedLayout: true } });
  network.on('click', p => p.nodes.length ? inspect(p.nodes[0]) : ($('inspect').style.display = 'none'));
  if (highlightSet) focusOn([...highlightSet]);
}
function restyle() { nodes.update(raw.nodes.map(nodeView)); edges.clear(); edges.add(raw.edges.map(edgeView)); }
async function focusOn(keys) {
  if (raw.truncated || mapMode === 'focus') {  // big workspace: load just the part of the map behind this answer
    const missing = keys.filter(k => !raw.nodes.some(n => n.id === k));
    if (missing.length) { try { highlightSet = new Set(keys); await loadGraph(await api('/graph/focus', { keys: keys.slice(0, 400) })); } catch (e) {} }
  }
  highlightSet = new Set(keys); restyle();
  const present = keys.filter(k => nodes.get(k));
  if (present.length) network.fit({ nodes: present, animation: { duration: 700, easingFunction: 'easeInOutQuad' } });
}
function inspect(key) {
  const n = raw.nodes.find(x => x.id === key); if (!n) return;
  const links = raw.edges.filter(e => e.source === key || e.target === key).length;
  $('inspect').style.display = 'block';
  $('inspect').innerHTML = `<div style="display:flex;gap:6px;align-items:center;color:var(--muted);font-size:11.5px"><i class="dot" style="background:${colorOf(n)}"></i>${esc(n.kind || n.type)} <span class="mono">${esc(n.id.includes(':') ? '' : n.id)}</span></div>
    <b style="display:block;margin:4px 0">${esc(n.name)}</b>
    <div class="muted">${esc((n.detail || '').slice(0, 240))}</div>
    <div style="color:var(--dim);margin-top:6px">${esc(n.date || '')}${n.status ? ' · ' + esc(n.status.replace('_', ' ')) : ''} · ${links} connections</div>`;
}
$('showall').onclick = async () => { highlightSet = null; citedSet = new Set(); if (mapMode === 'focus') await loadGraph(); else { restyle(); network.fit({ animation: true }); } };

// ---------- markdown (answers + generated docs) ----------
function inline(t) {
  return t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/~~(.+?)~~/g, '<del>$1</del>').replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([A-Z]{2,5}-\d+)\]/g, (_, k) => `<span class="cite" data-k="${k}">${k}</span>`);
}
function md(text) {
  const lines = esc(text).split('\n'); let out = '', list = null, i = 0;
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      close();
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      out += '<table><tr>' + cells(l).map(c => `<th>${c}</th>`).join('') + '</tr>';
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { out += '<tr>' + cells(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>'; i++; }
      out += '</table>'; continue;
    }
    let m;
    if ((m = l.match(/^(#{1,3})\s+(.*)/))) { close(); out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; }
    else if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (list !== 'ul') { close(); out += '<ul>'; list = 'ul'; } out += `<li>${inline(m[1])}</li>`; }
    else if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== 'ol') { close(); out += '<ol>'; list = 'ol'; } out += `<li>${inline(m[1])}</li>`; }
    else if (l.trim()) { close(); out += `<p>${inline(l)}</p>`; }
    else close();
    i++;
  }
  close(); return out;
}
function sourceList(cits) {
  return cits.map(c => {
    const col = c.label === 'Decision' ? COLORS.Decision : COLORS[c.kind];
    return `<div class="src" data-k="${c.key}"><div class="t"><i class="dot" style="background:${col}"></i><b>${esc(c.title)}</b>
      ${c.status === 'superseded' ? '<span class="old">outdated</span>' : ''}<span class="m">${esc(c.author || c.kind)} · ${esc(c.date || '')}</span></div>
      <div class="x">${esc(c.text)}</div>
      <div class="acts">${c.label === 'Decision' ? `<button class="mini" data-act="nd" data-key="${c.key}">Not a decision</button>`
        : `<button class="mini" data-act="del" data-key="${c.key}">Remove this item</button>`}</div></div>`;
  }).join('');
}
document.addEventListener('click', async e => {
  const act = e.target.closest('[data-act]');
  if (act) {
    e.stopPropagation();
    const key = act.dataset.key, nd = act.dataset.act === 'nd';
    if (!confirm(nd ? `Mark ${key} as not a decision? Anything it marked outdated becomes current again.` : `Remove ${key} from the brain?`)) return;
    try {
      const r = (await api('/delete', { keys: [key] })).results[0];
      if (r.error) { toast(esc(r.error)); return; }
      act.closest('.src').remove();
      toast(nd ? `${key} removed${r.restored.length ? `; ${r.restored.join(', ')} is current again` : ''}.` : `${key} removed${r.decisions_removed.length ? ` with decision ${r.decisions_removed.join(', ')}` : ''}.`);
      await refresh();
    } catch (err) { if (err.message !== 'locked') toast(esc(err.message)); }
    return;
  }
  const el = e.target.closest('[data-k]'); if (!el) return;
  const k = el.dataset.k, box = el.closest('.view') || document;
  box.querySelectorAll('.src').forEach(s => s.classList.toggle('focus', s.dataset.k === k && !(el.classList.contains('src') && s === el && el.classList.contains('focus'))));
  if (el.classList.contains('cite')) box.querySelector(`.src[data-k="${k}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  if (nodes && nodes.get(k)) { network.selectNodes([k]); network.focus(k, { scale: 1.3, animation: { duration: 500 } }); inspect(k); }
});

// ---------- tabs + menu ----------
function showView(v) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
  document.querySelectorAll('.view').forEach(x => x.classList.toggle('on', x.id === 'v-' + v));
}
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => showView(b.dataset.view));
$('menubtn').onclick = e => { e.stopPropagation(); $('menu').classList.toggle('open'); };
document.addEventListener('click', () => $('menu').classList.remove('open'));

// ---------- ask ----------
const TOOL_TEXT = { search_knowledge: 'Searched docs, tickets and chats', entity_profile: 'Looked up', who_knows: 'Checked who has worked on',
  decision_trail: 'Followed the decision history of', run_cypher: 'Ran a custom map query' };
async function askStream(q, onStep) {
  const resp = await fetch(`/api/w/${SLUG}/ask/stream`, { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Workspace-Key': getKey() }, body: JSON.stringify({ question: q }) });
  if (resp.status === 401) { $('gate').classList.add('open'); throw new Error('locked'); }
  if (!resp.ok || !resp.body) { let d = {}; try { d = await resp.json(); } catch (e) {} throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed.'); }
  const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = '', final = null;
  while (!final) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = (chunk.match(/^event: (.*)$/m) || [])[1], data = (chunk.match(/^data: (.*)$/m) || [])[1];
      if (!ev || !data) continue;
      if (ev === 'step') onStep(JSON.parse(data)); else if (ev === 'answer') final = JSON.parse(data);
    }
  }
  if (!final) throw new Error('The connection was interrupted. Please try again.');
  return final;
}
const stepText = s => `${TOOL_TEXT[s.tool] || s.tool}: <i>${esc(String(Object.values(s.args)[0]).slice(0, 80))}</i> (${s.found} found)`;
async function ask(q) {
  if (!q.trim()) return;
  $('q').value = q; $('go').disabled = true;
  $('out').innerHTML = `<div class="card"><div><span class="spin"></span>Looking through the company map&hellip;</div><ol class="live muted" id="livesteps" style="margin:10px 0 0;padding-left:20px;line-height:1.7;font-size:13px"></ol></div>`;
  const seen = [];
  let r;
  try {
    r = await askStream(q.slice(0, 400), step => {
      $('livesteps')?.insertAdjacentHTML('beforeend', `<li>${stepText(step)}</li>`);
      seen.push(...step.keys); citedSet = new Set(); focusOn([...new Set(seen)]);
    });
  } catch (e) { $('go').disabled = false; if (e.message !== 'locked') $('out').innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  $('go').disabled = false;
  citedSet = new Set(r.cited);
  const steps = r.trace.map(s => `<li>${stepText(s)}</li>`).join('');
  $('out').innerHTML = `<div class="card answer">${md(r.answer)}
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:6px"><details class="how" style="margin:0"><summary>How it found this</summary><ol>${steps || '<li>Answered directly</li>'}</ol></details>${shareBtn()}</div></div>
    ${r.citations.length ? `<div class="h">Sources</div>${sourceList(r.citations)}` : ''}`;
  const sb = $('out').querySelector('[data-share]');
  if (sb) sb.onclick = () => shareToChannel(`Q: ${q}`, r.answer + (r.citations.length ? '\n\nSources:\n' + r.citations.slice(0, 6).map(c => `- [${c.key}] ${c.title}`).join('\n') : ''));
  focusOn(r.highlight);
}
$('go').onclick = () => ask($('q').value);
$('q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask($('q').value); } });

function welcome() {
  const c = META.counts, people = c.Person || 0, items = c.Source || 0;
  if (META.workspace.demo || items) {
    $('out').innerHTML = `<div class="card steps">
      <div class="s"><span class="n">1</span><div><b>Ask a question</b> in plain words, or tap one of the examples above.</div></div>
      <div class="s"><span class="n">2</span><div><b>Check the proof.</b> Every answer links to the original doc, ticket or message, and the map highlights the connections it used.</div></div>
      <div class="s"><span class="n">3</span><div><b>Need a plan?</b> Open <a href="#" onclick="showView('write');return false" style="color:var(--accent2)">Write a PRD or sprint plan</a>.</div></div></div>`;
    return;
  }
  $('out').innerHTML = `<div class="card steps">
    <p style="margin:0 0 14px;font-weight:600">Set up ${esc(META.workspace.name)}</p>
    <div class="s ${people ? 'done' : ''}"><span class="n">${people ? '&#10003;' : '1'}</span><div><b>Add your team &amp; projects</b> so the brain knows who's who.</div></div>
    <div class="s"><span class="n">2</span><div><b>Add info:</b> paste docs, notes, tickets or chats, upload files, or import a GitHub repo.</div></div>
    <div class="s"><span class="n">3</span><div><b>Ask questions</b> and <b>write PRDs and sprint plans</b> from your own data.</div></div>
    <button class="btn" onclick="openDrawer(${people ? 'false' : 'true'})">${people ? 'Add info' : 'Add team &amp; projects'}</button>
    <p class="muted" style="font-size:12.5px;margin:12px 0 0">Keep your private link safe (menu &middot;&middot;&middot; &rarr; Copy private link). It's the only way back in.</p></div>`;
}

// ---------- write PRD / sprint ----------
let KIND = 'prd';
document.querySelectorAll('#kind button').forEach(b => b.onclick = () => {
  KIND = b.dataset.k;
  document.querySelectorAll('#kind button').forEach(x => x.classList.toggle('on', x === b));
  $('g-weeks-wrap').style.display = KIND === 'sprint' ? '' : 'none';
  $('g-goal-label').textContent = KIND === 'sprint' ? 'Sprint goal (optional)' : 'What do you want to build? (optional)';
  $('g-goal').placeholder = KIND === 'sprint' ? 'Leave empty to let the brain pick from blockers and open work' : 'e.g. Finish the Keycloak migration';
  $('g-go').textContent = KIND === 'sprint' ? 'Write sprint plan' : 'Write PRD';
});
let lastDoc = null;
$('g-go').onclick = async () => {
  if (!$('g-project').value) { $('gen').innerHTML = '<div class="card">Add a project first (+ Add info &rarr; Your team &amp; projects).</div>'; return; }
  $('g-go').disabled = true;
  $('gen').innerHTML = `<div class="card"><span class="spin"></span>Reading decisions, tickets and experts, then writing&hellip;</div>`;
  try {
    const r = await api('/generate', { kind: KIND, project: $('g-project').value, goal: $('g-goal').value, weeks: +$('g-weeks').value });
    lastDoc = r;
    citedSet = new Set(r.cited);
    $('gen').innerHTML = `<div class="doctools"><button class="ghost" id="d-copy">Copy</button><button class="ghost" id="d-md">Download .md</button><button class="ghost" id="d-pdf">Save as PDF</button>${shareBtn()}</div>
      <div class="card doc">${md(r.markdown)}<div class="foot">${r.mode === 'claude' ? 'Written by Claude from' : 'Assembled from'} ${r.citations.length} sources in the company map.</div></div>
      <div id="gensrc">${r.citations.length ? `<div class="h">Sources used</div>${sourceList(r.citations)}` : ''}</div>`;
    $('d-copy').onclick = async () => { try { await navigator.clipboard.writeText(r.markdown); toast('Copied as Markdown.'); } catch (e) { toast('Copy failed. Use Download instead.'); } };
    $('d-md').onclick = () => download(`${KIND === 'prd' ? 'PRD' : 'Sprint plan'} - ${r.title}.md`, r.markdown, 'text/markdown');
    $('d-pdf').onclick = () => window.print();
    const sb = $('gen').querySelector('[data-share]');
    if (sb) sb.onclick = () => shareToChannel('', r.markdown);
    focusOn(r.highlight);
  } catch (e) { if (e.message !== 'locked') $('gen').innerHTML = `<div class="card">${esc(e.message)}</div>`; }
  $('g-go').disabled = false;
};

// ---------- add info drawer ----------
function openDrawer(team) {
  $('drawer').classList.add('open'); $('overlay').classList.add('open');
  if (team && !META.workspace.demo) $('sec-team').open = true;
}
function closeDrawer() { $('drawer').classList.remove('open'); $('overlay').classList.remove('open'); }
$('addinfo').onclick = () => openDrawer(!(META && META.counts.Person));
$('dclose').onclick = closeDrawer; $('overlay').onclick = closeDrawer;
$('k-date').value = new Date().toISOString().slice(0, 10);
function setRes(id, html, ok) { $(id).innerHTML = html; $(id).className = 'res ' + (ok ? 'ok' : 'err'); }
function showChange(r) {
  let msg = `Added <b>${r.source}</b>, connected to ${r.mentions.length} people/projects/tools.`;
  if (r.decision) msg += ` New decision: <b>${esc(r.decision.title)}</b>.`;
  if (r.superseded.length) msg += ` <span style="color:#fca5a5">Marked ${r.superseded.join(', ')} as outdated.</span>`;
  return msg;
}
$('k-save').onclick = async () => {
  const text = $('k-text').value.trim(); if (!text) { setRes('k-res', 'Paste some text first.'); return; }
  $('k-save').disabled = true;
  try {
    const r = await api('/knowledge', { kind: $('k-kind').value, text, author: $('k-author').value, title: $('k-title').value,
      date: $('k-date').value, channel: $('k-channel').value, status: $('k-status').value, assignee: $('k-assignee').value, key: $('k-key').value });
    setRes('k-res', showChange(r), true); toast(showChange(r));
    ['k-text', 'k-title', 'k-key', 'k-assignee'].forEach(i => $(i).value = '');
    citedSet = new Set([r.source, ...(r.decision ? [r.decision.key] : [])]);
    highlightSet = new Set([r.source, ...r.mentions, ...(r.decision ? [r.decision.key] : []), ...r.superseded]);
    await refresh();
  } catch (e) { if (e.message !== 'locked') setRes('k-res', esc(e.message)); }
  $('k-save').disabled = false;
};
const lines = id => $(id).value.split('\n').map(l => l.trim()).filter(Boolean).map(l => l.split('|').map(x => x.trim()));
const list = v => (v || '').split(',').map(x => x.trim()).filter(Boolean);
$('e-save').onclick = async () => {
  const people = lines('e-people').map(([name, role, team]) => ({ name, role: role || '', team: team || '' }));
  const projects = lines('e-projects').map(([name, team, lead, uses]) => ({ name, team: team || '', lead: lead || '', uses: list(uses) }));
  const systems = lines('e-systems').map(([name, aliases]) => ({ name, aliases: list(aliases) }));
  if (!people.length && !projects.length && !systems.length) { setRes('e-res', 'Add at least one line.'); return; }
  $('e-save').disabled = true;
  try {
    const c = await api('/entities', { people, projects, systems, teams: [] });
    setRes('e-res', `Saved: ${c.Person || 0} people, ${c.Project || 0} projects, ${c.System || 0} tools. Now paste or upload some info above.`, true);
    ['e-people', 'e-projects', 'e-systems'].forEach(i => $(i).value = '');
    await refresh();
  } catch (e) { if (e.message !== 'locked') setRes('e-res', esc(e.message)); }
  $('e-save').disabled = false;
};

// file import
function parseCSV(text) {
  const rows = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); rows.push(row); row = []; cur = ''; }
    else cur += c;
  }
  if (cur || row.length) { row.push(cur); rows.push(row); }
  const head = (rows.shift() || []).map(h => h.trim().toLowerCase());
  return rows.filter(r => r.some(x => x.trim())).map(r => Object.fromEntries(head.map((h, i) => [h, (r[i] || '').trim()])));
}
const normSource = o => {
  const kind = String(o.kind || o.type || 'doc').toLowerCase();
  return { kind: ['doc', 'ticket', 'message', 'meeting'].includes(kind) ? kind : 'doc', text: String(o.text || o.content || o.body || '').slice(0, 4000),
    title: String(o.title || '').slice(0, 200), author: String(o.author || o.user || '').slice(0, 60), date: String(o.date || '').slice(0, 10),
    channel: String(o.channel || '').slice(0, 40), status: String(o.status || '').slice(0, 20), assignee: String(o.assignee || '').slice(0, 60),
    key: String(o.key || o.id || '').slice(0, 20) };
};
async function importFiles(files) {
  const sources = [], ent = { people: [], projects: [], systems: [], teams: [] }, skipped = [];
  for (const f of files) {
    const text = await f.text(), name = f.name.toLowerCase();
    try {
      if (name.endsWith('.json')) {
        const j = JSON.parse(text);
        if (Array.isArray(j)) sources.push(...j.map(normSource));
        else { ['people', 'projects', 'systems', 'teams'].forEach(k => ent[k].push(...(j[k] || []))); sources.push(...(j.sources || []).map(normSource)); }
      } else if (name.endsWith('.csv')) sources.push(...parseCSV(text).map(normSource));
      else if (name.endsWith('.txt') || name.endsWith('.md'))
        sources.push({ kind: 'doc', title: f.name.replace(/\.(txt|md)$/i, ''), text: text.slice(0, 4000), author: '', date: new Date(f.lastModified).toISOString().slice(0, 10) });
      else skipped.push(f.name);
    } catch (e) { skipped.push(f.name); }
  }
  const valid = sources.filter(s => s.text.trim());
  const hasEnt = ['people', 'projects', 'systems', 'teams'].some(k => ent[k].length);
  if (!valid.length && !hasEnt) { setRes('f-res', 'Nothing to import. Check the file format.' + (skipped.length ? ` Skipped: ${esc(skipped.join(', '))}` : '')); return; }
  setRes('f-res', `<span class="spin"></span>Importing ${valid.length} items&hellip;`, true);
  try {
    if (hasEnt) await api('/entities', ent);
    let added = 0, decisions = 0, superseded = 0, failed = 0;
    for (let i = 0; i < valid.length; i += 200) {
      const r = await api('/import', { sources: valid.slice(i, i + 200) });
      added += r.added; decisions += r.decisions; superseded += r.superseded; failed += r.errors.length;
    }
    setRes('f-res', `Imported ${added} items and found ${decisions} decisions${superseded ? ` (${superseded} replaced older ones)` : ''}.` +
      (failed ? ` ${failed} failed.` : '') + (skipped.length ? ` Skipped: ${esc(skipped.join(', '))}` : ''), true);
    await refresh();
  } catch (e) { if (e.message !== 'locked') setRes('f-res', esc(e.message)); }
}
$('drop').onclick = () => $('files').click();
$('files').onchange = e => { importFiles([...e.target.files]); e.target.value = ''; };
['dragover', 'dragenter'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.remove('over'); }));
$('drop').addEventListener('drop', e => importFiles([...e.dataTransfer.files]));
function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); }
$('tpl-csv').onclick = e => { e.preventDefault(); download('company-brain-template.csv',
  'kind,title,text,author,date,channel,status,assignee\n' +
  'meeting,Architecture review,"We decided to use Postgres for billing because the team knows it well.",Priya Sharma,2026-03-04,,,\n' +
  'message,,"Postgres replicas are lagging again, ping me if you see timeouts.",Arjun Mehta,2026-04-11,#infra,,\n' +
  'ticket,Fix replica lag,"Billing reads time out when replicas lag.",Priya Sharma,2026-04-12,,in_progress,Arjun Mehta\n', 'text/csv'); };
$('tpl-json').onclick = e => { e.preventDefault(); download('company-brain-template.json', JSON.stringify({
  people: [{ name: 'Priya Sharma', role: 'Engineering Manager', team: 'Platform' }, { name: 'Arjun Mehta', role: 'Backend Engineer', team: 'Payments' }],
  projects: [{ name: 'Billing', team: 'Payments', lead: 'Arjun Mehta', uses: ['Postgres', 'Stripe'] }],
  systems: [{ name: 'Postgres', aliases: ['postgresql', 'pg'] }, { name: 'Stripe' }],
  sources: [{ kind: 'meeting', title: 'Architecture review', text: 'We decided to use Postgres for billing because the team knows it well.', author: 'Priya Sharma', date: '2026-03-04' },
    { kind: 'ticket', title: 'Fix replica lag', text: 'Billing reads time out when replicas lag.', author: 'Priya Sharma', date: '2026-04-12', status: 'in_progress', assignee: 'Arjun Mehta' }]
}, null, 2), 'application/json'); };

$('gh-go').onclick = async () => {
  const repo = $('gh-repo').value.trim(); if (!repo) { setRes('gh-res', 'Paste a repository first.'); return; }
  $('gh-go').disabled = true; setRes('gh-res', '<span class="spin"></span>Reading issues, pull requests and comments&hellip;', true);
  try {
    const r = await api('/import/github', { repo });
    setRes('gh-res', `Imported ${r.added} items from ${esc(r.repo)} into project <b>${esc(r.project)}</b>` +
      (r.decisions ? `, found ${r.decisions} decisions` : '') + `. The brain now knows ${r.counts.Person || 0} people.`, true);
    $('gh-repo').value = ''; await refresh();
  } catch (e) { if (e.message !== 'locked') setRes('gh-res', esc(e.message)); }
  $('gh-go').disabled = false;
};

// ---------- connections ----------
let CONN = null;
const PLATFORM = { slack: 'Slack', discord: 'Discord', teams: 'Microsoft Teams', google_chat: 'Google Chat' };
async function openConnections() {
  $('cdrawer').classList.add('open'); $('overlay').classList.add('open');
  ['c-slack-res', 'c-notify-res', 'c-in-res'].forEach(i => $(i).innerHTML = '');
  try { CONN = await api('/connections'); } catch (e) { return; }
  const demo = CONN.demo;
  $('c-demo').style.display = demo ? '' : 'none';
  $('cbody').querySelectorAll('input,button.btn,button.ghost:not(#cclose)').forEach(el => el.disabled = demo);
  if (demo) return;
  $('c-token').placeholder = CONN.slack_token ? `Saved (${CONN.slack_token})` : 'xoxb-...';
  $('c-secret').placeholder = CONN.slack_signing_secret ? 'Saved' : '••••••';
  $('c-notify').placeholder = CONN.notify_url ? `Connected: ${PLATFORM[CONN.notify_platform] || CONN.notify_platform} (${CONN.notify_url})` : $('c-notify').placeholder;
  $('c-decisions').checked = CONN.notify_decisions;
  $('c-inbound').value = CONN.inbound_url;
  $('c-slack-res').innerHTML = CONN.slack_token && CONN.slack_signing_secret
    ? `Connected. Events URL: <span class="mono">${esc(CONN.slack_events_url)}</span>` : '';
}
function closeConnections() { $('cdrawer').classList.remove('open'); $('overlay').classList.remove('open'); }
$('connect').onclick = openConnections; $('menu-connect').onclick = openConnections; $('cclose').onclick = closeConnections;
$('overlay').addEventListener('click', closeConnections);
async function saveConn(body, resId, okMsg) {
  try { CONN = await api('/connections', body); setRes(resId, okMsg, true); await refresh(); openConnections(); }
  catch (e) { if (e.message !== 'locked') setRes(resId, esc(e.message)); }
}
$('c-manifest').onclick = async e => {
  e.preventDefault(); if (!CONN || CONN.demo) return;
  try { await navigator.clipboard.writeText(JSON.stringify(CONN.slack_manifest, null, 2)); toast('Slack app manifest copied. Paste it on api.slack.com/apps.'); }
  catch (err) { prompt('Copy this Slack app manifest:', JSON.stringify(CONN.slack_manifest)); }
};
$('c-save-slack').onclick = () => {
  const body = {};
  if ($('c-token').value.trim()) body.slack_token = $('c-token').value.trim();
  if ($('c-secret').value.trim()) body.slack_signing_secret = $('c-secret').value.trim();
  if (!Object.keys(body).length) { setRes('c-slack-res', 'Paste the bot token and signing secret first.'); return; }
  $('c-token').value = ''; $('c-secret').value = '';
  saveConn(body, 'c-slack-res', 'Slack saved. Invite @Company Brain to channels, then try /brain in Slack.');
};
$('c-import-slack').onclick = async () => {
  setRes('c-slack-res', '<span class="spin"></span>Reading recent messages from channels the bot is in&hellip;', true);
  try { const r = await api('/slack/import', {}); setRes('c-slack-res', `Imported ${r.added} messages and found ${r.decisions} decisions.`, true); await refresh(); }
  catch (e) { if (e.message !== 'locked') setRes('c-slack-res', esc(e.message)); }
};
$('c-save-notify').onclick = () => {
  const body = { notify_decisions: $('c-decisions').checked };
  if ($('c-notify').value.trim()) body.notify_url = $('c-notify').value.trim();
  $('c-notify').value = '';
  saveConn(body, 'c-notify-res', 'Saved. Use "Send a test message" to check it.');
};
$('c-test').onclick = async () => {
  try { await api('/connections/test', {}); setRes('c-notify-res', 'Test message sent. Check your channel.', true); }
  catch (e) { if (e.message !== 'locked') setRes('c-notify-res', esc(e.message)); }
};
$('c-copy-inbound').onclick = async () => { try { await navigator.clipboard.writeText($('c-inbound').value); toast('Webhook URL copied. Keep it private.'); } catch (e) { $('c-inbound').select(); } };
$('c-rotate').onclick = async () => {
  if (!confirm('Make a new webhook URL? Tools using the old one will stop sending.')) return;
  try { CONN = await api('/connections/rotate', {}); $('c-inbound').value = CONN.inbound_url; setRes('c-in-res', 'New URL ready. Update it in your tools.', true); }
  catch (e) { if (e.message !== 'locked') setRes('c-in-res', esc(e.message)); }
};

// Slack export .zip, parsed in the browser
async function importSlackZip(file) {
  if (!window.JSZip) { setRes('zip-res', 'Could not load the zip reader. Check your connection.'); return; }
  setRes('zip-res', '<span class="spin"></span>Reading the export&hellip;', true);
  try {
    const zip = await JSZip.loadAsync(file);
    const users = {};
    const uf = zip.file(/(^|\/)users\.json$/)[0];
    if (uf) JSON.parse(await uf.async('string')).forEach(u => users[u.id] = u.real_name || (u.profile || {}).real_name || u.name);
    const items = [];
    for (const f of zip.file(/\/\d{4}-\d{2}-\d{2}\.json$/)) {
      const parts = f.name.split('/'), channel = '#' + parts[parts.length - 2], day = parts[parts.length - 1].slice(0, 10);
      for (const m of JSON.parse(await f.async('string'))) {
        if (m.type !== 'message' || m.subtype || m.bot_id || !m.text) continue;
        const text = m.text.replace(/<@([UW][A-Z0-9]+)(?:\|[^>]+)?>/g, (_, id) => '@' + (users[id] || id))
          .replace(/<#C[A-Z0-9]+\|([^>]+)>/g, '#$1').replace(/<(https?:[^|>]+)\|([^>]+)>/g, '$2 ($1)').replace(/<(https?:[^>]+)>/g, '$1')
          .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (text.length < 3) continue;
        items.push({ kind: 'message', text: text.slice(0, 4000), author: (users[m.user] || (m.user_profile || {}).real_name || m.user || '').slice(0, 60),
          channel: channel.slice(0, 40), date: day, title: '', status: '', assignee: '', key: '' });
      }
    }
    if (!items.length) { setRes('zip-res', 'No messages found. Is this a Slack export?'); return; }
    items.sort((a, b) => a.date.localeCompare(b.date));
    const recent = items.slice(-600);
    let added = 0, decisions = 0;
    for (let i = 0; i < recent.length; i += 200) {
      setRes('zip-res', `<span class="spin"></span>Importing ${Math.min(i + 200, recent.length)} of ${recent.length} messages&hellip;`, true);
      const r = await api('/import', { sources: recent.slice(i, i + 200) }); added += r.added; decisions += r.decisions;
    }
    setRes('zip-res', `Imported ${added} messages${items.length > recent.length ? ` (the most recent ${recent.length} of ${items.length})` : ''} and found ${decisions} decisions.`, true);
    await refresh();
  } catch (e) { if (e.message !== 'locked') setRes('zip-res', esc(e.message || 'Could not read the zip.')); }
}
$('zipdrop').onclick = () => $('zipfile').click();
$('zipfile').onchange = e => { if (e.target.files[0]) importSlackZip(e.target.files[0]); e.target.value = ''; };
['dragover', 'dragenter'].forEach(ev => $('zipdrop').addEventListener(ev, e => { e.preventDefault(); $('zipdrop').classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => $('zipdrop').addEventListener(ev, e => { e.preventDefault(); $('zipdrop').classList.remove('over'); }));
$('zipdrop').addEventListener('drop', e => { if (e.dataTransfer.files[0]) importSlackZip(e.dataTransfer.files[0]); });

// "Send to channel" for answers and documents
async function shareToChannel(title, markdown) {
  try { const r = await api('/share', { title, markdown }); toast(`Sent to ${PLATFORM[r.platform] || r.platform}.`); }
  catch (e) { if (e.message !== 'locked') toast(esc(e.message)); }
}
const shareBtn = () => META && META.notify ? `<button class="ghost" data-share="1" style="font-size:12px;padding:5px 9px">Send to ${esc(PLATFORM[META.notify] || META.notify)}</button>` : '';

// ---------- menu actions + gate ----------
$('mcp').onclick = () => {
  const cfg = { mcpServers: { 'company-brain': { command: 'python3', args: ['/path/to/mcp_server.py'],
    env: { BRAIN_URL: location.origin, BRAIN_WORKSPACE: SLUG, BRAIN_KEY: META && META.workspace.demo ? '' : getKey() } } } };
  $('mcpcfg').textContent = JSON.stringify(cfg, null, 2); $('mcpmodal').classList.add('open');
};
$('mcpcopy').onclick = async () => { try { await navigator.clipboard.writeText($('mcpcfg').textContent); toast('Config copied.'); } catch (e) { toast('Select the text and copy it.'); } };
$('mcpclose').onclick = () => $('mcpmodal').classList.remove('open');
$('share').onclick = async () => {
  const link = `${location.origin}/w/${SLUG}#key=${getKey()}`;
  try { await navigator.clipboard.writeText(link); toast('Private link copied. Share it only with your team.'); }
  catch (e) { prompt('Copy this private link (share it only with your team):', link); }
};
$('reset').onclick = async () => {
  const demo = META && META.workspace.demo;
  if (!confirm(demo ? 'Restore the demo company to its original data?' : 'Delete ALL data in this workspace? This cannot be undone.')) return;
  try { await api('/reset', {}); } catch (e) { toast(esc(e.message)); return; }
  highlightSet = null; citedSet = new Set(); $('gen').innerHTML = ''; $('out').innerHTML = ''; await refresh();
  toast(demo ? 'Demo data restored.' : 'Workspace cleared.');
};
$('gate-go').onclick = () => {
  const v = $('gate-key').value.trim(), m = v.match(/key=([A-Za-z0-9_-]+)/), k = m ? m[1] : v;
  if (!k) { $('gate-res').textContent = 'Paste the link or key.'; return; }
  storeKey(k); $('gate').classList.remove('open'); init();
};

// ---------- load ----------
async function refresh() {
  try { META = await api('/meta'); } catch (e) { if (e.message !== 'locked') $('out').innerHTML = `<div class="card">${esc(e.message)}</div>`; return false; }
  const m = META;
  document.title = m.workspace.name + ' · Company Brain';
  $('wsname').innerHTML = esc(m.workspace.name.replace(' (demo)', '')) + (m.workspace.demo ? '<span class="tag">demo</span>' : '');
  $('share').style.display = m.workspace.demo ? 'none' : '';
  $('try').innerHTML = m.questions.length ? '<span>Try:</span>' + m.questions.slice(0, 5).map(q => `<button class="chip">${esc(q)}</button>`).join('') : '';
  $('try').querySelectorAll('.chip').forEach(b => b.onclick = () => ask(b.textContent));
  $('people').innerHTML = m.people.map(p => `<option value="${esc(p.name)}">${esc(p.role)}</option>`).join('');
  const sel = $('g-project').value;
  $('g-project').innerHTML = m.projects.length ? m.projects.map(p => `<option value="${p.key}">${esc(p.name)}</option>`).join('') : '<option value="">No projects yet</option>';
  if (sel && m.projects.some(p => p.key === sel)) $('g-project').value = sel;
  $('sec-files').style.display = m.workspace.demo ? 'none' : '';
  $('sec-gh').style.display = m.workspace.demo ? 'none' : '';
  $('connect').title = m.notify ? `Connected: ${PLATFORM[m.notify] || m.notify}` : 'Connect Slack, Jira, Linear, GitHub, Teams...';
  $('sec-team').style.display = m.workspace.demo ? 'none' : '';
  $('demo-note').style.display = m.workspace.demo ? '' : 'none';
  if (m.demo_ingest && !$('k-text').value) {
    const a = m.people.find(p => p.key === m.demo_ingest.author);
    $('k-author').value = a ? a.name : ''; $('k-text').value = m.demo_ingest.text; $('k-channel').value = m.demo_ingest.channel;
  }
  await loadGraph();
  if (!$('out').innerHTML.trim() || $('out').querySelector('.steps')) welcome();
  return true;
}
async function init() {
  if (!(await refresh())) return;
  // Deep links: ?ask=question  or  ?write=prd|sprint&project=project:key&weeks=2
  const qs = new URLSearchParams(location.search);
  if (qs.get('ask')) ask(qs.get('ask'));
  else if (qs.get('write')) {
    showView('write');
    document.querySelector(`#kind button[data-k="${qs.get('write') === 'sprint' ? 'sprint' : 'prd'}"]`).click();
    if (qs.get('project')) $('g-project').value = qs.get('project');
    if (qs.get('weeks')) $('g-weeks').value = qs.get('weeks');
    if (qs.get('goal')) $('g-goal').value = qs.get('goal');
    $('g-go').click();
  }
}
init();
