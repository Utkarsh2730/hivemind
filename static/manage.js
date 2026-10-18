// Manage-data drawer, access gate, sharing and file import for a Company Brain workspace.
// Relies on globals from index.html: $, esc, api, toast, META, SLUG, getKey, storeKey, init, refresh,
// focusOn, citedSet, showChange.

// ---------- reset & share ----------
$('reset').onclick = async () => {
  const demo = META && META.workspace.demo;
  if (!confirm(demo ? 'Restore the demo company to its original data?' : 'Delete ALL data in this workspace? This cannot be undone.')) return;
  try { await api('/reset', {}); } catch (e) { toast(esc(e.message)); return; }
  highlightSet = null; citedSet = new Set(); await init(); toast(demo ? 'Demo data restored.' : 'Workspace cleared.');
};
$('share').onclick = async () => {
  const link = `${location.origin}/w/${SLUG}#key=${getKey()}`;
  try { await navigator.clipboard.writeText(link); toast('Private access link copied. Share it only with your team.'); }
  catch (e) { prompt('Copy this private access link and share it only with your team:', link); }
};

// ---------- access gate ----------
function openGate() { $('gate').classList.add('open'); }
$('gate-go').onclick = () => {
  const v = $('gate-key').value.trim(); const m = v.match(/key=([A-Za-z0-9_-]+)/); const k = m ? m[1] : v;
  if (!k) { $('gate-res').textContent = 'Paste the link or key.'; return; }
  storeKey(k); $('gate').classList.remove('open'); init();
};

// ---------- drawer ----------
function openDrawer(tab) {
  if (META && META.workspace.demo && tab !== 'add') {
    toast('This is the shared demo. <a href="/" style="color:var(--accent2)">Create your own workspace</a> to add your team and import files.');
    tab = 'add';
  }
  $('drawer').classList.add('open'); $('overlay').classList.add('open'); selectTab(tab || 'team');
}
function closeDrawer() { $('drawer').classList.remove('open'); $('overlay').classList.remove('open'); }
function selectTab(t) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'tab-' + t));
}
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => openDrawer(b.dataset.tab));
$('manage').onclick = () => openDrawer(META && META.counts.Person ? 'add' : 'team');
$('dclose').onclick = closeDrawer; $('overlay').onclick = closeDrawer;
$('k-date').value = new Date().toISOString().slice(0, 10);
$('k-kind').onchange = () => {
  $('k-ticket').style.display = $('k-kind').value === 'ticket' ? 'grid' : 'none';
  $('k-chan').style.display = $('k-kind').value === 'message' ? 'block' : 'none';
};

const lines = id => $(id).value.split('\n').map(l => l.trim()).filter(Boolean).map(l => l.split('|').map(x => x.trim()));
const list = v => (v || '').split(',').map(x => x.trim()).filter(Boolean);
function setRes(id, html, ok) { $(id).innerHTML = html; $(id).className = 'result ' + (ok ? 'ok' : 'err'); }

$('e-save').onclick = async () => {
  const people = lines('e-people').map(([name, role, team]) => ({ name, role: role || '', team: team || '' }));
  const projects = lines('e-projects').map(([name, team, lead, uses]) => ({ name, team: team || '', lead: lead || '', uses: list(uses) }));
  const systems = lines('e-systems').map(([name, aliases]) => ({ name, aliases: list(aliases) }));
  if (!people.length && !projects.length && !systems.length) { setRes('e-res', 'Add at least one line.'); return; }
  $('e-save').disabled = true;
  try {
    const c = await api('/entities', { people, projects, systems, teams: [] });
    setRes('e-res', `Saved. The brain now knows ${c.Person || 0} people, ${c.Team || 0} teams, ${c.Project || 0} projects and ${c.System || 0} tools. Next: <a href="#" onclick="selectTab('add');return false" style="color:var(--accent2)">add knowledge</a>.`, true);
    ['e-people', 'e-projects', 'e-systems'].forEach(i => $(i).value = '');
    await refresh();
  } catch (e) { setRes('e-res', esc(e.message)); }
  $('e-save').disabled = false;
};

