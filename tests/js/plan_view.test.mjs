// node --test tests/js/plan_view.test.mjs — the update plan view layer (assets/plan_view.js), no browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const PV = require('../../assets/plan_view.js');
PV.setLang('pl');

const S = (pid, ui_state, extra = {}) => ({
  product_id: pid, title: `Gra ${pid}`, ui_state,
  counts: {added: 1, changed: 2, removed: 3, unchanged: 4}, download_bytes: 0, reused_bytes: 0,
  repair_bytes: 0, repair_unique_bytes: 0, ambiguous_files: 0, ambiguous_groups: 0, depot_groups: 2, ...extra,
});

test('the view layer never calls the Api', () => {
  const src = readFileSync(new URL('../../assets/plan_view.js', import.meta.url), 'utf8');
  assert.ok(!src.includes('pywebview'));
  assert.ok(!/\bcall\(/.test(src));
});

test('first_archive reads as "Plan dla nowej archiwizacji", never as an update', () => {
  assert.equal(PV.stateLabel('first_archive'), 'Plan dla nowej archiwizacji');
  const deps = PV.summaryView(S('1', 'first_archive', {download_bytes: 5 * 1024 * 1024, shared_dependency_check: true,
                                                       first_archive_check: 'dependencies_only'}));
  assert.match(deps, /Plan dla nowej archiwizacji/);
  assert.doesNotMatch(deps, /plan aktualizacji gotowy/);
  assert.match(deps, /Plan dla nowej archiwizacji — sprawdzono wspólne zależności; inne gry lub wydania mogą już zawierać część danych/);
  assert.doesNotMatch(deps, /dokładn|≈|oszacowani|wszystkie chunki/);      // never called exact or approximate
  const full = PV.summaryView(S('1', 'first_archive', {first_archive_check: 'full'}));
  assert.match(full, /Plan dla nowej archiwizacji — sprawdzono wszystkie chunki/);
  assert.doesNotMatch(full, /wspólne zależności/);
  const row = PV.planRows([S('1', 'first_archive', {shared_dependency_check: true})])[0];
  assert.equal(row.label, 'Plan dla nowej archiwizacji');
  assert.match(PV.planAllView([S('1', 'first_archive', {shared_dependency_check: true})]), /ⓘ/);
});

test('incomplete_archive is its own state', () => {
  assert.equal(PV.stateLabel('incomplete_archive'), 'archiwum niekompletne');
  const html = PV.summaryView(S('1', 'incomplete_archive', {reason: 'Część danych tej gry już jest w archiwum'}));
  assert.match(html, /archiwum niekompletne/);
  assert.match(html, /Część danych tej gry już jest w archiwum/);
  assert.doesNotMatch(html, /Sprawdzono wspólne zależności/);
});

test('state priority: error > ambiguous_path > v1_unavailable > incomplete_archive > first_archive > plan_ready > up_to_date > skipped', () => {
  const order = ['skipped', 'up_to_date', 'plan_ready', 'first_archive', 'incomplete_archive', 'v1_unavailable',
                 'ambiguous_path', 'error'];
  const sorted = PV.sortPlans(order.map((s, i) => S(String(i), s))).map(p => p.ui_state);
  assert.deepEqual(sorted, [...order].reverse());
});

test('v1_unavailable says the whole depot is downloaded and is not an error', () => {
  const html = PV.summaryView(S('1', 'v1_unavailable', {reason: 'x'}));
  assert.match(html, /CAŁY depot/);
  assert.equal(PV.filterPlans([S('1', 'v1_unavailable')], 'errors').length, 0);
});

test('ambiguous_path shows a warning; skipped is its own filter, not an error', () => {
  assert.match(PV.summaryView(S('1', 'ambiguous_path', {ambiguous_groups: 1})), /nic nie zostało uruchomione/);
  const plans = [S('1', 'skipped'), S('2', 'error'), S('3', 'ambiguous_path', {ambiguous_files: 2}),
                 S('4', 'plan_ready'), S('5', 'first_archive'), S('6', 'up_to_date'), S('7', 'incomplete_archive')];
  assert.deepEqual(PV.filterPlans(plans, 'skipped').map(p => p.product_id), ['1']);
  assert.deepEqual(PV.filterPlans(plans, 'errors').map(p => p.product_id), ['2']);
  assert.deepEqual(PV.filterPlans(plans, 'ambiguous').map(p => p.product_id), ['3']);
  assert.deepEqual(PV.filterPlans(plans, 'updates').map(p => p.product_id), ['4', '5', '7']);
  assert.equal(PV.filterPlans(plans, 'all').length, 7);
});

test('sort by "to download" descending', () => {
  const plans = [S('a', 'plan_ready', {download_bytes: 10}), S('b', 'plan_ready', {download_bytes: 300}),
                 S('c', 'up_to_date', {download_bytes: 0}), S('d', 'first_archive', {download_bytes: 50})];
  assert.deepEqual(PV.sortPlans(plans, 'download').map(p => p.product_id), ['b', 'd', 'a', 'c']);
  assert.match(PV.planAllView(plans, {sort: 'download'}), /do pobrania ▼/);
});

test('to download and to repair are shown separately, with the unique repair size', () => {
  const html = PV.summaryView(S('1', 'plan_ready', {download_bytes: 2048, repair_bytes: 3072, repair_unique_bytes: 1024}));
  assert.match(html, /2\.00 KB<\/b><span>do pobrania/);
  assert.match(html, /3\.00 KB<\/b><span>do naprawy · unikalnie 1\.00 KB/);
});

test('file list: at most 500 rows and how many remain', () => {
  const items = Array.from({length: 600}, (_, i) => ({path: `f${i}.dat`, size: 1, chunks: 1}));
  const html = PV.fileListView({kind: 'added', items, total: 1234, remaining: 734, offset: 0});
  assert.equal((html.match(/<tr>/g) || []).length, 1 + 500);              // header + 500
  assert.match(html, /pokazano 500 z 1234 — jeszcze 734/);
});

test('file list columns per kind', () => {
  const ch = PV.fileListView({kind: 'changed', remaining: 0, total: 1, items: [
    {path: 'bin\\a.exe', size: 2048, reused_chunks: 3, missing_chunks: 1, missing_bytes: 1024, reasons: ['chunks', 'md5']}]});
  assert.match(ch, /bin\\a\.exe/);
  assert.match(ch, /<td class="pc-reused">3<\/td><td class="pc-missing">1<\/td><td class="pc-missingBytes">1\.00 KB<\/td>/);
  assert.match(ch, /chunki, MD5/);
  const rm = PV.fileListView({kind: 'removed', remaining: 0, total: 1, items: [{path: 'old.dat', size: 10}]});
  assert.doesNotMatch(rm, /pc-missing/);
  const rp = PV.fileListView({kind: 'repair', remaining: 0, total: 1,
    items: [{path: '<smallFilesContainer>', sfc_container: true, group: '1 · *', missing_chunks: 1, missing_bytes: 5}]});
  assert.match(rp, /kontener małych plików/);
});

test('every-game table is built from summaries alone', () => {
  const rows = PV.planRows([S('9', 'plan_ready', {download_bytes: 7, reused_bytes: 8, repair_bytes: 9, ambiguous_files: 1})]);
  assert.deepEqual(rows[0], {pid: '9', title: 'Gra 9', state: 'plan_ready', label: 'plan aktualizacji gotowy',
    added: {unique: null, entries: 1}, changed: {unique: null, entries: 2}, removed: {unique: null, entries: 3},
    unchanged: {unique: null, entries: 4}, download: 7, reused: 8, repair: 9, ambiguous: 1,
    shared_dependency_check: false, stale: false, reason: ''});
});

test('added files: unique paths next to depot entries', () => {
  const s = S('1', 'first_archive', {counts: {added: 63507, changed: 0, removed: 0, unchanged: 0},
                                     counts_unique: {added: 21408, changed: 0, removed: 0, unchanged: null}});
  assert.equal(PV.pathCountText({unique: 21408, entries: 63507}), '21 408 unikalnych / 63 507 wpisów');
  assert.equal(PV.pathCountText({unique: 5, entries: 5}), '5');
  assert.equal(PV.pathCountText({unique: null, entries: 7}), '7');
  const head = PV.summaryView(s);
  assert.match(head, /<b>21 408<\/b><span>dodane: 21 408 unikalnych \/ 63 507 wpisów<\/span>/);
  const table = PV.planAllView([s]);
  assert.match(table, /<td>21 408 <span class="plan-dim">\/ 63 507<\/span><\/td>/);
});

test('details switch: unique paths (default) / all depot entries', () => {
  assert.match(PV.entriesToggleView(true), /class="plan-tab active" data-unique="1">Unikalne ścieżki/);
  assert.match(PV.entriesToggleView(false), /class="plan-tab active" data-unique="0">Wszystkie wpisy depotów/);
  const page = {kind: 'added', unique: true, total: 1, remaining: 0,
                items: [{path: 'goggame-1.info', size: 10, chunks: 1, entries: 3}]};
  assert.match(PV.fileListView(page), /<th>wpisy<\/th>/);
  assert.match(PV.fileListView(page), /<td class="pc-entries">3<\/td>/);
  assert.doesNotMatch(PV.fileListView({...page, unique: false}), /pc-entries/);
});

test('up_to_date without computed manifests shows "—", not zeros', () => {
  const plan = {product_id: '5', title: 'Aktualna', ui_state: 'up_to_date'};    // no counts: nothing compared
  const row = PV.planRows([plan])[0];
  assert.equal(row.added, null);
  assert.equal(row.download, null);
  const html = PV.planAllView([plan]);
  const cells = html.match(/<tr data-pid="5"[\s\S]*?<\/tr>/)[0].match(/<td>[^<]*<\/td>/g).slice(1);
  assert.ok(cells.every(c => c === '<td>—</td>'), cells.join(''));
});

test('HTML is escaped', () => {
  const html = PV.planAllView([S('1', 'error', {title: '<img src=x onerror=alert(1)>'})]);
  assert.ok(!html.includes('<img'));
});

test('progress and merge of live results', () => {
  assert.match(PV.progressView({total: 10, done: 3, errors: 1}, 'Doom'), /Sprawdzono 3 z 10 · teraz: Doom · błędy: 1/);
  assert.match(PV.progressView({total: 10, done: 4, interrupted: true}), /przerwane/);
  let plans = PV.mergePlan([], S('1', 'up_to_date'));
  plans = PV.mergePlan(plans, S('1', 'plan_ready'));
  assert.equal(plans.length, 1);
  assert.equal(plans[0].ui_state, 'plan_ready');
});

test('stale plan is flagged', () => {
  assert.match(PV.summaryView(S('1', 'plan_ready', {stale: true})), /Plan nieaktualny/);
});

test('a plan opens on its first non-empty list', () => {
  assert.equal(PV.defaultKind({changed: 0, added: 63507, removed: 0, repair: 0}), 'added');
  assert.equal(PV.defaultKind({changed: 2, added: 5}), 'changed');
  assert.equal(PV.defaultKind({changed: 0, added: 0, removed: 0, repair: 3}), 'repair');
  assert.equal(PV.defaultKind({}), 'changed');
});
