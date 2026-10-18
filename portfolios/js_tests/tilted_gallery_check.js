/* Headless checks for static/js/tilted_gallery.js (run by portfolios/test_minimal_gallery.py).
 *
 * The layout maths was ported from the TiltedGridHero React component. This
 * keeps a literal transcription of the original `arc`/`measure` and checks the
 * port returns the same layout across a spread of frame sizes and settings.
 */
'use strict';
const assert = require('assert');
const path = require('path');

const gallery = require(path.join(__dirname, '..', '..', 'static', 'js', 'tilted_gallery.js'));

// ── Original component maths (tilted-grid-hero.tsx), unchanged ──
const CAMERA = 1.6;
const MAX_WIDTH = 55;
function arc(bend) {
    return (CAMERA - 1 + Math.cos(bend)) / (2 * CAMERA * Math.sin(bend));
}
function measure(width, height, tile, aspect, gap, bend) {
    const h = Math.min((tile / 100) * height, ((MAX_WIDTH / 100) * width) / aspect);
    const radius = width * arc(bend);
    if (!(h > 0) || !(radius > 0)) return { columns: 2, sweep: 0, unit: 0, limit: 0 };
    const deg = (rad) => (rad * 180) / Math.PI;
    const unit = deg(h / radius);
    const pitch = (aspect + gap / 100) * unit;
    const limit = deg(bend) + (aspect * unit) / 2;
    const columns = Math.min(60, Math.max(2, Math.ceil((2 * limit) / pitch)));
    const round = (n) => +n.toFixed(4);
    const sweep = round((columns * pitch) / 2);
    return { columns, sweep, unit: round(unit), limit: round(Math.min(sweep, limit)) };
}

let checks = 0;
function check(fn) { fn(); checks++; }

const rad = (d) => (d * Math.PI) / 180;
const sizes = [[1440, 900], [1200, 560], [1920, 1080], [2560, 1100], [1024, 768], [768, 1024], [390, 844], [320, 568], [600, 600]];
const settings = [
    [26, 16 / 9, 6, 80], [20, 16 / 9, 6, 60], [32, 4 / 3, 10, 45], [26, 9 / 16, 6, 80], [26, 16 / 9, 0, 85], [26, 16 / 9, 6, 5],
];

for (const [w, h] of sizes) {
    for (const [tile, aspect, gap, curve] of settings) {
        check(() => assert.deepStrictEqual(
            gallery.measure(w, h, tile, aspect, gap, rad(curve)),
            measure(w, h, tile, aspect, gap, rad(curve)),
            `measure(${w}x${h}, tile=${tile}, aspect=${aspect}, gap=${gap}, curve=${curve})`,
        ));
    }
}

for (const curve of [5, 30, 60, 80, 85]) {
    check(() => assert.strictEqual(gallery.arc(rad(curve)), arc(rad(curve))));
}

// The theme's settings: a handful of tiles on every screen, and the loop always
// reaches past the point where a tile leaves the frame (so wraps are unseen).
const themeLayouts = { '1440x900': 4, '1200x560': 5, '768x1024': 3, '390x844': 3 };
for (const [size, columns] of Object.entries(themeLayouts)) {
    const [w, h] = size.split('x').map(Number);
    const layout = gallery.measure(w, h, 26, 16 / 9, 6, rad(80));
    check(() => assert.strictEqual(layout.columns, columns, size));
    check(() => assert.ok(layout.limit <= layout.sweep, size + ' limit <= sweep'));
}

// Degenerate frames fall back to the minimum loop instead of dividing by zero.
for (const [w, h] of [[0, 0], [0, 500], [500, 0]]) {
    check(() => assert.deepStrictEqual(gallery.measure(w, h, 26, 16 / 9, 6, rad(80)),
        { columns: 2, sweep: 0, unit: 0, limit: 0 }));
}

// A sliver-thin frame is capped at 60 tiles.
check(() => assert.ok(gallery.measure(4000, 2, 26, 16 / 9, 6, rad(80)).columns <= 60));

check(() => assert.strictEqual(gallery.SLICES, 16));

console.log(`tilted_gallery: ${checks} checks passed`);
