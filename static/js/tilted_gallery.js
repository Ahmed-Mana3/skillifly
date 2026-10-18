/* ── Tilted gallery: a curved row of images ───────────────────────
 * Vanilla port of the "Scroll Tilted Grid" hero (TiltedGridHero), used by
 * the Minimal Gallery video-editor theme. One row of images streams from
 * right to left around the inside of a cylinder: the centre faces you flat,
 * the ends bend toward you, and both ends fade into the page.
 *
 * A CSS box can't bend, so every tile is cut into SLICES vertical strips,
 * each a flat facet of the cylinder showing its share of the image. The
 * strips sit still inside their tile, each turned a few degrees round the
 * cylinder's axis, and the tile (preserve-3d) is what moves: one rotateY
 * about that same axis carries the whole tile along the arc. A tile is one
 * animation, so its strips never drift apart. Only a tile's delay differs,
 * and that sets where on the arc it sits. The band is transform-only on the
 * compositor; the fade is a static mask over it.
 *
 * The only JS work is a ResizeObserver that sizes the loop, and a handler
 * that hands a tile its next image each time it wraps, out of sight.
 *
 * Usage:
 *   TiltedGallery.mount(el, [{src: '...'}, ...], {speed: 4, curve: 80, ...})
 * `el` must have a definite size; it becomes a size container. Options can
 * also come from data-* attributes on `el` (data-speed, data-tile-height,
 * data-aspect, data-gap, data-axis, data-curve, data-fade).
 * `el.dataset.tgState` reports 'running', 'empty' or 'unsupported'.
 * ─────────────────────────────────────────────────────────────── */
