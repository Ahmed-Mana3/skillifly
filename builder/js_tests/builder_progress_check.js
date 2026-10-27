// Logic check for static/js/builder_v2.js, run by builder/test_builder_js.py.
// Loads the real script against a tiny DOM stub and exercises the pure logic that
// PR-7 changed: the per-category section order and the "Client-ready x/3" counter.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'builder_v2.js'), 'utf8');

function makeInput(name, value, extra) {
  return Object.assign({
    name, value,
    closest() { return this.item || null; },
  }, extra || {});
}

function load(i18n) {
  const listeners = [];
  const context = {
    window: Object.assign({ matchMedia: () => ({ matches: false }) }, i18n ? { BuilderI18n: i18n } : {}),
    document: {
      addEventListener: (type, fn) => listeners.push([type, fn]),
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => ({}),
    },
    location: { hash: '' },
    history: { replaceState() {} },
    console, setTimeout, clearTimeout, URLSearchParams, Array, Object, Math, JSON,
  };
  context.window.document = context.document;
  vm.createContext(context);
  // `const BX = ...` is not exposed on the context object, so append an export.
  vm.runInContext(source + '\n;globalThis.__BX = BX; globalThis.__bxt = bxt;', context);
  return { BX: context.__BX, bxt: context.__bxt, context };
}

function formWith(values) {
  return {
    querySelector(sel) {
      const m = /\[name="(.+)"\]/.exec(sel);
      return m && m[1] in values ? { value: values[m[1]] } : null;
    },
  };
}

function projectsContainer(names, opts) {
  opts = opts || {};
  const inputs = names.map((n, i) => {
    const input = makeInput('projects-' + i + '-name', n);
    input.item = {
      classList: { contains: c => c === 'is-removed' && opts.removed === i },
      style: { display: opts.hidden === i ? 'none' : '' },
    };
    return input;
  });
  return { querySelectorAll: sel => (sel === '[name$="-name"]' ? inputs : []) };
}

function counter(BX, values, names, opts) {
  const container = projectsContainer(names, opts);
  const ctx = Object.assign(Object.create(BX), { form: formWith(values) });
  // clientReadyCount reads the container through document.getElementById.
  return function run(document) {
    document.getElementById = id => (id === 'projects-container' ? container : null);
    return BX.clientReadyCount.call(ctx);
  };
}

const { BX, bxt, context } = load();

// --- section order -------------------------------------------------------
assert.strictEqual(BX.ORDERS_BY_CATEGORY.video_editor[0], 'projects', 'video editors start with their work');
assert.strictEqual(BX.ORDERS_BY_CATEGORY.video_editor[1], 'identity');
assert.deepStrictEqual(Array.from(BX.EXTRAS_BY_CATEGORY.video_editor), ['experience', 'education', 'creators', 'order'],
  'the optional sections fold under "More sections"');
assert.strictEqual(BX.ORDERS_BY_CATEGORY.developer[0], 'identity', 'other categories are unchanged');
assert.strictEqual(BX.ORDERS_BY_CATEGORY.student[0], 'identity');
const eight = ['identity', 'projects', 'skills', 'creators', 'reviews', 'experience', 'education', 'links', 'order'];
assert.deepStrictEqual([...BX.ORDERS_BY_CATEGORY.video_editor].sort(), [...eight].sort(), 'same sections, new order');

// --- client-ready counter ------------------------------------------------
const doc = context.document;
const run = (values, names, opts) => counter(BX, values, names, opts)(doc);

assert.strictEqual(run({ title: 'Video Editor' }, []), 0, 'placeholder title and no videos');
assert.strictEqual(run({ title: 'Video Editor' }, ['', '']), 0, 'blank project rows do not count');
assert.strictEqual(run({ title: 'Colorist' }, []), 1, 'a real title counts');
assert.strictEqual(run({ title: 'مونتير فيديو' }, []), 0, 'Arabic placeholder title');
assert.strictEqual(run({ title: 'VIDEO EDITOR' }, []), 0, 'placeholder check is case-insensitive');
assert.strictEqual(run({ title: 'Colorist', booking_url: 'https://wa.me/20100' }, []), 2, 'booking link counts as contact');
assert.strictEqual(run({ title: 'Colorist', phone: '+201001234567' }, []), 2, 'phone counts as contact');
assert.strictEqual(run({ title: 'Colorist', booking_url: 'x' }, ['A', 'B', 'C']), 3, 'three videos complete it');
assert.strictEqual(run({ title: 'x' }, ['A', 'B']), 1, 'two videos is not enough');
assert.strictEqual(run({ title: '' }, ['A', 'B', 'C']), 1, 'three videos alone = 1/3');
assert.strictEqual(run({ title: 'x' }, ['A', 'B', 'C'], { removed: 2 }), 1, 'removed rows are ignored');
assert.strictEqual(run({ title: 'x' }, ['A', 'B', 'C'], { hidden: 0 }), 1, 'hidden rows are ignored');

