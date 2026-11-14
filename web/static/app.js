/* SnapRecall frontend. No framework and nothing loaded from the internet. All text that comes from
   the server (file names, recognized text, folder paths) is inserted as text, never as HTML. */
'use strict';

const ALL = '__all__';
const INDIVIDUAL = 'snaprecall:individual';

// ---- small helpers -----------------------------------------------------------------------
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (['value', 'checked', 'disabled', 'selected', 'hidden'].includes(key)) el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  const add = (kid) => {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) kid.forEach(add);
    else el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  };
  kids.forEach(add);
  return el;
}

// Replace an element's children with `kids`, flattening arrays and skipping empty values like h() does.
function fill(el, ...kids) {
  const holder = h('div', {}, kids);
  el.replaceChildren(...holder.childNodes);
}

const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/>',
  external: '<path d="M14 3h7v7"/><path d="M10 14L21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  back: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
};

function icon(name, size = 18) {
  const t = document.createElement('template');
  t.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return t.content.firstChild;
}

async function api(path, { method = 'GET', body } = {}) {
  const options = { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'SnapRecall' } };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    const error = new Error((data && data.error) || 'Something went wrong. Please try again.');
    error.status = response.status;
    throw error;
  }
  return data;
}

const fmtDate = (ms) => new Date(ms).toLocaleString(undefined,
  { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const fmtScan = (utc) => {
  if (!utc) return null;
  const d = new Date(utc.replace(' ', 'T') + 'Z');
  return isNaN(d) ? utc : fmtDate(d.getTime());
};
const fmtKb = (bytes) => `${Math.round(bytes / 1024)} KB`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const folderLabel = (p) => (p === ALL ? 'All folders' : p === INDIVIDUAL ? 'Individual screenshots'
  : (p.split(/[\\/]/).filter(Boolean).pop() || p));

// ---- dialogs ---------------------------------------------------------------------------------
function askDialog({ title, text, fields = [], confirm = 'OK', danger = false }) {
  const dialog = document.getElementById('dialog');
  return new Promise((resolve) => {
    // Answer from the handlers themselves; the dialog's own close event is only a fallback (some
    // embedded browsers never deliver it).
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const inputs = fields.map((f) => h('input', { type: f.type || 'text', name: f.name, value: f.value || '',
      placeholder: f.placeholder || '', autocomplete: 'off', required: f.required !== false }));
    const form = h('form', { method: 'dialog' },
      h('h3', { text: title }), text ? h('p', { text }) : null,
      fields.map((f, i) => h('label', { class: 'field' }, h('span', { text: f.label }), inputs[i])),
      h('div', { class: 'actions' },
        h('button', { class: 'btn', type: 'button', text: 'Cancel', onclick: () => finish(null) }),
        h('button', { class: `btn ${danger ? 'danger solid' : 'primary'}`, type: 'submit', text: confirm })));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      finish(Object.fromEntries(fields.map((f, i) => [f.name, inputs[i].value])));
    });
    dialog.replaceChildren(form);
    dialog.addEventListener('cancel', () => finish(null), { once: true });  // the Escape key
    dialog.addEventListener('close', () => finish(null), { once: true });
    dialog.showModal();
    (inputs[0] || form.querySelector('button[type=submit]')).focus();
  });
}

// ---- state -------------------------------------------------------------------------------------
const S = {
  session: null, library: null, folder: ALL, q: '', when: 'any', start: '', end: '', sort: 'Best match',
  result: null, searchSeq: 0, jobs: { active: [], recent: [] }, dismissed: new Set(), loadedAt: Date.now(),
  focusFolder: null, notice: null, detailPath: null, tick: 0, timer: null,
};
const app = () => document.getElementById('app');

