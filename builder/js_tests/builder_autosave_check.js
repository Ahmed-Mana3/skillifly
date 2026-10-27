// Logic check for the BXAutosave save queue in static/js/builder_v2.js, run by
// builder/test_autosave.py. Loads the real script against a tiny DOM stub, swaps in a
// fake fetch and short timers, and checks what gets sent and when.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'builder_v2.js'), 'utf8');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
// Wait for something that should happen, without depending on how busy the machine is.
async function until(check, ms = 3000) {
  const end = Date.now() + ms;
  while (!check() && Date.now() < end) await sleep(5);
}

function load() {
  const context = {
    window: { matchMedia: () => ({ matches: false }), addEventListener() {} },
    document: {
      addEventListener() {},
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
      body: { classList: { add() {} } },
    },
    location: { hash: '' },
    history: { replaceState() {} },
    console, setTimeout, clearTimeout, FormData, Promise, Array, Object, Math, JSON, Map, Set,
  };
  context.window.document = context.document;
  vm.createContext(context);
  vm.runInContext(source + '\n;globalThis.__A = BXAutosave;', context);
  return context.__A;
}

// A builder row: inputs named like Django's formset ("skills-0-skill"), inside a .bx-item.
function makeRow(kind, values, opts) {
  opts = opts || {};
  const el = {
    classList: { contains: c => c === 'bx-item' },
    parentElement: { id: kind + '-container' },
    closest: () => null,
  };
  const fields = [];
  const make = (name, value, extra) => {
    const f = Object.assign({
      name, value, type: 'text', required: false, invalid: false,
      checkValidity() { return !this.invalid && !(this.required && !this.value); },
      closest: sel => (sel === (kind === 'personal' ? '#panel-identity' : '.bx-item') ? el : null),
      setAttribute() {}, removeAttribute() {},
    }, extra || {});
    fields.push(f);
    return f;
  };
  const prefix = kind === 'personal' ? '' : kind + '-0-';
  if (kind !== 'personal') make(prefix + 'id', opts.id ? String(opts.id) : '', { type: 'hidden' });
  const byName = {};
  Object.keys(values).forEach(name => {
    byName[name] = make(prefix + name, values[name], { required: (opts.required || []).indexOf(name) !== -1 });
  });
  el.querySelectorAll = () => fields;
  el.querySelector = sel => (sel === 'input[name$="-id"]' ? fields[0] : null);
  return { el, f: byName, idInput: fields[0] };
}

// fetch double: answers from `replies` in order (a function gets the call), records every call.
function fakeFetch(replies) {
  const calls = [];
  const fetch = async (url, opts) => {
    const call = { url, data: Object.fromEntries(opts.body.entries()) };
    calls.push(call);
    let reply = replies.length ? replies.shift() : { status: 200, body: { ok: true, id: 1 } };
    if (typeof reply === 'function') reply = await reply(call);
    if (reply === 'network') throw new TypeError('Failed to fetch');
    return { status: reply.status, ok: reply.status >= 200 && reply.status < 300, json: async () => reply.body };
  };
  return { fetch, calls };
}

function setUp(replies) {
  const A = load();
  Object.assign(A, {
    on: true, base: '/builder/api/', lang: 'en', statusEl: null,
    DEBOUNCE_MS: 20, DELETE_DELAY_MS: 40, RETRY_DELAYS_MS: [10, 10, 10],
  });
  const fake = fakeFetch(replies || []);
  A.fetch = fake.fetch;
  return { A, calls: fake.calls };
}

const type = (A, field, value) => { field.value = value; A.onFieldEvent(field, false); };