// --- initial panel: switching silently must not scroll, focus or touch the hash ----
{
  const calls = { scroll: 0, focus: 0, hash: 0 };
  const el = (key) => ({
    dataset: { navKey: key },
    classList: { _on: false, add() { this._on = true; }, remove() { this._on = false; }, toggle() {} },
    setAttribute() {}, removeAttribute() {}, focus() { calls.focus += 1; }, getBoundingClientRect: () => ({ top: 0 }),
  });
  const projects = el('projects'), identity = el('identity');
  const fake = {
    currentKey: 'identity', panelByKey: { projects, identity }, navItems: [], navByKey: {},
    order: ['projects', 'identity'],
  };
  context.window.scrollTo = () => { calls.scroll += 1; };
  context.history.replaceState = () => { calls.hash += 1; };
  context.window.pageYOffset = 0;

  BX.goTo.call(fake, 'projects', { silent: true });
  assert.strictEqual(fake.currentKey, 'projects', 'the panel does switch');
  assert.deepStrictEqual(calls, { scroll: 0, focus: 0, hash: 0 }, 'but nothing scrolls, focuses or rewrites the URL');

  fake.currentKey = 'identity';
  BX.goTo.call(fake, 'projects');   // a real navigation still does all three
  assert.strictEqual(calls.hash, 1);
  assert.strictEqual(calls.scroll, 1);
  assert.strictEqual(calls.focus, 1);

  // No hash on load: open the category's first section silently; a hash deep-links normally.
  const opened = [];
  const loader = { order: ['projects', 'identity'], currentKey: 'identity', goTo: (k, o) => opened.push([k, o]) };
  context.location.hash = '';
  BX.openFromHash.call(loader);
  // (objects built inside the vm context have another Object.prototype: compare as JSON)
  assert.strictEqual(JSON.stringify(opened), '[["projects",{"silent":true}]]');
  opened.length = 0;
  context.location.hash = '#identity';
  BX.openFromHash.call(loader);
  assert.strictEqual(JSON.stringify(opened), '[["identity",null]]', 'deep links keep their normal scrolling behaviour');
  context.location.hash = '';
}

// --- live progress: many keystrokes in one frame cost a single update ---------
{
  const frames = [];
  context.window.requestAnimationFrame = cb => { frames.push(cb); return frames.length; };
  let updates = 0;
  const fake = { _progressFrame: 0, updateNavStates() { updates += 1; } };
  for (let i = 0; i < 25; i++) BX.scheduleProgress.call(fake);
  assert.strictEqual(frames.length, 1, 'one frame requested no matter how many inputs');
  assert.strictEqual(updates, 0, 'nothing runs before the frame fires');
  frames[0]();
  assert.strictEqual(updates, 1);
  BX.scheduleProgress.call(fake);   // the next keystroke after the frame ran schedules again
  assert.strictEqual(frames.length, 2);
  delete context.window.requestAnimationFrame;
  const timers = [];
  const realSetTimeout = context.setTimeout;
  context.setTimeout = (fn) => { timers.push(fn); return timers.length; };
  const fake2 = { _progressFrame: 0, updateNavStates() { updates += 1; } };
  BX.scheduleProgress.call(fake2);  // falls back to a timer when rAF is unavailable
  assert.strictEqual(timers.length, 1);
  context.setTimeout = realSetTimeout;
}

// --- strings ----------------------------------------------------------------
assert.strictEqual(bxt('clientReadyOf', { done: 2 }), 'Client-ready 2/3');
const ar = load({ clientReadyOf: 'جاهز للعملاء {done}/3' });
assert.strictEqual(ar.bxt('clientReadyOf', { done: 1 }), 'جاهز للعملاء 1/3');

console.log('builder_v2.js logic checks passed');