// ---- login -----------------------------------------------------------------------------------------
function showLogin(notice) {
  clearInterval(S.timer);
  S.timer = null; S.library = null; S.result = null; S.jobs = { active: [], recent: [] };
  const features = [
    ['search', 'Search by memory', 'Type words that were on screen, or describe what it looked like.'],
    ['lock', 'Stays on this computer', 'Screenshots are indexed locally. Nothing is uploaded unless you turn on backup for a folder.'],
    ['copy', 'Copy the original', 'Put the full-resolution image on your clipboard and paste it anywhere.'],
  ];
  const message = h('div', { class: 'banner error', hidden: true, role: 'alert' });
  const note = notice ? h('div', { class: 'banner' }, notice) : null;
  let mode = 'in';
  const body = h('div');
  const show = (error) => { message.hidden = !error; message.textContent = error || ''; };
  const run = async (promise) => {
    show('');
    try { await promise; await enterApp(); } catch (err) { show(err.message); }
  };
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const draw = () => {
    tabs.replaceChildren(...[['in', 'Sign in'], ['new', 'Create account']].map(([key, label]) =>
      h('button', { class: 'tab', role: 'tab', type: 'button', 'aria-selected': String(mode === key), text: label,
        onclick: () => { mode = key; show(''); draw(); } })));
    if (mode === 'in') {
      const name = h('input', { type: 'text', autocomplete: 'username', required: true });
      const pw = h('input', { type: 'password', autocomplete: 'current-password', required: true });
      body.replaceChildren(h('form', {
        onsubmit: (e) => { e.preventDefault(); run(api('/api/session/login', { method: 'POST', body: { username: name.value, password: pw.value } })); },
      }, h('label', { class: 'field' }, h('span', { text: 'Username' }), name),
        h('label', { class: 'field' }, h('span', { text: 'Password' }), pw),
        h('button', { class: 'btn primary block', type: 'submit', text: 'Sign in' })));
    } else {
      const name = h('input', { type: 'text', autocomplete: 'username', required: true });
      const pw = h('input', { type: 'password', autocomplete: 'new-password', required: true });
      const again = h('input', { type: 'password', autocomplete: 'new-password', required: true });
      const claim = S.session.canClaimLegacy
        ? h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: true, id: 'claim' }),
          'Add the library already on this computer to this account') : null;
      body.replaceChildren(h('form', {
        onsubmit: (e) => {
          e.preventDefault();
          run(api('/api/session/register', { method: 'POST', body: {
            username: name.value, password: pw.value, confirm: again.value,
            claimLegacy: claim ? claim.querySelector('input').checked : false } }));
        },
      }, h('label', { class: 'field' }, h('span', { text: 'Username' }), name),
        h('label', { class: 'field' }, h('span', { text: 'Password (at least 8 characters)' }), pw),
        h('label', { class: 'field' }, h('span', { text: 'Confirm password' }), again), claim,
        h('button', { class: 'btn primary block', type: 'submit', text: 'Create account' })));
    }
  };
  draw();
  app().replaceChildren(h('div', { class: 'login' },
    h('div', { class: 'hero' },
      h('img', { src: '/static/icon.svg', width: 44, height: 44, alt: '' }),
      h('h1', {}, 'Find any screenshot by ', h('span', { class: 'grad', text: 'describing it.' })),
      h('p', { text: 'SnapRecall reads the text in your screenshots and compares what they show with your description, so you can look for one the way you remember it.' }),
      h('ul', { class: 'features' }, features.map(([ic, title, text]) =>
        h('li', {}, h('div', { class: 'ic' }, icon(ic)), h('div', {}, h('b', { text: title }), h('span', { text })))))),
    h('div', { class: 'card' },
      h('h2', { text: 'Welcome' }), h('p', { class: 'muted small', text: 'Sign in to keep your library between sessions.' }),
      note, message, tabs, body,
      h('p', { class: 'muted small', text: 'Accounts are stored on this computer. Passwords are saved only as secure hashes, and a forgotten password can’t be recovered.' }),
      h('div', { class: 'or', text: 'or' }),
      h('button', { class: 'btn block', type: 'button', text: 'Continue as guest',
        onclick: () => run(api('/api/session/guest', { method: 'POST' })) }),
      h('p', { class: 'muted small', text: 'Guest libraries are temporary. The search data SnapRecall builds is deleted when you close this window, sign out, or stop the app. Your screenshot files are never deleted.' }))));
}

// ---- the app shell ----------------------------------------------------------------------------------
async function enterApp() {
  S.session = await api('/api/session');
  if (!S.session.user) return showLogin();
  S.folder = ALL; S.q = ''; S.when = 'any'; S.sort = 'Best match'; S.notice = null;
  buildShell();
  await refreshLibrary();
  await refreshJobs();
  await route();
  clearInterval(S.timer);
  S.timer = setInterval(tick, 1000);
}

