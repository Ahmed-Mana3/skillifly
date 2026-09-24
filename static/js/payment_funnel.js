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

    // Persistent visitor id — reused across steps/pages so opens merge per visitor
    var vid = localStorage.getItem('sf_payment_vid');
    if (!vid) {
        vid = 'pvid_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        try { localStorage.setItem('sf_payment_vid', vid); } catch (e) {}
    }
    document.cookie = 'sf_payment_vid=' + vid + '; path=/; max-age=' + (60 * 60 * 24 * 365);

    var isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    var endpoint = isLocal ? '/api/payment-funnel/' : 'https://skillifly.cloud/api/payment-funnel/';

    function send(action, extra) {
        var planType = (extra && extra.plan_type) || config.plan || '';
        var body = JSON.stringify({
            event_type: 'click',
            page: page,
            action: action,
            plan_type: planType,
            visitor_id: vid
        });
        if (navigator.sendBeacon) {
            navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
        } else {
            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
                keepalive: true
            }).catch(function () {});
        }
    }

    function currentMethod() {
        var el = document.querySelector('input[name="payment_method"]:checked');
        return el ? el.value : '';
    }

    // Track explicit data-pf-action buttons/links
    document.addEventListener('click', function (e) {
        var target = e.target.closest('[data-pf-action]');
        if (!target) return;
        var action = target.getAttribute('data-pf-action');
        if (!action) return;

        // Continue with "card" selected actually leaves for Fawaterk — log both
        if (action === 'continue' && currentMethod() === 'card') {
            send('card_checkout');
        }
        send(action);
    });

    // Track payment-method selection
    document.addEventListener('change', function (e) {
        if (e.target && e.target.name === 'payment_method' && e.target.value) {
            send('method_' + e.target.value);
        }
    });
})();