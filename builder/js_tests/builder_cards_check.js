// Logic check for the builder's video cards, skill chips and links (static/js/builder_v2.js),
// run by builder/test_autosave.py. Pure functions only, against a tiny DOM stub.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'builder_v2.js'), 'utf8');
const context = {
  window: { matchMedia: () => ({ matches: false }), addEventListener() {} },
  document: { addEventListener() {}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] },
  location: { hash: '' }, history: { replaceState() {} },
  console, setTimeout, clearTimeout, URL, Array, Object, Math, JSON, Set, Map,
};
context.window.document = context.document;
vm.createContext(context);
vm.runInContext(source + '\n;Object.assign(globalThis, { __BX: BX, __V: BXVideos, __S: BXSkills, __L: BXLinks, __A: BXAutosave });', context);
const { __BX: BX, __V: V, __S: S, __L: L, __A: A } = context;

// --- links: the name comes from the URL -------------------------------------------------
const cases = {
  'instagram.com/sara': 'Instagram',
  'https://www.instagram.com/sara/': 'Instagram',
  'youtu.be/dQw4w9WgXcQ': 'YouTube',
  'https://m.youtube.com/@sara': 'YouTube',
  'wa.me/201001234567': 'WhatsApp',
  'https://x.com/sara': 'X',
  'twitter.com/sara': 'X',
  'behance.net/sara': 'Behance',
  'https://sara.studio/reel': 'sara.studio',
  '': '',
  'not a url at all': '',
};
Object.keys(cases).forEach(url => assert.strictEqual(L.platformFromUrl(url), cases[url], url));

// --- video cards -----------------------------------------------------------------------
assert.strictEqual(V.youtubeThumb('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
assert.strictEqual(V.youtubeThumb('https://youtube.com/shorts/abcdefghijk'), 'https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg');
assert.strictEqual(V.youtubeThumb('https://vimeo.com/76979871'), '', 'no guessed thumbnail for other hosts');
assert.strictEqual(V.hostOf('vimeo.com/123'), 'vimeo.com');
assert.strictEqual(V.hostOf('https://www.tiktok.com/@sara/video/1'), 'tiktok.com');

// A new video row is created once it has a link or a title, not before.
const field = value => ({ value, type: 'text', required: false, checkValidity: () => true });
assert.strictEqual(A.readyToCreate({ url: field(''), name: field(''), description: field('Colour') }, 'projects'), false);
assert.strictEqual(A.readyToCreate({ url: field('youtu.be/x'), name: field('') }, 'projects'), true, 'a link alone is enough');
assert.strictEqual(A.readyToCreate({ url: field(''), name: field('Brand film') }, 'projects'), true, 'so is a title');
assert.strictEqual(A.readyToCreate({ skill: field('Blender') }, 'skills'), true);

// --- readiness: a video with only a link counts ---------------------------------------
{
  const item = url => ({ classList: { contains: () => false }, style: {}, querySelector: () => ({ value: url }) });
  const nameInput = (value, url) => ({ value, closest: () => item(url) });
  const container = { querySelectorAll: () => [nameInput('', 'youtu.be/a'), nameInput('Cut', ''), nameInput('', '')] };
  context.document.getElementById = id => (id === 'projects-container' ? container : null);
  const ctx = Object.assign(Object.create(BX), { form: { querySelector: () => null } });
  const items = BX.clientReadyItems.call(ctx);
  assert.strictEqual(items.videoCount, 2, 'link-only and title-only rows count, empty ones do not');
  assert.strictEqual(items.videos, false);
  context.document.getElementById = () => null;
}

// --- skills: a saved skill matches its preset in either language --------------------------
{
  const preset = (label, names) => ({ dataset: { skill: label, names } });
  S.presets = [preset('DaVinci Resolve', 'davinci resolve'), preset('تصحيح الألوان', 'color grading|تصحيح الألوان')];
  assert.strictEqual(S.presetFor('DaVinci Resolve'), S.presets[0]);
  assert.strictEqual(S.presetFor('  davinci RESOLVE '), S.presets[0], 'case and spaces do not matter');
  assert.strictEqual(S.presetFor('Color grading'), S.presets[1], 'an English name matches the Arabic chip');
  assert.strictEqual(S.presetFor('Blender'), null, 'own skills are not presets');
}

console.log('card checks passed');