(async () => {
  // --- typing is debounced into one request with the latest value ------------------
  {
    const { A, calls } = setUp();
    const row = makeRow('skills', { skill: 'Ca' }, { id: 7, required: ['skill'] });
    type(A, row.f.skill, 'Cap');
    type(A, row.f.skill, 'CapC');
    type(A, row.f.skill, 'CapCut');
    assert.strictEqual(calls.length, 0, 'nothing is sent while typing');
    await sleep(60);
    assert.strictEqual(calls.length, 1, 'one request after the pause');
    assert.strictEqual(calls[0].url, '/builder/api/skills/7/');
    assert.deepStrictEqual(calls[0].data, { lang: 'en', skill: 'CapCut' });
    assert.strictEqual(A.overallState(), 'saved');
  }

  // --- an update sends only the changed fields ---------------------------------------
  {
    const { A, calls } = setUp();
    const row = makeRow('projects', { name: 'Cut', url: 'https://youtu.be/x', description: '' }, { id: 3 });
    row.f.url.value = 'https://youtu.be/y';
    A.onFieldEvent(row.f.url, true);
    await sleep(20);
    assert.deepStrictEqual(calls[0].data, { lang: 'en', url: 'https://youtu.be/y' });
  }

  // --- a new row waits for its required fields, then is created exactly once -----------
  {
    let release;
    const { A, calls } = setUp([
      () => new Promise(resolve => { release = () => resolve({ status: 201, body: { ok: true, id: 42 } }); }),
      { status: 200, body: { ok: true, id: 42 } },
    ]);
    const row = makeRow('links', { name: '', url: '' }, { required: ['name', 'url'] });
    type(A, row.f.name, 'Instagram');
    await sleep(40);
    assert.strictEqual(calls.length, 0, 'not created while a required field is empty');
    assert.strictEqual(A.overallState(), 'draft');

    type(A, row.f.url, 'instagram.com/me');
    await sleep(40);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/builder/api/links/', 'a create');
    assert.deepStrictEqual(calls[0].data, { lang: 'en', name: 'Instagram', url: 'instagram.com/me' }, 'with the whole row');

    type(A, row.f.name, 'Instagram Reels'); // edited while the create is still in flight
    await sleep(40);
    assert.strictEqual(calls.length, 1, 'the edit waits for the create');
    release();
    await sleep(40);
    assert.strictEqual(calls.length, 2);
    assert.strictEqual(calls[1].url, '/builder/api/links/42/', 'then goes out as an update, not a second create');
    assert.deepStrictEqual(calls[1].data, { lang: 'en', name: 'Instagram Reels' });
    assert.strictEqual(row.idInput.value, '42', 'the new id is written back into the row');
  }

  // --- a value the browser knows is wrong is held back, the rest still saves ------------
  {
    const { A, calls } = setUp();
    const row = makeRow('personal', { title: 'Editor', phone: '' });
    row.f.phone.invalid = true;
    type(A, row.f.phone, 'call me');
    type(A, row.f.title, 'Colorist');
    await sleep(60);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/builder/api/personal/');
    assert.deepStrictEqual(calls[0].data, { lang: 'en', title: 'Colorist' });
    assert.strictEqual(A.overallState(), 'invalid', 'the held field still counts as unsaved');
  }

  // --- a value the server refuses never blocks the others --------------------------------
  {
    const { A, calls } = setUp([
      { status: 400, body: { ok: false, errors: { booking_url: ['Enter a full booking link.'] } } },
      { status: 200, body: { ok: true } },
      { status: 200, body: { ok: true } },
    ]);
    const row = makeRow('personal', { booking_url: '', bio: '' });
    type(A, row.f.booking_url, 'not a link');
    type(A, row.f.bio, 'Hi there');
    await sleep(60);
    assert.strictEqual(calls.length, 2, 'refused, then sent again without the refused value');
    assert.deepStrictEqual(calls[0].data, { lang: 'en', booking_url: 'not a link', bio: 'Hi there' });
    assert.deepStrictEqual(calls[1].data, { lang: 'en', bio: 'Hi there' });
    assert.strictEqual(A.overallState(), 'invalid');

    type(A, row.f.bio, 'Hi there!'); // other edits keep leaving the refused value out
    await sleep(60);
    assert.deepStrictEqual(calls[2].data, { lang: 'en', bio: 'Hi there!' });

    type(A, row.f.booking_url, 'calendly.com/me'); // once the user changes it, it goes out
    await sleep(60);
    assert.deepStrictEqual(calls[3].data, { lang: 'en', booking_url: 'calendly.com/me' });
    assert.strictEqual(A.overallState(), 'saved');
  }

  // --- network trouble: retried, and after three tries the user gets a Retry -------------
  {
    const { A, calls } = setUp(['network', { status: 200, body: { ok: true } }]);
    const row = makeRow('skills', { skill: 'Resolve' }, { id: 1 });
    type(A, row.f.skill, 'DaVinci Resolve');
    await until(() => calls.length === 2 && A.overallState() === 'saved');
    assert.strictEqual(calls.length, 2, 'retried after the failure');
    assert.deepStrictEqual(calls[1].data, { lang: 'en', skill: 'DaVinci Resolve' });
    assert.strictEqual(A.overallState(), 'saved');
  }
  {
    const { A, calls } = setUp(['network', 'network', 'network', { status: 500, body: {} }]);
    const row = makeRow('skills', { skill: 'Resolve' }, { id: 1 });
    type(A, row.f.skill, 'Avid');
    await until(() => A.overallState() === 'error');
    assert.strictEqual(calls.length, 4, 'first try plus three retries');
    assert.strictEqual(A.overallState(), 'error');
    A.retryAll();
    await until(() => calls.length === 5 && A.overallState() === 'saved');
    assert.strictEqual(calls.length, 5, 'Retry sends it again');
    assert.deepStrictEqual(calls[4].data, { lang: 'en', skill: 'Avid' });
    assert.strictEqual(A.overallState(), 'saved');
  }

  // --- signed out: nothing lost, the pill says so ---------------------------------------
  {
    const { A, calls } = setUp([{ status: 401, body: { ok: false, error: 'signed_out' } }]);
    const row = makeRow('skills', { skill: 'x' }, { id: 1 });
    type(A, row.f.skill, 'Blender');
    await sleep(60);
    assert.strictEqual(calls.length, 1, 'not retried on its own');
    assert.strictEqual(A.overallState(), 'signed_out');
    A.retryAll();
    await sleep(30);
    assert.strictEqual(calls.length, 2);
    assert.strictEqual(calls[1].data.skill, 'Blender');
  }

  // --- removing waits for the Undo window; Undo cancels it --------------------------------
  {
    const { A, calls } = setUp();
    const row = makeRow('links', { name: 'X', url: 'https://x.com' }, { id: 5 });
    A.onRemove(row.el);
    await sleep(15);
    A.onRestore(row.el);
    await sleep(60);
    assert.strictEqual(calls.length, 0, 'undone in time: nothing deleted');

    A.onRemove(row.el);
    await sleep(70);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/builder/api/links/5/delete/');

    A.onRestore(row.el); // Undo after the delete went out: the row is created again
    await sleep(30);
    assert.strictEqual(calls[1].url, '/builder/api/links/');
    assert.deepStrictEqual(calls[1].data, { lang: 'en', name: 'X', url: 'https://x.com' });
  }

  // --- leaving the page sends a waiting delete at once ------------------------------------
  {
    const { A, calls } = setUp();
    const row = makeRow('skills', { skill: 'x' }, { id: 9 });
    A.onRemove(row.el);
    A.flushOnExit();
    await sleep(10);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/builder/api/skills/9/delete/');
  }

  // --- a row removed elsewhere is added back when the user keeps editing it ---------------
  {
    const { A, calls } = setUp([{ status: 404, body: {} }, { status: 201, body: { ok: true, id: 77 } }]);
    const row = makeRow('skills', { skill: 'x' }, { id: 9 });
    type(A, row.f.skill, 'After Effects');
    await sleep(60);
    assert.strictEqual(calls[1].url, '/builder/api/skills/');
    assert.strictEqual(row.idInput.value, '77');
  }

  // --- the pill shows the worst state ------------------------------------------------------
  {
    const { A } = setUp();
    const a = A.stateFor(makeRow('skills', {}).el, 'skills');
    const b = A.stateFor(makeRow('links', {}).el, 'links');
    a.state = 'saving'; b.state = 'draft';
    assert.strictEqual(A.overallState(), 'saving');
    b.state = 'error';
    assert.strictEqual(A.overallState(), 'error');
    b.removed = true;
    assert.strictEqual(A.overallState(), 'saving', 'removed rows do not count');
  }

  // --- switched off: nothing happens ---------------------------------------------------------
  {
    const { A, calls } = setUp();
    A.on = false;
    const row = makeRow('skills', { skill: 'x' }, { id: 1 });
    type(A, row.f.skill, 'y');
    await sleep(40);
    assert.strictEqual(calls.length, 0);
  }

  console.log('autosave checks passed');
})().catch(err => {
  console.error(err);
  process.exit(1);
});
