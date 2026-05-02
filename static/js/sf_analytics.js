(function() {
    /**
     * Skillifly Analytics Tracker
     * Tracks page views, time spent, and project clicks.
     */
    const config = window.SF_ANALYTICS || {};
    const username = config.username;
    if (!username) return;

    // session_id for this visit
    let sessionId = sessionStorage.getItem('sf_analytics_sid');
    if (!sessionId) {
        sessionId = 'sid_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        sessionStorage.setItem('sf_analytics_sid', sessionId);
    }

    // Use absolute URL for production (custom domains), relative for local development
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const endpoint = isLocal ? '/api/track/' : 'https://skillifly.cloud/api/track/';
    const startTime = Date.now();

    function track(eventType, metadata = {}) {
        const duration = Math.floor((Date.now() - startTime) / 1000);
        const body = JSON.stringify({
            username: username,
            session_id: sessionId,
            event_type: eventType,
            duration: duration,
            ...metadata
        });

        if (navigator.sendBeacon) {
            navigator.sendBeacon(endpoint, body);
        } else {
            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
                keepalive: true
            }).catch(() => {});
        }
    }

    // Initial view track
    track('view');

    // Heartbeat to track time spent (every 20 seconds)
    const heartbeat = setInterval(() => {
        track('heartbeat');
    }, 20000);

    const trackedProjects = new Set();

    // Track clicks on elements with data-project-id
    document.addEventListener('click', (e) => {
        const projectLink = e.target.closest('[data-project-id]');
        if (projectLink) {
            const projectId = projectLink.getAttribute('data-project-id');
            if (!trackedProjects.has(projectId)) {
                trackedProjects.add(projectId);
                track('project_click', { project_id: projectId });
            }
        }
    });

    // Automatically track reels that come into view (since they autoplay on scroll)
    const projectObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const projectId = entry.target.getAttribute('data-project-id');
                if (projectId && !trackedProjects.has(projectId)) {
                    trackedProjects.add(projectId);
                    track('project_click', { project_id: projectId });
                }
            }
        });
    }, { threshold: 0.6 });

    function observeProjects() {
        document.querySelectorAll('.reel-slide[data-project-id]').forEach(el => {
            projectObserver.observe(el);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observeProjects);
    } else {
        observeProjects();
    }

    // Cleanup and final track
    window.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            track('exit');
        }
    });
})();
