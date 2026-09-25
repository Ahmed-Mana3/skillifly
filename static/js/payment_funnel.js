(function () {
    /**
     * Skillifly Payment Funnel Tracker
     * Sends button-click events from the payment flow to the server so admins
     * can see how the payment page is used.
     *
     * Elements opt in via data-pf-action. Clicks on the payment method radios
     * (input[name="payment_method"]) are tracked automatically.
     */
    var config = window.SF_PAYMENT_FUNNEL || {};
    var page = config.page || '';
    if (!page) return;

    var STORAGE_KEY = 'sf_payment_vid';
    var YEAR = 60 * 60 * 24 * 365;

    function readCookie(name) {
        var parts = document.cookie ? document.cookie.split('; ') : [];
        for (var i = 0; i < parts.length; i++) {
            var eq = parts[i].indexOf('=');
            if (eq > -1 && parts[i].slice(0, eq) === name) {
                return decodeURIComponent(parts[i].slice(eq + 1));
            }
        }
        return '';
    }

    function readStorage(key) {
        try { return localStorage.getItem(key) || ''; } catch (e) { return ''; }
    }

    function writeStorage(key, value) {
        try { localStorage.setItem(key, value); } catch (e) {}
    }

    function newVid() {
        return 'pvid_' + Math.random().toString(36).slice(2, 11) + Date.now().toString(36);
    }

    // The server renders the id it already used for this page view, so the click
    // beacon merges with the open instead of showing up as a second visitor.
    // Cookie wins so the id survives localStorage being cleared.
    var vid = config.vid || readCookie(STORAGE_KEY) || readStorage(STORAGE_KEY) || newVid();
    writeStorage(STORAGE_KEY, vid);
    document.cookie = STORAGE_KEY + '=' + encodeURIComponent(vid) +
        '; path=/; max-age=' + YEAR + '; SameSite=Lax';

    // Always same-origin: the endpoint lives on the main site (/api/ is never
    // rewritten by the custom-domain middleware) and a relative URL keeps the
    // first-party cookie attached in dev (lvh.me) and on custom domains.
    var endpoint = '/api/payment-funnel/';

    function post(body) {
        // text/plain is CORS-safelisted, so sendBeacon never needs a preflight.
        return fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
            body: body,
            keepalive: true,
            credentials: 'same-origin'
        });
    }

    function send(action, planType) {
        var body = JSON.stringify({
            event_type: 'click',
            page: page,
            action: action,
            plan_type: planType || config.plan || '',
            visitor_id: vid
        });

        // sendBeacon survives the page unloading, but it is dropped when the
        // queue is full or the payload is rejected - fall back to fetch.
        var queued = false;
        if (navigator.sendBeacon) {
            try {
                queued = navigator.sendBeacon(
                    endpoint,
                    new Blob([body], { type: 'text/plain;charset=UTF-8' })
                );
            } catch (e) {
                queued = false;
            }
        }
        if (!queued) {
            post(body).catch(function () {});
        }
    }

    function currentMethod() {
        var el = document.querySelector('input[name="payment_method"]:checked');
        return el ? el.value : '';
    }

    function couponInField() {
        var el = document.getElementById('couponCode') ||
            document.querySelector('input[name="coupon"]');
        return el && el.value ? el.value.trim() : '';
    }

    // Track explicit data-pf-action buttons/links
    document.addEventListener('click', function (e) {
        var el = e.target;
        if (!el || !el.closest) return;
        var target = el.closest('[data-pf-action]');
        if (!target) return;
        var action = target.getAttribute('data-pf-action');
        if (!action) return;

        var planType = target.getAttribute('data-pf-plan') || '';

        // Continue with "card" selected actually leaves for Fawaterk - log both
        if (action === 'continue' && currentMethod() === 'card') {
            send('card_checkout', planType);
        }
        // Picking a plan with a coupon typed in is a redemption attempt
        if (action.indexOf('plan_') === 0 && couponInField()) {
            send('apply_coupon', planType);
        }
        send(action, planType);
    });

    // Track payment-method selection
    document.addEventListener('change', function (e) {
        if (e.target && e.target.name === 'payment_method' && e.target.value) {
            send('method_' + e.target.value);
        }
    });
})();
