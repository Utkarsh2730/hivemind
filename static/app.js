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
async function loadGraph() {
  raw = await api('/graph');
  $('stats').textContent = raw.nodes.length ? `${raw.nodes.length} things, ${raw.edges.length} connections · click any dot` : 'The map fills up as you add info';
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
function focusOn(keys) {
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
$('showall').onclick = () => { highlightSet = null; citedSet = new Set(); restyle(); network.fit({ animation: true }); };

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
      <div class="x">${esc(c.text)}</div></div>`;
  }).join('');
}
document.addEventListener('click', e => {
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
async function ask(q) {
  if (!q.trim()) return;
  $('q').value = q; $('go').disabled = true;
  $('out').innerHTML = `<div class="card"><span class="spin"></span>Looking through the company map&hellip;</div>`;
  let r;
  try { r = await api('/ask', { question: q.slice(0, 400) }); }
  catch (e) { $('go').disabled = false; if (e.message !== 'locked') $('out').innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  $('go').disabled = false;
  citedSet = new Set(r.cited);
  const steps = r.trace.map(s => `<li>${TOOL_TEXT[s.tool] || s.tool}: <i>${esc(String(Object.values(s.args)[0]).slice(0, 80))}</i> (${s.found} found)</li>`).join('');
  $('out').innerHTML = `<div class="card answer">${md(r.answer)}
      <details class="how"><summary>How it found this</summary><ol>${steps || '<li>Answered directly</li>'}</ol></details></div>
    ${r.citations.length ? `<div class="h">Sources</div>${sourceList(r.citations)}` : ''}`;
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
    <div class="s"><span class="n">2</span><div><b>Add info:</b> paste docs, notes, tickets or chats, or upload files.</div></div>
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
    $('gen').innerHTML = `<div class="doctools"><button class="ghost" id="d-copy">Copy</button><button class="ghost" id="d-md">Download .md</button><button class="ghost" id="d-pdf">Save as PDF</button></div>
      <div class="card doc">${md(r.markdown)}<div class="foot">${r.mode === 'claude' ? 'Written by Claude from' : 'Assembled from'} ${r.citations.length} sources in the company map.</div></div>
      <div id="gensrc">${r.citations.length ? `<div class="h">Sources used</div>${sourceList(r.citations)}` : ''}</div>`;
    $('d-copy').onclick = async () => { try { await navigator.clipboard.writeText(r.markdown); toast('Copied as Markdown.'); } catch (e) { toast('Copy failed. Use Download instead.'); } };
    $('d-md').onclick = () => download(`${KIND === 'prd' ? 'PRD' : 'Sprint plan'} - ${r.title}.md`, r.markdown, 'text/markdown');
    $('d-pdf').onclick = () => window.print();
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

// ---------- menu actions + gate ----------
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
  $('try').innerHTML = m.questions.length ? '<span>Try:</span>' + m.questions.slice(0, 4).map(q => `<button class="chip">${esc(q)}</button>`).join('') : '';
  $('try').querySelectorAll('.chip').forEach(b => b.onclick = () => ask(b.textContent));
  $('people').innerHTML = m.people.map(p => `<option value="${esc(p.name)}">${esc(p.role)}</option>`).join('');
  const sel = $('g-project').value;
  $('g-project').innerHTML = m.projects.length ? m.projects.map(p => `<option value="${p.key}">${esc(p.name)}</option>`).join('') : '<option value="">No projects yet</option>';
  if (sel && m.projects.some(p => p.key === sel)) $('g-project').value = sel;
  $('sec-files').style.display = m.workspace.demo ? 'none' : '';
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
const init = refresh;
init();