function buildShell() {
  const search = h('input', { type: 'search', class: 'search', placeholder: 'Describe what you remember…',
    'aria-label': 'Search your screenshots', value: S.q, id: 'q' });
  let debounce = null;
  search.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { S.q = search.value; if (!S.detailPath) runSearch(); }, 300);
  });
  const when = h('select', { 'aria-label': 'When', id: 'when', onchange: (e) => {
    S.when = e.target.value; document.getElementById('custom').hidden = S.when !== 'custom'; runSearch(); } },
  [['any', 'Any time'], ['today', 'Today'], ['7d', 'Past 7 days'], ['30d', 'Past 30 days'], ['year', 'This year'],
    ['custom', 'Custom range…']].map(([v, t]) => h('option', { value: v, text: t })));
  const sort = h('select', { 'aria-label': 'Sort by', id: 'sort', onchange: (e) => { S.sort = e.target.value; runSearch(); } },
    S.session.sortOptions.map((o) => h('option', { value: o, text: o })));
  const start = h('input', { type: 'date', 'aria-label': 'From', onchange: (e) => { S.start = e.target.value; runSearch(); } });
  const end = h('input', { type: 'date', 'aria-label': 'To', onchange: (e) => { S.end = e.target.value; runSearch(); } });
  app().replaceChildren(h('div', { class: 'shell' },
    h('aside', { class: 'sidebar', id: 'sidebar', 'aria-label': 'Library' }),
    h('main', { class: 'main' },
      h('div', { class: 'topbar', id: 'topbar' }, h('div', { class: 'search' }, search), when, sort,
        h('div', { class: 'custom', id: 'custom', hidden: true }, 'Between', start, 'and', end)),
      h('div', { id: 'jobs' }), h('div', { id: 'notice' }), h('div', { id: 'content' }))));
}

async function refreshLibrary() {
  S.library = await api('/api/library');
  const known = S.library.folders.map((f) => f.path);
  if (S.focusFolder && known.includes(S.focusFolder)) { S.folder = S.focusFolder; S.focusFolder = null; }
  if (S.folder !== ALL && !known.includes(S.folder)) S.folder = known.length ? known[0] : ALL;
  if (S.folder === ALL && known.length === 1) S.folder = known[0];
  renderSidebar();
}

function currentInfo() { return S.library.folders.find((f) => f.path === S.folder) || null; }

function renderSidebar() {
  const lib = S.library, info = currentInfo(), guest = lib.guest;
  const known = lib.folders.map((f) => f.path);
  const scope = info ? (info.individual ? 'these screenshots' : 'this folder') : 'all folders';
  const options = [...(known.length > 1 ? [ALL] : []), ...known];
  const select = h('select', { 'aria-label': 'Current folder', onchange: async (e) => {
    S.folder = e.target.value; location.hash = '';
    if (S.folder !== ALL) api('/api/library/open', { method: 'POST', body: { folder: S.folder } }).catch(() => {});
    renderSidebar(); route();
  } }, options.map((p) => h('option', { value: p, text: folderLabel(p), selected: p === S.folder })));
  const models = S.session.models;
  const state = (on) => (on ? 'on' : models.loading ? 'starting…' : 'off');
  fill(document.getElementById('sidebar'),
    h('div', { class: 'brand' }, h('img', { src: '/static/icon.svg', width: 28, height: 28, alt: '' }), 'SnapRecall'),
    h('div', { class: 'user' },
      h('div', { class: guest ? 'avatar guest' : 'avatar', text: guest ? 'G' : lib.username.slice(0, 1).toUpperCase() }),
      h('div', {}, h('div', {}, guest ? 'Guest' : lib.username, guest ? h('span', { class: 'badge', text: 'Temporary' }) : null),
        h('div', { class: 'muted small', text: guest ? 'Deleted when this session ends' : 'Local account' }))),
    guest ? h('p', { class: 'muted small', text: 'Guest libraries are temporary. The search data SnapRecall builds is deleted when you close this window, sign out, or stop the app. Your screenshot files are never deleted.' }) : null,
    h('button', { class: 'btn block', type: 'button', onclick: signOut }, icon('logout', 16), guest ? 'End guest session' : 'Sign out'),
    h('div', { class: 'section-label', text: 'Library' }),
    known.length ? [select, h('div', { class: 'path', text: info ? (info.individual ? 'Screenshots you chose one by one' : info.path) : `Searching ${known.length} folders` })] : null,
    h('button', { class: 'btn primary block', type: 'button', id: 'add', onclick: addScreenshots,
      title: 'Pick folders, individual screenshots, or both. Folders include their subfolders. Files stay where they are.' },
    icon('plus', 16), 'Add screenshots…'),
    h('button', { class: 'btn ghost block small', type: 'button', onclick: addByPath, text: 'Or paste a folder path…' }),
    known.length ? h('button', { class: 'btn block', type: 'button', onclick: () => reindex(),
      disabled: S.jobs.active.length > 0 }, icon('refresh', 16), `Re-index ${scope}`) : null,
    h('div', { class: 'section-label', text: 'Preferences' }),
    h('details', { class: 'settings' }, h('summary', { text: 'Settings' }), h('div', {},
      h('div', { class: 'muted small', text: 'Index location' }), h('div', { class: 'code', text: lib.indexDir }),
      h('div', { class: 'muted small', text: 'Set SNAPRECALL_HOME to change where accounts and libraries are kept.' }),
      h('div', { class: 'muted small', text: `Text recognition: ${state(models.ocr)} · Visual search: ${state(models.visual)} · Meaning: ${state(models.textMeaning)}` }),
      known.length ? h('button', { class: 'btn danger block', type: 'button', onclick: deleteAll, text: 'Delete all screenshots…' }) : null,
      lib.removedCount ? h('button', { class: 'btn block', type: 'button', onclick: restoreRemoved,
        text: `Restore ${lib.removedCount} deleted screenshots` }) : null,
      info ? h('button', { class: 'btn block', type: 'button', onclick: forgetFolder,
        text: info.individual ? 'Remove these from the library' : 'Remove folder from index' }) : null,
      !guest ? h('button', { class: 'btn danger block', type: 'button', onclick: deleteAccount, text: 'Delete this account…' }) : null)));
}