$('k-save').onclick = async () => {
  const text = $('k-text').value.trim(); if (!text) { setRes('k-res', 'Paste some text first.'); return; }
  const kind = $('k-kind').value;
  const body = {
    kind, text, author: $('k-author').value, title: $('k-title').value, date: $('k-date').value,
    channel: kind === 'message' ? $('k-channel').value : '', status: kind === 'ticket' ? $('k-status').value : '',
    assignee: kind === 'ticket' ? $('k-assignee').value : '', key: kind === 'ticket' ? $('k-key').value : ''
  };
  $('k-save').disabled = true;
  try {
    const r = await api('/knowledge', body);
    setRes('k-res', showChange(r), true);
    $('k-text').value = ''; $('k-title').value = ''; $('k-key').value = '';
    await refresh();
    citedSet = new Set([r.source, ...(r.decision ? [r.decision.key] : [])]);
    focusOn([r.source, ...r.mentions, ...(r.decision ? [r.decision.key] : []), ...r.superseded]);
  } catch (e) { setRes('k-res', esc(e.message)); }
  $('k-save').disabled = false;
};

// ---------- file import ----------
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
function normSource(o) {
  const kind = String(o.kind || o.type || 'doc').toLowerCase();
  return {
    kind: ['doc', 'ticket', 'message', 'meeting'].includes(kind) ? kind : 'doc',
    text: String(o.text || o.content || o.body || '').slice(0, 4000), title: String(o.title || '').slice(0, 200),
    author: String(o.author || o.user || '').slice(0, 60), date: String(o.date || '').slice(0, 10),
    channel: String(o.channel || '').slice(0, 40), status: String(o.status || '').slice(0, 20),
    assignee: String(o.assignee || '').slice(0, 60), key: String(o.key || o.id || '').slice(0, 20)
  };
}
async function importFiles(files) {
  const sources = [], ent = { people: [], projects: [], systems: [], teams: [] }, skipped = [];
  for (const f of files) {
    const text = await f.text(); const name = f.name.toLowerCase();
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
  const hasEnt = ent.people.length || ent.projects.length || ent.systems.length || ent.teams.length;
  if (!valid.length && !hasEnt) { setRes('f-res', 'Nothing to import. Check the file format.' + (skipped.length ? ` Skipped: ${esc(skipped.join(', '))}` : '')); return; }
  setRes('f-res', `<span class="spin"></span>Importing ${valid.length} items&hellip; this can take a minute.`, true);
  try {
    if (hasEnt) await api('/entities', ent);
    let added = 0, decisions = 0, superseded = 0; const errors = [];
    for (let i = 0; i < valid.length; i += 200) {
      const r = await api('/import', { sources: valid.slice(i, i + 200) });
      added += r.added; decisions += r.decisions; superseded += r.superseded; errors.push(...r.errors);
    }
    setRes('f-res', `Imported ${added} items and found ${decisions} decisions` + (superseded ? ` (${superseded} replaced older ones)` : '') + '.' +
      (errors.length ? ` ${errors.length} failed.` : '') + (skipped.length ? ` Skipped: ${esc(skipped.join(', '))}` : ''), true);
    await refresh();
  } catch (e) { setRes('f-res', esc(e.message)); }
}
$('drop').onclick = () => $('files').click();
$('files').onchange = e => { importFiles([...e.target.files]); e.target.value = ''; };
['dragover', 'dragenter'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.remove('over'); }));
$('drop').addEventListener('drop', e => importFiles([...e.dataTransfer.files]));

function download(name, text, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click();
}
$('tpl-csv').onclick = () => download('company-brain-template.csv',
  'kind,title,text,author,date,channel,status,assignee\n' +
  'meeting,Architecture review,"We decided to use Postgres for billing because the team knows it well.",Priya Sharma,2026-03-04,,,\n' +
  'message,,"Postgres replicas are lagging again, ping me if you see timeouts.",Arjun Mehta,2026-04-11,#infra,,\n' +
  'ticket,Fix replica lag,"Billing reads time out when replicas lag.",Priya Sharma,2026-04-12,,in_progress,Arjun Mehta\n', 'text/csv');
$('tpl-json').onclick = () => download('company-brain-template.json', JSON.stringify({
  people: [{ name: 'Priya Sharma', role: 'Engineering Manager', team: 'Platform' }, { name: 'Arjun Mehta', role: 'Backend Engineer', team: 'Payments' }],
  projects: [{ name: 'Billing', team: 'Payments', lead: 'Arjun Mehta', uses: ['Postgres', 'Stripe'] }],
  systems: [{ name: 'Postgres', aliases: ['postgresql', 'pg'] }, { name: 'Stripe' }],
  sources: [
    { kind: 'meeting', title: 'Architecture review', text: 'We decided to use Postgres for billing because the team knows it well.', author: 'Priya Sharma', date: '2026-03-04' },
    { kind: 'message', text: 'Postgres replicas are lagging again, ping me if you see timeouts.', author: 'Arjun Mehta', date: '2026-04-11', channel: '#infra' }
  ]
}, null, 2), 'application/json');