(function (root) {
    'use strict';

    // Strips per tile. Fewer starts to show corners along the top and
    // bottom edges where the curve is tight.
    var SLICES = 16;

    // Camera distance from the screen, as a multiple of the cylinder's
    // radius. Just past the axis, so the ends come right up to the lens.
    var CAMERA = 1.6;

    // A tile is never wider than this share of the frame, so a phone still
    // shows its neighbours instead of one tile edge to edge.
    var MAX_WIDTH = 55;

    // Never fetch more than this many images up front.
    var MAX_IMAGES = 12;

    /**
     * Cylinder radius, as a share of the frame's width, that puts the
     * frame's edge `bend` radians round the arc as seen through the camera:
     * r·sinθ · CAMERA / (CAMERA − 1 + cosθ) = width / 2, solved for r.
     */
    function arc(bend) {
        return (CAMERA - 1 + Math.cos(bend)) / (2 * CAMERA * Math.sin(bend));
    }

    function round4(n) { return +n.toFixed(4); }

    /**
     * Lays the loop on the cylinder. Angles come back in degrees: `unit` is
     * the arc one tile-height spans, `limit` how far round a tile's centre
     * can go before the whole tile is off-screen, and `sweep` how far round
     * the loop's ends sit. The loop reaches past `limit`, so a tile only
     * ever wraps out of sight, and holds a whole number of tiles so the gap
     * never stretches.
     */
    function measure(width, height, tile, aspect, gap, bend) {
        var h = Math.min((tile / 100) * height, ((MAX_WIDTH / 100) * width) / aspect);
        var radius = width * arc(bend);
        if (!(h > 0) || !(radius > 0)) return { columns: 2, sweep: 0, unit: 0, limit: 0 };
        var deg = function (rad) { return (rad * 180) / Math.PI; };
        var unit = deg(h / radius);
        var pitch = (aspect + gap / 100) * unit;
        var limit = deg(bend) + (aspect * unit) / 2;
        // Capped so a frame squeezed to a sliver can't mount thousands of tiles.
        var columns = Math.min(60, Math.max(2, Math.ceil((2 * limit) / pitch)));
        var sweep = round4((columns * pitch) / 2);
        return { columns: columns, sweep: sweep, unit: round4(unit), limit: round4(Math.min(sweep, limit)) };
    }

    function supported() {
        var css = root.CSS;
        return !!(css && css.supports && root.ResizeObserver &&
            css.supports('width', '1cqw') && css.supports('transform-style', 'preserve-3d'));
    }

    function option(opts, data, key, fallback) {
        var raw = opts[key] != null ? opts[key] : data[key];
        var n = parseFloat(raw);
        return isFinite(n) ? n : fallback;
    }

    var instances = 0;

    function mount(el, images, opts) {
        if (!el) return null;
        opts = opts || {};
        images = (images || []).filter(function (img) { return img && img.src; }).slice(0, MAX_IMAGES);
        if (!images.length) { el.dataset.tgState = 'empty'; return null; }
        if (!supported()) { el.dataset.tgState = 'unsupported'; return null; }

        var data = el.dataset;
        var speed = Math.max(0.5, option(opts, data, 'speed', 4));
        var tileHeight = option(opts, data, 'tileHeight', 26);
        var aspect = option(opts, data, 'aspect', 16 / 9);
        var gap = option(opts, data, 'gap', 6);
        var axis = option(opts, data, 'axis', 56);
        var curve = option(opts, data, 'curve', 80);
        var fade = option(opts, data, 'fade', 12);
        var bend = (Math.min(85, Math.max(5, curve)) * Math.PI) / 180;

        var id = ++instances;
        var orbit = 'tg-o-' + id;
        var tileClass = 'tg-t-' + id;
        var share = aspect / SLICES;
        var r = 100 * arc(bend);
        var radius = +r.toFixed(3) + 'cqw';
        // Every length is a multiple of the tile's height, which follows the
        // frame's height until MAX_WIDTH caps it on narrow screens.
        var unitLength = 'min(' + tileHeight + 'cqh, ' + round4(MAX_WIDTH / aspect) + 'cqw)';
        function u(n) { return 'calc(' + round4(n) + ' * var(--tg-u))'; }
        // Out to the axis, round it, back in: a box sits on the cylinder at
        // the angle rotateY gives it.
        function turn(deg) {
            return 'translateZ(' + radius + ') rotateY(' + round4(deg) + 'deg) translateZ(-' + radius + ')';
        }

        el.style.containerType = 'size';
        if (getComputedStyle(el).position === 'static') el.style.position = 'relative';

        var style = document.createElement('style');
        var mask = 'linear-gradient(90deg,transparent,#000 ' + fade + '%,#000 ' + (100 - fade) + '%,transparent)';
        var band = document.createElement('div');
        band.className = 'tg-band';
        band.setAttribute('aria-hidden', 'true');
        band.style.cssText =
            'position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .6s ease;' +
            '--tg-u:' + unitLength + ';' +
            // A shared vanishing point on the row's centre line, so the ends
            // grow evenly above and below it as they come toward the viewer.
            'perspective:' + +(r * CAMERA).toFixed(3) + 'cqw;' +
            'perspective-origin:50% ' + axis + '%;' +
            '-webkit-mask-image:' + mask + ';mask-image:' + mask + ';';
        el.appendChild(style);
        el.appendChild(band);

        var layout = null;
        var shown = {};
        var started = performance.now();

        function build(next) {
            layout = next;
            shown = {};
            var columns = next.columns, sweep = next.sweep, unit = next.unit, limit = next.limit;
            // Beyond `limit` a tile is wholly off-screen, so it is hidden there.
            // The loop's ends, where it wraps, fall inside that stretch.
            var hide = round4(((sweep - limit) / (2 * sweep || 1)) * 100);
            style.textContent =
                '@keyframes ' + orbit + '{' +
                'from{transform:' + turn(-sweep) + '}to{transform:' + turn(sweep) + '}' +
                '0%,' + hide + '%,' + (100 - hide) + '%,100%{visibility:hidden}' +
                (hide + 0.001) + '%,' + (100 - hide - 0.001) + '%{visibility:visible}}' +
                '.' + tileClass + '{position:absolute;transform-style:preserve-3d;will-change:transform}' +
                // !important because each tile's inline `animation` shorthand
                // resets animation-play-state to running, and inline wins.
                '.tg-paused .' + tileClass + '{animation-play-state:paused!important}' +
                // Pausing rather than removing the motion keeps the band whole:
                // every tile is already placed by its negative delay, so it
                // freezes as a finished still.
                '@media(prefers-reduced-motion:reduce){.' + tileClass + '{animation-play-state:paused!important}}';

            var duration = columns * speed;
            // Carry the time already run into the new delays, so a resize that
            // re-lays the loop doesn't jump the row back to its start.
            var elapsed = (performance.now() - started) / 1000;
            var frag = document.createDocumentFragment();
            for (var t = 0; t < columns; t++) {
                frag.appendChild(makeTile(t, columns, duration, elapsed, unit));
            }
            band.textContent = '';
            band.appendChild(frag);
        }

        function makeTile(t, columns, duration, elapsed, unit) {
            // Tile `columns - 1` starts nearest the exit and tile 0 furthest
            // back, so this numbers tiles in the order they come on.
            var first = columns - 1 - t;
            var img = images[first % images.length];
            var tile = document.createElement('div');
            tile.className = 'tg-tile ' + tileClass;
            tile.style.left = 'calc(50% - ' + u(aspect / 2) + ')';
            tile.style.top = 'calc(' + axis + '% - ' + u(0.5) + ')';
            tile.style.width = u(aspect);
            tile.style.height = u(1);
            tile.style.animation = orbit + ' ' + duration + 's linear ' + round4(-(t * speed + elapsed)) + 's infinite';

            for (var k = 0; k < SLICES; k++) {
                var slice = document.createElement('div');
                slice.className = 'tg-slice';
                slice.style.cssText =
                    'position:absolute;top:0;overflow:hidden;' +
                    'left:' + u((aspect - share) / 2) + ';' +
                    // Wider than its share, so neighbouring facets overlap and
                    // no hairline opens between them. Two pixels, not one: the
                    // centre of the row sits behind the screen plane, where
                    // perspective shrinks a 1px overlap below a device pixel.
                    'width:' + (k === SLICES - 1 ? u(share) : 'calc(' + u(share) + ' + 2px)') + ';' +
                    'height:' + u(1) + ';' +
                    'transform:' + turn((aspect / 2 - (k + 0.5) * share) * unit) + ';' +
                    (k === 0 ? 'border-radius:var(--tg-radius,6px) 0 0 var(--tg-radius,6px);' : '') +
                    (k === SLICES - 1 ? 'border-radius:0 var(--tg-radius,6px) var(--tg-radius,6px) 0;' : '');
                var pic = document.createElement('img');
                pic.alt = '';
                pic.draggable = false;
                pic.decoding = 'async';
                pic.src = img.src;
                pic.style.cssText =
                    'position:absolute;top:0;max-width:none;object-fit:cover;display:block;' +
                    'left:' + u(-k * share) + ';width:' + u(aspect) + ';height:' + u(1) + ';';
                slice.appendChild(pic);
                tile.appendChild(slice);
            }

            tile.addEventListener('animationiteration', function (e) {
                if (e.target !== tile) return;
                // elapsedTime counts whole loops, missed events included.
                var lap = Math.round(e.elapsedTime / duration);
                var next = lap * columns + first;
                if (shown[t] === next) return;
                shown[t] = next;
                var src = images[next % images.length].src;
                var pics = tile.getElementsByTagName('img');
                for (var i = 0; i < pics.length; i++) pics[i].src = src;
            });
            return tile;
        }

        function relayout(width, height) {
            var next = measure(width, height, tileHeight, aspect, gap, bend);
            if (layout && layout.columns === next.columns && layout.sweep === next.sweep && layout.unit === next.unit) return;
            build(next);
            if (band.style.opacity !== '1') requestAnimationFrame(function () { band.style.opacity = '1'; });
        }

        // Fetch every image up front. A tile picks up its next one just before
        // it comes back into view, too late to start loading it then.
        images.forEach(function (img) { new Image().src = img.src; });

        var ro = new ResizeObserver(function (entries) {
            var box = entries[0].contentRect;
            relayout(box.width, box.height);
        });
        ro.observe(el);

        // Off-screen, the band stops: no compositor work while you read on.
        var io = null;
        if (root.IntersectionObserver) {
            io = new IntersectionObserver(function (entries) {
                band.classList.toggle('tg-paused', !entries[0].isIntersecting);
            });
            io.observe(el);
        }

        el.dataset.tgState = 'running';
        return {
            band: band,
            pause: function () { band.classList.add('tg-paused'); },
            resume: function () { band.classList.remove('tg-paused'); },
            destroy: function () {
                ro.disconnect();
                if (io) io.disconnect();
                band.remove();
                style.remove();
                delete el.dataset.tgState;
            }
        };
    }

    var api = { mount: mount, measure: measure, arc: arc, SLICES: SLICES, CAMERA: CAMERA, MAX_WIDTH: MAX_WIDTH };
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root && root.document) root.TiltedGallery = api;
})(typeof window !== 'undefined' ? window : globalThis);
