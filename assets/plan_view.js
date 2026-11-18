/* Update plan — view layer. Takes plan data (summaries from status.json, one page of a plan's file list) and
   returns view structures / HTML. Never calls the Api and never touches the DOM: index.html binds it.
   Loaded in the app as a classic script (window.PlanView) and in Node tests via require(). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PlanView = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // error > ambiguous_path > v1_unavailable > incomplete_archive > first_archive > plan_ready > up_to_date > skipped
  var STATE_PRIORITY = ['error', 'ambiguous_path', 'v1_unavailable', 'incomplete_archive', 'first_archive',
                        'plan_ready', 'up_to_date', 'skipped'];
  var LIMIT = 500;

  var L = {
    pl: {
      'st.error': 'błąd', 'st.ambiguous_path': 'niejednoznaczne ścieżki', 'st.v1_unavailable': 'v1 — plan niedostępny',
      'st.first_archive': 'Plan dla nowej archiwizacji', 'st.incomplete_archive': 'archiwum niekompletne',
      'st.plan_ready': 'plan aktualizacji gotowy',
      'depnote': 'Plan dla nowej archiwizacji — sprawdzono wspólne zależności; inne gry lub wydania mogą już zawierać część danych',
      'fullnote': 'Plan dla nowej archiwizacji — sprawdzono wszystkie chunki',
      'n.uniq': 'unikalnych', 'n.entries': 'wpisów', 'v.unique': 'Unikalne ścieżki', 'v.entries': 'Wszystkie wpisy depotów',
      'c.entries': 'wpisy',
      'st.up_to_date': 'aktualna', 'st.skipped': 'pominięta', 'st.checking': 'Sprawdzanie aktualizacji…',
      'stale': 'Plan nieaktualny — po jego wyliczeniu ruszyła aktualizacja tej gry. Sprawdź plan ponownie.',
      'v1note': 'Gra ma build Galaxy v1 (main.bin): aktualizacja pobiera CAŁY depot, planu plików nie ma.',
      'ambnote': 'Ta sama ścieżka ma różną treść w kilku depotach jednej grupy. Plan tego nie rozstrzyga — nic nie zostało uruchomione.',
      'k.added': 'dodane', 'k.changed': 'zmienione', 'k.removed': 'usunięte', 'k.unchanged': 'bez zmian',
      'k.repair': 'do naprawy',
      'b.download': 'do pobrania', 'b.reused': 'ponownie użyte', 'b.repair': 'do naprawy',
      'b.repairUnique': 'unikalnie', 'b.groups': 'grupy depotów', 'b.ambiguous': 'grupy niejednoznaczne',
      'c.path': 'ścieżka', 'c.size': 'rozmiar', 'c.chunks': 'chunki', 'c.reused': 'ponownie użyte',
      'c.missing': 'brakujące', 'c.missingBytes': 'brakujące bajty', 'c.reasons': 'powody', 'c.group': 'grupa',
      'more': 'pokazano {n} z {total} — jeszcze {rest}; zawęź filtr', 'empty': 'Brak pozycji.',
      't.game': 'gra', 't.state': 'stan', 't.ambiguous': 'niejedn.', 'from': 'z', 'to': 'na',
      'run.progress': 'Sprawdzono {done} z {total}', 'run.current': 'teraz: {title}', 'run.errors': 'błędy: {n}',
      'run.done': 'Zakończono: {done} z {total}', 'run.cancelled': 'Przerwano: {done} z {total}',
      'run.interrupted': 'Poprzednie sprawdzanie zostało przerwane ({done} z {total}).',
      'r.chunks': 'chunki', 'r.size': 'rozmiar', 'r.md5': 'MD5', 'r.sfc_container_changed': 'kontener SFC',
      'r.sfc_ref_changed': 'sfcRef (niespójny manifest)', 'r.sfc_storage_changed': 'SFC ↔ chunki',
      'sfc': 'kontener małych plików'
    },
    en: {
      'st.error': 'error', 'st.ambiguous_path': 'ambiguous paths', 'st.v1_unavailable': 'v1 — no plan',
      'st.first_archive': 'Plan for a new archive', 'st.incomplete_archive': 'incomplete archive',
      'st.plan_ready': 'update plan ready',
      'depnote': 'Plan for a new archive — shared dependencies checked; other games or editions may already hold part of the data',
      'fullnote': 'Plan for a new archive — every chunk checked',
      'n.uniq': 'unique', 'n.entries': 'entries', 'v.unique': 'Unique paths', 'v.entries': 'All depot entries',
      'c.entries': 'entries',
      'st.up_to_date': 'up to date', 'st.skipped': 'skipped', 'st.checking': 'Checking for updates…',
      'stale': 'Plan is stale — an update of this game started after it was computed. Check again.',
      'v1note': 'This game has a Galaxy v1 build (main.bin): the update downloads the WHOLE depot; no file plan.',
      'ambnote': 'The same path has different content in several depots of one group. The plan does not decide it — nothing was started.',
      'k.added': 'added', 'k.changed': 'changed', 'k.removed': 'removed', 'k.unchanged': 'unchanged',
      'k.repair': 'to repair',
      'b.download': 'to download', 'b.reused': 'reused', 'b.repair': 'to repair',
      'b.repairUnique': 'unique', 'b.groups': 'depot groups', 'b.ambiguous': 'ambiguous groups',
      'c.path': 'path', 'c.size': 'size', 'c.chunks': 'chunks', 'c.reused': 'reused',
      'c.missing': 'missing', 'c.missingBytes': 'missing bytes', 'c.reasons': 'reasons', 'c.group': 'group',
      'more': 'showing {n} of {total} — {rest} more; narrow the filter', 'empty': 'Nothing here.',
      't.game': 'game', 't.state': 'state', 't.ambiguous': 'ambig.', 'from': 'from', 'to': 'to',
      'run.progress': 'Checked {done} of {total}', 'run.current': 'now: {title}', 'run.errors': 'errors: {n}',
      'run.done': 'Finished: {done} of {total}', 'run.cancelled': 'Stopped: {done} of {total}',
      'run.interrupted': 'The previous check was interrupted ({done} of {total}).',
      'r.chunks': 'chunks', 'r.size': 'size', 'r.md5': 'MD5', 'r.sfc_container_changed': 'SFC container',
      'r.sfc_ref_changed': 'sfcRef (inconsistent manifest)', 'r.sfc_storage_changed': 'SFC ↔ chunks',
      'sfc': 'small files container'
    }
  };
  var lang = 'pl';

  function setLang(l) { lang = L[l] ? l : 'pl'; }
  function tr(k, vars) {
    var s = (L[lang] && L[lang][k]) || L.pl[k] || k;
    if (vars) Object.keys(vars).forEach(function (v) { s = s.split('{' + v + '}').join(String(vars[v])); });
    return s;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function fmtBytes(n) {
    n = Number(n) || 0;
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? String(n) : n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2)) + ' ' + u[i];
  }
  function fmtInt(n) { return String(Number(n) || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }
  function stateOf(s) { return (s && s.ui_state) || 'error'; }
  function stateLabel(state) { return tr('st.' + state); }
  function stateRank(state) {
    var i = STATE_PRIORITY.indexOf(state);
    return i < 0 ? 0 : i;
  }
  function badge(state) {
    return '<span class="plan-badge plan-' + esc(state) + '">' + esc(stateLabel(state)) + '</span>';
  }
  function counts(s) {
    var c = (s && s.counts) || {};
    return {added: c.added || 0, changed: c.changed || 0, removed: c.removed || 0, unchanged: c.unchanged || 0};
  }
  /* Unique normalised paths (counts_unique) and depot entries (counts) of one kind; unique null = not known. */
  function pathCount(s, k) {
    var e = counts(s)[k], u = s && s.counts_unique ? s.counts_unique[k] : null;
    return {unique: u == null ? null : u, entries: e};
  }
  /* "21 408 unikalnych / 63 507 wpisów" when they differ, else the one number */
  function pathCountText(pc) {
    if (pc.unique == null || pc.unique === pc.entries) return fmtInt(pc.entries);
    return fmtInt(pc.unique) + ' ' + tr('n.uniq') + ' / ' + fmtInt(pc.entries) + ' ' + tr('n.entries');
  }

  /* ── one game ─────────────────────────────────────────────────────────── */
  function checkingView() {
    return '<div class="plan-checking"><span class="plan-spin"></span>' + esc(tr('st.checking')) + '</div>';
  }

  function summaryView(s) {
    var st = stateOf(s), c = counts(s), h = '';
    h += '<div class="plan-head">' + badge(st);
    if (s.from_build || s.to_build) {
      h += '<span class="plan-builds">' + esc(tr('from')) + ' ' + esc(s.from_version || s.from_build || '—') +
           ' → ' + esc(tr('to')) + ' ' + esc(s.to_version || s.to_build || '—') + '</span>';
    }
    h += '</div>';
    if (s.stale) h += '<div class="plan-note plan-warn">' + esc(tr('stale')) + '</div>';
    if (st === 'v1_unavailable') h += '<div class="plan-note plan-warn">' + esc(tr('v1note')) + '</div>';
    if (st === 'ambiguous_path') h += '<div class="plan-note plan-warn">' + esc(tr('ambnote')) + '</div>';
    if (s.reason && st !== 'v1_unavailable') h += '<div class="plan-note">' + esc(s.reason) + '</div>';
    if (st === 'first_archive' && s.first_archive_check === 'dependencies_only')
      h += '<div class="plan-note plan-warn">' + esc(tr('depnote')) + '</div>';
    else if (st === 'first_archive' && s.first_archive_check === 'full')
      h += '<div class="plan-note">' + esc(tr('fullnote')) + '</div>';
    if (st === 'skipped' || st === 'error' || st === 'v1_unavailable' || !s.counts) return h;
    h += '<div class="plan-tiles">';
    ['added', 'changed', 'removed', 'unchanged'].forEach(function (k) {
      var pc = pathCount(s, k), big = pc.unique == null ? pc.entries : pc.unique;
      h += '<div class="plan-tile"><b>' + fmtInt(big) + '</b><span>' + esc(tr('k.' + k)) +
           (pc.unique != null && pc.unique !== pc.entries ? ': ' + esc(pathCountText(pc)) : '') + '</span></div>';
    });
    h += '</div><div class="plan-tiles">';
    h += '<div class="plan-tile plan-dl"><b>' + fmtBytes(s.download_bytes) + '</b><span>' + esc(tr('b.download')) + '</span></div>';
    h += '<div class="plan-tile"><b>' + fmtBytes(s.reused_bytes) + '</b><span>' + esc(tr('b.reused')) + '</span></div>';
    h += '<div class="plan-tile' + (s.repair_bytes ? ' plan-repair' : '') + '"><b>' + fmtBytes(s.repair_bytes) +
         '</b><span>' + esc(tr('b.repair')) + ' · ' + esc(tr('b.repairUnique')) + ' ' + fmtBytes(s.repair_unique_bytes) + '</span></div>';
    h += '<div class="plan-tile"><b>' + (s.depot_groups || 0) + '</b><span>' + esc(tr('b.groups')) + '</span></div>';
    h += '<div class="plan-tile' + (s.ambiguous_groups ? ' plan-amb' : '') + '"><b>' + (s.ambiguous_groups || 0) +
         '</b><span>' + esc(tr('b.ambiguous')) + '</span></div>';
    return h + '</div>';
  }

  var KINDS = ['changed', 'added', 'removed', 'repair'];

  function tabsView(sizes, active) {
    sizes = sizes || {};
    return '<div class="plan-tabs">' + KINDS.map(function (k) {
      return '<button class="plan-tab' + (k === active ? ' active' : '') + '" data-kind="' + k + '">' +
             esc(tr('k.' + k)) + ' · ' + (sizes[k] || 0) + '</button>';
    }).join('') + '</div>';
  }

  /* The tab a plan opens on: the first non-empty list (a new archive has only "added"). */
  function defaultKind(sizes) {
    sizes = sizes || {};
    for (var i = 0; i < KINDS.length; i++) if (sizes[KINDS[i]] > 0) return KINDS[i];
    return KINDS[0];
  }

  function reasonsText(rs) {
    return (rs || []).map(function (r) { return tr('r.' + r); }).join(', ');
  }

  /* "Unique paths" / "All depot entries" switch of the details list */
  function entriesToggleView(unique) {
    return '<div class="plan-tabs plan-view-toggle">' +
      '<button class="plan-tab' + (unique ? ' active' : '') + '" data-unique="1">' + esc(tr('v.unique')) + '</button>' +
      '<button class="plan-tab' + (unique ? '' : ' active') + '" data-unique="0">' + esc(tr('v.entries')) + '</button></div>';
  }

  var COLUMNS = {
    changed: ['path', 'size', 'reused', 'missing', 'missingBytes', 'reasons'],
    added: ['path', 'size', 'chunks'],
    removed: ['path', 'size'],
    repair: ['path', 'size', 'missing', 'missingBytes']
  };

  function cell(col, e) {
    switch (col) {
      case 'path': return e.sfc_container ? esc(tr('sfc')) + ' <span class="plan-dim">' + esc(e.group) + '</span>'
                                          : esc(e.path) + (e.manifest_inconsistent ? ' ⚠' : '') + (e.layout_changed ? ' ↺' : '');
      case 'size': return e.sfc_container ? '—' : fmtBytes(e.size);
      case 'chunks': return String(e.chunks || 0);
      case 'reused': return String(e.reused_chunks || 0);
      case 'missing': return String(e.missing_chunks || 0);
      case 'missingBytes': return fmtBytes(e.missing_bytes);
      case 'reasons': return esc(reasonsText(e.reasons));
      case 'entries': return String(e.entries || 1);
    }
    return '';
  }

  /* `page` = one get_update_plan answer: {kind, items, total, remaining, offset} */
  function fileListView(page) {
    var kind = page && page.kind, items = (page && page.items) || [], cols = (COLUMNS[kind] || COLUMNS.changed).slice();
    if (page && page.unique) cols.push('entries');
    if (!items.length) return '<div class="plan-empty">' + esc(tr('empty')) + '</div>';
    var h = '<table class="plan-files"><thead><tr>' + cols.map(function (c) {
      return '<th>' + esc(tr('c.' + c)) + '</th>';
    }).join('') + '</tr></thead><tbody>';
    items.slice(0, LIMIT).forEach(function (e) {
      h += '<tr>' + cols.map(function (c) { return '<td class="pc-' + c + '">' + cell(c, e) + '</td>'; }).join('') + '</tr>';
    });
    h += '</tbody></table>';
    var shown = Math.min(items.length, LIMIT);
    if (page.remaining) h += '<div class="plan-more">' + esc(tr('more', {n: shown, total: page.total, rest: page.remaining})) + '</div>';
    return h;
  }

  function ambiguousView(list) {
    if (!list || !list.length) return '';
    return '<div class="plan-note plan-warn"><b>' + esc(tr('st.ambiguous_path')) + ':</b> ' +
           list.slice(0, 50).map(function (i) { return esc(i.path); }).join(', ') +
           (list.length > 50 ? ' …' : '') + '</div>';
  }

  /* ── every game ───────────────────────────────────────────────────────── */
  var FILTERS = {
    all: function () { return true; },
    updates: function (s) {
      var st = stateOf(s); return st === 'plan_ready' || st === 'first_archive' || st === 'incomplete_archive';
    },
    errors: function (s) { return stateOf(s) === 'error'; },
    ambiguous: function (s) { return stateOf(s) === 'ambiguous_path' || (s.ambiguous_files || 0) > 0; },
    skipped: function (s) { return stateOf(s) === 'skipped'; }
  };

  /* Plans "Wykonaj plan" runs: an update, a first download or finishing an incomplete archive, not stale. */
  var EXEC_STATES = {plan_ready: 1, first_archive: 1, incomplete_archive: 1};
  function executablePlans(plans) {
    return (plans || []).filter(function (s) { return EXEC_STATES[stateOf(s)] && !s.stale; });
  }

  function filterPlans(plans, filter) {
    var f = FILTERS[filter] || FILTERS.all;
    return (plans || []).filter(f);
  }

  /* sort: 'download' = to-download bytes descending; default = state priority, then title */
  function sortPlans(plans, sort) {
    var out = (plans || []).slice();
    if (sort === 'download') {
      out.sort(function (a, b) { return (b.download_bytes || 0) - (a.download_bytes || 0) ||
                                        String(a.title).localeCompare(String(b.title)); });
    } else {
      out.sort(function (a, b) { return stateRank(stateOf(a)) - stateRank(stateOf(b)) ||
                                        String(a.title).localeCompare(String(b.title)); });
    }
    return out;
  }

  /* Rows of the every-game table, built from summaries only (status.json) — no plan file is needed. */
  /* A plan that compared no manifests (up to date by build id, v1, skipped, error) has no counts: null → "—". */
  function planRows(plans) {
    return (plans || []).map(function (s) {
      var has = !!s.counts, pc = function (k) { return has ? pathCount(s, k) : null; };
      return {pid: String(s.product_id || ''), title: s.title || '', state: stateOf(s), label: stateLabel(stateOf(s)),
              added: pc('added'), changed: pc('changed'), removed: pc('removed'), unchanged: pc('unchanged'),
              download: has ? (s.download_bytes || 0) : null, reused: has ? (s.reused_bytes || 0) : null,
              repair: has ? (s.repair_bytes || 0) : null, ambiguous: has ? (s.ambiguous_files || 0) : null,
              shared_dependency_check: !!s.shared_dependency_check, stale: !!s.stale, reason: s.reason || ''};
    });
  }
  function num(v) { return v == null ? '—' : String(v); }
  function pathNum(pc) {
    if (pc == null) return '—';
    if (pc.unique == null || pc.unique === pc.entries) return fmtInt(pc.entries);
    return fmtInt(pc.unique) + ' <span class="plan-dim">/ ' + fmtInt(pc.entries) + '</span>';
  }
  function size(v) { return v == null ? '—' : fmtBytes(v); }

  function planAllView(plans, opts) {
    opts = opts || {};
    var rows = planRows(sortPlans(filterPlans(plans, opts.filter), opts.sort));
    var arrow = opts.sort === 'download' ? ' ▼' : '';
    var h = '<table class="plan-all"><thead><tr>' +
      '<th>' + esc(tr('t.game')) + '</th><th>' + esc(tr('t.state')) + '</th>' +
      '<th>' + esc(tr('k.added')) + '</th><th>' + esc(tr('k.changed')) + '</th><th>' + esc(tr('k.removed')) + '</th>' +
      '<th>' + esc(tr('k.unchanged')) + '</th>' +
      '<th class="plan-sort" data-sort="download">' + esc(tr('b.download')) + arrow + '</th>' +
      '<th>' + esc(tr('b.reused')) + '</th><th>' + esc(tr('b.repair')) + '</th><th>' + esc(tr('t.ambiguous')) + '</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (r) {
      h += '<tr data-pid="' + esc(r.pid) + '" title="' + esc(r.reason) + '"><td>' + esc(r.title) + (r.stale ? ' ⏱' : '') +
           '</td><td>' + badge(r.state) + '</td><td>' + pathNum(r.added) + '</td><td>' + pathNum(r.changed) + '</td><td>' +
           pathNum(r.removed) + '</td><td>' + pathNum(r.unchanged) + '</td><td>' + size(r.download) +
           (r.shared_dependency_check ? ' <span class="plan-dim" title="' + esc(tr('depnote')) + '">ⓘ</span>' : '') +
           '</td><td>' + size(r.reused) + '</td><td>' + size(r.repair) + '</td><td>' + num(r.ambiguous) + '</td></tr>';
    });
    return h + '</tbody></table>' + (rows.length ? '' : '<div class="plan-empty">' + esc(tr('empty')) + '</div>');
  }

  function progressView(run, current) {
    run = run || {};
    var total = run.total || 0, done = run.done || 0;
    var pct = total ? Math.round(100 * done / total) : 0;
    var head = run.interrupted ? tr('run.interrupted', {done: done, total: total})
             : run.finished ? tr(run.cancelled ? 'run.cancelled' : 'run.done', {done: done, total: total})
             : tr('run.progress', {done: done, total: total});
    return '<div class="plan-progress"><div class="plan-bar"><i style="width:' + pct + '%"></i></div>' +
           '<div class="plan-prog-txt">' + esc(head) +
           (!run.finished && current ? ' · ' + esc(tr('run.current', {title: current})) : '') +
           ' · ' + esc(tr('run.errors', {n: run.errors || 0})) + '</div></div>';
  }

  /* merge one live progress summary into the list of summaries (by product id) */
  function mergePlan(plans, s) {
    if (!s || !s.product_id) return plans || [];
    var out = (plans || []).filter(function (p) { return String(p.product_id) !== String(s.product_id); });
    out.push(s);
    return out;
  }

  return {STATE_PRIORITY: STATE_PRIORITY, LIMIT: LIMIT, KINDS: KINDS, setLang: setLang, esc: esc,
          fmtBytes: fmtBytes, fmtInt: fmtInt, pathCountText: pathCountText,
          entriesToggleView: entriesToggleView, defaultKind: defaultKind, stateLabel: stateLabel, stateRank: stateRank, checkingView: checkingView,
          summaryView: summaryView, tabsView: tabsView, fileListView: fileListView, ambiguousView: ambiguousView,
          filterPlans: filterPlans, executablePlans: executablePlans, sortPlans: sortPlans, planRows: planRows, planAllView: planAllView,
          progressView: progressView, mergePlan: mergePlan};
}));