// ---- library actions ------------------------------------------------------------------------------------
function flash(message, kind = 'error') {
  S.notice = message ? { message, kind } : null;
  const box = document.getElementById('notice');
  if (!box) return;
  box.replaceChildren(S.notice ? h('div', { class: `banner ${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('div', { class: 'grow', text: message }),
    h('button', { class: 'btn ghost', type: 'button', text: 'Dismiss', onclick: () => flash(null) })) : '');
}

async function startIndex(body) {
  try {
    await api('/api/library/index', { method: 'POST', body });
    if (body.folders.length) S.focusFolder = body.folders[0];
    else if (body.files.length) S.focusFolder = INDIVIDUAL;
    await refreshJobs();
    await refreshLibrary();
  } catch (err) { flash(err.message); }
}

async function addScreenshots() {
  const button = document.getElementById('add');
  button.disabled = true;
  flash('A window opened on this computer to choose screenshots. It may be behind this one.', 'ok');
  try {
    const info = currentInfo();
    const picked = await api('/api/library/pick', { method: 'POST',
      body: { start: info && !info.individual ? info.path : null } });
    flash(null);
    if (picked.folders.length || picked.files.length) await startIndex(picked);
  } catch (err) { flash(err.message); } finally { button.disabled = false; }
}

async function addByPath() {
  const values = await askDialog({ title: 'Add a folder', text: 'Paste the full path of a folder of screenshots. It is indexed with its subfolders and never changed.',
    fields: [{ name: 'path', label: 'Folder path', placeholder: 'C:\\Users\\you\\Pictures\\Screenshots' }], confirm: 'Add folder' });
  if (values && values.path.trim()) startIndex({ folders: [values.path.trim()], files: [] });
}

async function reindex() {
  try {
    await api('/api/library/reindex', { method: 'POST', body: { folder: S.folder === ALL ? null : S.folder } });
    await refreshJobs();
  } catch (err) { flash(err.message); }
}

async function forgetFolder() {
  const info = currentInfo();
  const values = await askDialog({ title: info.individual ? 'Remove these from the library?' : 'Remove this folder from the index?',
    text: 'Only SnapRecall’s data is removed. The screenshot files stay where they are.', confirm: 'Remove', danger: true });
  if (!values) return;
  try { await api('/api/library/forget', { method: 'POST', body: { folder: S.folder } }); await refreshLibrary(); await route(); }
  catch (err) { flash(err.message); }
}

async function deleteAll() {
  const what = S.folder === ALL ? 'every screenshot in all folders' : currentInfo().individual ? 'all of these screenshots' : 'every screenshot in this folder';
  const values = await askDialog({ title: `Delete ${what} from SnapRecall?`,
    text: 'They disappear from your library and search. The image files stay on your computer, and re-indexing won’t bring them back.',
    confirm: 'Delete all screenshots', danger: true });
  if (!values) return;
  try { await api('/api/library/delete-all', { method: 'POST', body: { folder: S.folder === ALL ? null : S.folder } }); await refreshLibrary(); await route(); }
  catch (err) { flash(err.message); }
}

async function restoreRemoved() {
  try { await api('/api/library/restore-removed', { method: 'POST' }); await refreshLibrary(); flash('They return the next time you re-index their folder. Screenshots you chose one by one return when you choose them again.', 'ok'); }
  catch (err) { flash(err.message); }
}

async function deleteAccount() {
  const values = await askDialog({ title: 'Delete your account and its library?',
    text: 'This removes the search data and thumbnails from this computer. Your screenshot files stay where they are. Cloud backups aren’t affected.',
    fields: [{ name: 'password', label: 'Password', type: 'password' }], confirm: 'Delete account', danger: true });
  if (!values) return;
  try { await api('/api/account/delete', { method: 'POST', body: { password: values.password } }); showLogin('Your account and its library were deleted.'); }
  catch (err) { flash(err.message); }
}

async function signOut() {
  try { await api('/api/session/logout', { method: 'POST' }); } catch { /* already signed out */ }
  S.session = await api('/api/session');
  showLogin();
}

// ---- indexing progress -----------------------------------------------------------------------------------------
async function refreshJobs() {
  let jobs;
  try { jobs = await api('/api/jobs'); } catch (err) { if (err.status === 401) showLogin(err.message); return; }
  const wasActive = S.jobs.active.length > 0;
  const changed = JSON.stringify(jobs) !== JSON.stringify(S.jobs);
  S.jobs = jobs;
  if (changed) renderJobs();
  if (wasActive && !jobs.active.length) {
    await refreshLibrary();
    if (!S.detailPath) runSearch();
  }
  if (changed && wasActive !== jobs.active.length > 0) renderSidebar();
}

function jobCard(job) {
  const many = job.targetCount > 1 ? ` (${job.targetNumber} of ${job.targetCount})` : '';
  let title, detail = null;
  if (job.state === 'queued') title = 'Waiting for another indexing run to finish…';
  else if (job.state === 'waiting') { title = 'Getting text recognition and visual search ready…'; detail = 'This takes a few seconds after SnapRecall starts.'; }
  else {
    title = `Indexing ${job.target ? folderLabel(job.target) : 'screenshots'}${many}`;
    detail = job.total ? `${job.done} of ${job.total} · ${job.current || 'finishing…'}` : 'Looking for new and changed screenshots…';
  }
  const bar = job.state === 'running' && job.total ? h('progress', { max: job.total, value: job.done, 'aria-label': 'Indexing progress' }) : null;
  const line = detail ? h('div', { class: 'muted small', text: detail }) : null;
  const card = h('section', { class: 'job', 'aria-label': 'Indexing progress' },
    h('div', { class: 'job-head' }, h('b', {}, job.state === 'running' ? null : h('span', { class: 'spinner' }), ' ', title),
      h('button', { class: 'btn', type: 'button', disabled: job.cancelRequested, text: job.cancelRequested ? 'Stopping…' : 'Cancel',
        onclick: () => api(`/api/jobs/${job.id}/cancel`, { method: 'POST' }).then(refreshJobs).catch((e) => flash(e.message)) })),
    bar, line,
    job.state === 'running' ? h('div', { class: 'muted small', text: 'You can keep searching while this runs, or close this window and open it again later.' }) : null);
  // Progress changes every second, so it is updated in place: replacing the card would also replace
  // the Cancel button under the pointer and could swallow a click on it.
  card.update = (next) => {
    if (bar && next.total) { bar.max = next.total; bar.value = next.done; }
    if (line && next.total) line.textContent = `${next.done} of ${next.total} · ${next.current || 'finishing…'}`;
  };
  return card;
}

let renderedJobs = '';

function finishedBanner(job) {
  const problems = [...job.problems, ...job.failed.map((f) => `${f.path.split(/[\\/]/).pop()}: ${f.message}`)];
  const lines = problems.length ? h('ul', {}, problems.slice(0, 5).map((p) => h('li', { text: p })),
    problems.length > 5 ? h('li', { text: `and ${problems.length - 5} more` }) : null) : null;
  let kind, text;
  if (job.state === 'cancelled') { kind = 'warn'; text = `Indexing stopped. ${plural(job.processed, 'screenshot was', 'screenshots were')} saved; run it again to continue where it left off.`; }
  else if (job.state === 'failed') { kind = 'error'; text = 'Indexing stopped unexpectedly.'; }
  else { kind = problems.length ? 'warn' : 'ok'; text = `Indexing complete — ${job.processed ? plural(job.processed, 'screenshot', 'screenshots') + ' added or updated' : 'everything was up to date'}${job.removed ? `, ${job.removed} removed` : ''}.`; }
  return h('div', { class: `banner ${kind}`, role: 'status' }, h('div', { class: 'grow' }, text, lines),
    h('button', { class: 'btn ghost', type: 'button', text: 'Dismiss', onclick: () => { S.dismissed.add(job.id); renderJobs(); } }));
}

function renderJobs() {
  const box = document.getElementById('jobs');
  if (!box) return;
  // The cards are rebuilt only when something other than the progress numbers changed.
  const shape = S.jobs.active.map((j) => [j.id, j.state, j.cancelRequested, j.target, j.targetNumber, !!j.total].join()).join('|');
  if (S.jobs.active.length && shape === renderedJobs) {
    [...box.querySelectorAll('.job')].forEach((card, i) => card.update(S.jobs.active[i]));
    return;
  }
  renderedJobs = shape;
  const recent = S.jobs.recent.filter((j) => !S.dismissed.has(j.id) && j.finishedAt && j.finishedAt * 1000 > S.loadedAt - 30 * 60 * 1000);
  box.replaceChildren(...S.jobs.active.map(jobCard), ...(S.jobs.active.length ? [] : recent.slice(0, 1).map(finishedBanner)));
}

async function tick() {
  S.tick += 1;
  refreshJobs();
  if (S.session && (S.session.models.loading || S.tick % 15 === 0)) {
    try {
      const was = S.session.models.loading;
      S.session = await api('/api/session');
      if (!S.session.user) return showLogin('Your guest session ended, so its temporary library was deleted.');
      if (was !== S.session.models.loading) { renderSidebar(); if (!S.detailPath && S.q.trim()) runSearch(); }
    } catch (err) { if (err.status === 401) showLogin(); }
  }
}

// ---- search and browsing --------------------------------------------------------------------------------------------
function shotCard(item, withExcerpt = true) {
  const open = () => { location.hash = '#shot=' + encodeURIComponent(item.path); };
  return h('article', { class: 'shot' },
    h('img', { src: item.thumb, alt: '', loading: 'lazy', onclick: open, onerror: (e) => {
      e.target.replaceWith(h('div', { class: 'noimg', text: 'Preview unavailable' })); } }),
    h('button', { class: 'name', type: 'button', title: 'View larger', text: item.name, onclick: open }),
    h('div', { class: 'date', text: fmtDate(item.mtimeMs) + (item.copies ? ` · +${item.copies} ${item.copies === 1 ? 'copy' : 'copies'}` : '') }),
    withExcerpt && item.excerpt ? h('div', { class: 'excerpt' }, item.excerpt.map(([t, hit]) => (hit ? h('mark', { text: t }) : t))) : null);
}

function emptyState(iconName, title, text, action) {
  return h('div', { class: 'empty' }, h('div', { class: 'ic' }, icon(iconName, 28)), h('h3', { text: title }), h('div', { text }), action || null);
}

async function runSearch() {
  const seq = ++S.searchSeq;
  if (!S.library) return;
  if (!S.library.folders.length) return renderResults();
  const params = new URLSearchParams({ q: S.q.trim(), folder: S.folder, when: S.when, start: S.start, end: S.end, sort: S.sort });
  try {
    const result = await api('/api/search?' + params);
    if (seq !== S.searchSeq) return;
    S.result = result;
  } catch (err) {
    if (err.status === 401) return showLogin(err.message);
    S.result = { state: 'error', message: err.message, results: [] };
  }
  renderResults();
}

function renderResults() {
  const box = document.getElementById('content');
  if (!box || S.detailPath) return;
  const info = currentInfo(), lib = S.library, r = S.result;
  if (!lib.folders.length) {
    return box.replaceChildren(emptyState('folder', 'Find any screenshot by describing it',
      'Add a folder of screenshots, or pick individual screenshots, to get started. They stay on this computer.' +
      (lib.guest ? ' As a guest, this library is deleted when you close this window.' : ''),
      h('button', { class: 'btn primary', type: 'button', onclick: addScreenshots }, icon('plus', 16), 'Add screenshots…')));
  }
  const chip = h('span', { class: 'chip', title: info ? info.path : 'All folders' }, icon(info && info.individual ? 'image' : 'folder', 14), folderLabel(S.folder));
  const status = [chip, info ? plural(info.count, 'screenshot', 'screenshots') : null,
    info && fmtScan(info.lastScanAt) ? `Indexed ${fmtScan(info.lastScanAt)}` : null,
    S.session.models.loading ? 'Visual search starting…' : null].filter(Boolean);
  const header = [h('div', { class: 'title', text: 'Your screenshots' }),
    h('div', { class: 'status' }, status.flatMap((s, i) => (i ? [h('span', { class: 'dot', text: '•' }), s] : [s])))];
  if (info && info.scanComplete === false) header.push(h('div', { class: 'banner warn' }, 'The last scan couldn’t read everything in this folder. Try re-indexing.'));
  const body = [];
  if (!r) body.push(h('div', { class: 'muted', text: 'Loading…' }));
  else if (r.state === 'error') body.push(h('div', { class: 'banner error' }, r.message));
  else if (r.state === 'empty') body.push(emptyState('inbox', 'No screenshots here yet', 'Add PNG or JPEG files to this folder, then re-index it from the sidebar.'));
  else if (r.state === 'no-dates') body.push(emptyState('search', 'No screenshots from this time', 'Choose a wider date range, or Any time to see everything.'));
  else if (r.state === 'no-match') body.push(emptyState('search', 'No matching screenshots', 'Try different or fewer words, or a wider date range.'));
  else {
    const hidden = r.hidden ? ` · ${plural(r.hidden, 'duplicate', 'duplicates')} hidden` : '';
    const range = S.when === 'any' ? '' : ` · ${document.getElementById('when').selectedOptions[0].text.toLowerCase()}`;
    if (r.notice) body.push(h('div', { class: 'banner warn', role: 'status' }, r.notice));
    if (r.weak) body.push(h('div', { class: 'banner', role: 'status' }, 'No strong matches. These are the closest screenshots, but they may not be what you’re looking for.'));
    body.push(S.q.trim()
      ? h('p', { class: 'count' }, h('b', { text: String(r.count) }), ` result${r.count === 1 ? '' : 's'} for “${S.q.trim()}”${range}${hidden}`)
      : h('p', { class: 'count', text: (r.order === 'Date modified (newest)' ? 'Newest screenshots' : `Sorted by ${r.order}`) + range + hidden }));
    body.push(h('div', { class: 'grid' }, r.results.map((item) => shotCard(item))));
  }
  box.replaceChildren(...header, ...body);
}

// ---- detail view ---------------------------------------------------------------------------------------------------------
async function route() {
  if (!S.library) return;
  const m = location.hash.match(/^#shot=(.+)$/);
  if (m) {
    S.detailPath = decodeURIComponent(m[1]);
    await showDetail(S.detailPath);
  } else {
    S.detailPath = null;
    document.getElementById('topbar').hidden = false;
    renderResults();
    runSearch();
  }
}

const COPY_MESSAGES = {
  ok: () => `Copied. Paste it anywhere with ${/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘V' : 'Ctrl+V'}.`,
  unsupported: () => 'This window can’t copy images. Try a current version of Chrome, Edge, Safari, or Firefox.',
  insecure: () => 'Copying images only works when SnapRecall is opened at localhost or over https.',
  denied: () => 'Clipboard access was blocked. Allow clipboard access for this page and try again.',
};

async function copyImage(url, button, message) {
  const show = (kind, text) => { message.className = `msg ${kind}`; message.textContent = text; };
  if (!window.isSecureContext) return show('error', COPY_MESSAGES.insecure());
  if (!navigator.clipboard || !navigator.clipboard.write || typeof ClipboardItem === 'undefined') return show('error', COPY_MESSAGES.unsupported());
  button.disabled = true; show('', '');
  try {
    // The item is built from a promise so the click still counts as the user's gesture while the PNG downloads.
    const blob = fetch(url, { credentials: 'same-origin' }).then(async (response) => {
      if (!response.ok) {
        let data = null; try { data = await response.json(); } catch { /* not JSON */ }
        throw Object.assign(new Error((data && data.error) || 'the image could not be prepared'), { fromServer: true });
      }
      return response.blob();
    });
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    show('ok', COPY_MESSAGES.ok());
  } catch (err) {
    if (err && err.name === 'NotAllowedError') show('error', COPY_MESSAGES.denied());
    else if (err && err.fromServer) show('error', err.message);
    else show('error', `Couldn’t copy the image (${(err && err.name) || 'unknown error'}). Try again, or use Open original.`);
  } finally { button.disabled = false; }
}

async function showDetail(path) {
  const box = document.getElementById('content');
  document.getElementById('topbar').hidden = true;
  box.replaceChildren(h('div', { class: 'muted', text: 'Loading…' }));
  let d;
  try { d = await api('/api/detail?' + new URLSearchParams({ path, folder: S.folder })); }
  catch (err) {
    if (err.status === 401) return showLogin(err.message);
    location.hash = '';
    return flash(err.message);
  }
  if (S.detailPath !== path) return;
  const copyMsg = h('div', { class: 'msg', role: 'status' });
  const copyBtn = h('button', { class: 'btn primary block', type: 'button', onclick: () => copyImage(d.png, copyBtn, copyMsg) }, icon('copy', 16), 'Copy image');
  const actionMsg = h('div', { class: 'msg error', role: 'alert' });
  const guess = h('span', { class: 'guess', text: 'Guess' });
  const rows = [['Folder', d.folder]];
  if (d.width) rows.push(['Size', `${d.width} × ${d.height} px · ${fmtKb(d.size)}`]);
  rows.push(['Modified', fmtDate(d.mtimeMs)]);
  if (d.copies.length) rows.push(['Also saved at', h('span', {}, d.copies.slice(0, 3).map((p, i) => [i ? h('br') : null, p]), d.copies.length > 3 ? [h('br'), `and ${d.copies.length - 3} more`] : null)]);
  if (d.source) rows.push([['From', guess.cloneNode(true)], `${d.source.app} (${d.source.confidence})`]);
  if (d.tags.length) rows.push([['Might show', guess.cloneNode(true)], d.tags.join(', ')]);
  const similar = d.similarState === 'ok' ? h('div', { class: 'grid' }, d.similar.map((item) => shotCard(item, false)))
    : h('p', { class: 'muted small', text: {
      loading: 'Visual search is still starting; similar screenshots will appear in a few seconds.',
      unavailable: 'Finding similar screenshots needs visual search, which isn’t available right now.',
      unanalysed: 'This screenshot hasn’t been analysed yet. Re-index the folder to find similar ones.',
      none: `Nothing in ${currentInfo() ? 'this folder' : 'your folders'} looks much like this screenshot.` }[d.similarState] });
  box.replaceChildren(
    h('button', { class: 'btn ghost', type: 'button', onclick: () => { location.hash = ''; } }, icon('back', 16), 'Back to results'),
    h('div', { class: 'detail' },
      h('div', { class: 'viewer' }, h('img', { src: d.image, alt: d.name, onerror: (e) => {
        e.target.replaceWith(h('div', { class: 'muted', text: 'This image can’t be opened. It may have been moved or deleted. Try re-indexing the folder.' })); } })),
      h('div', { class: 'panel' },
        h('div', { class: 'title2', text: d.name }), copyBtn, copyMsg,
        h('button', { class: 'btn block', type: 'button', onclick: async () => {
          try { await api('/api/screenshot/open', { method: 'POST', body: { path: d.path } }); actionMsg.textContent = ''; }
          catch (err) { actionMsg.textContent = err.message; } } }, icon('external', 16), 'Open original'),
        h('div', { class: 'row2' },
          h('button', { class: 'btn', type: 'button', onclick: () => renameShot(d) }, icon('edit', 16), 'Rename'),
          h('button', { class: 'btn danger', type: 'button', onclick: () => deleteShot(d) }, icon('trash', 16), 'Delete')),
        actionMsg,
        h('p', { class: 'muted small', text: 'Copy image puts the full-size picture on your clipboard. Open original opens it in your default image viewer.' }),
        h('div', { class: 'section-label', text: 'Details' }),
        h('dl', { class: 'meta' }, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])),
        d.source || d.tags.length ? h('p', { class: 'muted small', text: '“From” and “Might show” are guessed automatically from the picture and its text, and may be wrong.' }) : null,
        d.ocrText ? h('details', { class: 'text' }, h('summary', { text: 'Text found in this screenshot' }), h('pre', { text: d.ocrText }),
          d.ocrQuality ? h('div', { class: 'muted small', text: `Recognition quality: ${d.ocrQuality}.` }) : null) : null)),
    h('div', { class: 'section', text: 'Similar screenshots' }), similar);
}

async function renameShot(d) {
  const dot = d.name.lastIndexOf('.');
  const values = await askDialog({ title: 'Rename file', text: 'Renames the file on your computer (its extension stays). The image itself isn’t changed.',
    fields: [{ name: 'name', label: `New name (keeps ${dot > 0 ? d.name.slice(dot) : 'its extension'})`, value: dot > 0 ? d.name.slice(0, dot) : d.name }], confirm: 'Rename file' });
  if (!values) return;
  try {
    const result = await api('/api/screenshot/rename', { method: 'POST', body: { path: d.path, name: values.name } });
    location.hash = '#shot=' + encodeURIComponent(result.path);
  } catch (err) { flash(err.message); }
}

async function deleteShot(d) {
  const values = await askDialog({ title: 'Delete this screenshot from SnapRecall?',
    text: 'It disappears from your library and search. The image file stays on your computer, and re-indexing won’t bring it back.', confirm: 'Delete screenshot', danger: true });
  if (!values) return;
  try { await api('/api/screenshot/delete', { method: 'POST', body: { path: d.path } }); await refreshLibrary(); location.hash = ''; }
  catch (err) { flash(err.message); }
}

window.addEventListener('hashchange', () => { if (S.library) route(); });

// ---- start -------------------------------------------------------------------------------------------------------------------
(async function boot() {
  try {
    S.session = await api('/api/session');
    if (S.session.user) await enterApp(); else showLogin();
  } catch (err) {
    app().replaceChildren(h('div', { class: 'empty' }, h('h3', { text: 'SnapRecall can’t start' }), h('div', { text: err.message })));
  }
})();
