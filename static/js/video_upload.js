/* Skillifly — direct-to-Cloudflare video upload (tus protocol).
 *
 * The file bytes go straight from the browser to Cloudflare. Django only
 * hands out the one-time tus URL (POST create-upload) and reports status
 * afterwards. Copy shared by the English and Arabic upload pages, so all
 * user-facing strings come from data-* attributes on the .dash root.
 */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var root = document.querySelector('[data-vu]');
    if (!root) return;

    var str = function (key, fallback) {
      return root.dataset[key] || fallback;
    };
    var t = {
      uploaded: str('uploaded', 'Uploaded'),
      preparing: str('preparing', 'Preparing your upload…'),
      uploading: str('uploading', 'Uploading'),
      of: str('of', 'of'),
      cancel: str('cancel', 'Cancel'),
      cancelled: str('cancelled', 'Upload cancelled.'),
      processing: str('processing', 'Processing your video…'),
      errType: str('errType', 'That does not look like a video file. Please choose a video.'),
      errSize: str('errSize', 'That file is too large.'),
      errEmpty: str('errEmpty', 'That file looks empty.'),
      errNetwork: str('errNetwork', 'We lost the connection. Please try again.'),
      errQuota: str('errQuota', 'You are out of video storage. Upgrade your storage add-on to upload more.'),
      errGeneric: str('errGeneric', 'Something went wrong on our side. Please try again.')
    };

    var createUrl = root.dataset.createUrl;
    var statusUrlTemplate = root.dataset.statusUrlTemplate || '';
    var cancelUrlTemplate = root.dataset.cancelUrlTemplate || '';
    var csrfToken = root.dataset.csrf || getCookie('csrftoken') || '';
    var maxBytes = parseInt(root.dataset.maxBytes, 10) || 0;
    var allowedTypes = (root.dataset.allowedTypes || '').split(',').filter(Boolean);

    var MAX_POLL_ATTEMPTS = 400;   // ~20 min at a 3s interval
    var POLL_INTERVAL_MS = 3000;

    // --- Elements ----------------------------------------------------------
    var els = {
      dropzone: document.getElementById('vu-dropzone'),
      input: document.getElementById('vu-file-input'),
      error: document.getElementById('vu-error'),
      errorText: document.getElementById('vu-error-text'),
      live: document.getElementById('sr-live'),
      fileName: document.getElementById('vu-file-name'),
      fileMeta: document.getElementById('vu-file-meta'),
      project: document.getElementById('vu-project'),
      start: document.getElementById('vu-start'),
      clear: document.getElementById('vu-clear'),
      change: document.getElementById('vu-change'),
      cancel: document.getElementById('vu-cancel'),
      another: document.getElementById('vu-another'),
      progressLabel: document.getElementById('vu-progress-label'),
      progressPct: document.getElementById('vu-progress-pct'),
      progressBar: document.getElementById('vu-progress-bar'),
      progressFill: document.getElementById('vu-progress-fill'),
      progressDetail: document.getElementById('vu-progress-detail'),
      player: document.getElementById('vu-player')
    };

    // --- State -------------------------------------------------------------
    var upload = null;      // tus.Upload instance
    var selected = null;    // the File the user picked
    var videoId = null;
    var pollTimer = null;
    var pollCount = 0;
    var cancelled = false;

    // --- Helpers -----------------------------------------------------------
    function getCookie(name) {
      var value = null;
      if (document.cookie && document.cookie !== '') {
        var parts = document.cookie.split(';');
        for (var i = 0; i < parts.length; i++) {
          var cookie = parts[i].trim();
          if (cookie.substring(0, name.length + 1) === (name + '=')) {
            value = decodeURIComponent(cookie.substring(name.length + 1));
            break;
          }
        }
      }
      return value;
    }

    /* The server renders these with a placeholder id of 0 (a template cannot
     * reverse a URL for an id it does not have yet), so swap in the real one. */
    function urlForVideo(template, id) {
      return template.replace(/\/0\//, '/' + id + '/');
    }

    function formatBytes(n) {
      if (!n && n !== 0) return '';
      var units = ['B', 'KB', 'MB', 'GB'];
      var i = 0;
      var value = n;
      while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
      return (i === 0 ? value : value.toFixed(1)) + ' ' + units[i];
    }

    function announce(msg) {
      if (els.live) els.live.textContent = msg;
    }

    function setState(name) {
      var panes = root.querySelectorAll('[data-vu-state]');
      for (var i = 0; i < panes.length; i++) {
        panes[i].hidden = panes[i].getAttribute('data-vu-state') !== name;
      }
      root.setAttribute('data-current-state', name);
    }

    /* Inline error surface — never alert(). */
    function showError(message) {
      stopPolling();
      els.errorText.textContent = message;
      els.error.hidden = false;
      announce(message);
      if (els.error.scrollIntoView) {
        els.error.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }

    function clearError() {
      els.errorText.textContent = '';
      els.error.hidden = true;
    }

    function resetToIdle() {
      stopPolling();
      if (upload) { try { upload.abort(false); } catch (e) { /* not started */ } }
      upload = null;
      selected = null;
      videoId = null;
      cancelled = false;
      pollCount = 0;
      els.input.value = '';
      if (els.progressFill) els.progressFill.style.width = '0%';
      if (els.progressBar) els.progressBar.setAttribute('aria-valuenow', '0');
      clearError();
      setState('idle');
    }

    // --- Client-side validation -------------------------------------------
    /* Some browsers report an empty type for .mkv/.mov, so fall back to the
     * file extension before rejecting. */
    function looksLikeVideo(file) {
      if (file.type && file.type.indexOf('video/') === 0) return true;
      return /\.(mp4|m4v|mov|qt|webm|mkv|avi|wmv|flv|mpg|mpeg|3gp|ogv|ogg|mts|m2ts)$/i
        .test(file.name || '');
    }

    function validate(file) {
      if (!file) return t.errGeneric;
      if (file.size === 0) return t.errEmpty;
      if (!looksLikeVideo(file)) return t.errType;
      if (maxBytes && file.size > maxBytes) return t.errSize;
      return null;
    }

    function selectFile(file) {
      var problem = validate(file);
      if (problem) {
        showError(problem);
        els.input.value = '';
        return;
      }
      clearError();
      selected = file;
      els.fileName.textContent = file.name;
      els.fileMeta.textContent = formatBytes(file.size);
      setState('selected');
    }

    // --- Drag & drop -------------------------------------------------------
    if (els.dropzone) {
      ['dragenter', 'dragover'].forEach(function (type) {
        els.dropzone.addEventListener(type, function (e) {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
          els.dropzone.classList.add('is-dragover');
        });
      });
      ['dragleave', 'dragend'].forEach(function (type) {
        els.dropzone.addEventListener(type, function () {
          els.dropzone.classList.remove('is-dragover');
        });
      });
      els.dropzone.addEventListener('drop', function (e) {
        e.preventDefault();
        els.dropzone.classList.remove('is-dragover');
        var files = e.dataTransfer && e.dataTransfer.files;
        if (files && files.length) selectFile(files[0]);
      });
    }

    if (els.input) {
      els.input.addEventListener('change', function () {
        if (els.input.files && els.input.files.length) selectFile(els.input.files[0]);
      });
    }

    if (els.clear) els.clear.addEventListener('click', resetToIdle);
    if (els.change) els.change.addEventListener('click', function () { els.input.click(); });
    if (els.another) els.another.addEventListener('click', resetToIdle);
    if (els.start) els.start.addEventListener('click', startUpload);

    // --- Upload ------------------------------------------------------------
    function updateProgress(pct) {
      var value = Math.max(0, Math.min(100, pct));
      if (els.progressFill) els.progressFill.style.width = value.toFixed(1) + '%';
      if (els.progressBar) els.progressBar.setAttribute('aria-valuenow', Math.round(value));
      if (els.progressPct) els.progressPct.textContent = Math.round(value) + '%';
    }

    function startUpload() {
      if (!selected) { showError(t.errType); return; }
      if (typeof window.tus === 'undefined') {
        showError(t.errGeneric);
        return;
      }

      clearError();
      cancelled = false;
      updateProgress(0);
      if (els.progressLabel) els.progressLabel.textContent = t.preparing;
      if (els.progressDetail) els.progressDetail.textContent = '';
      if (els.dropzone) els.dropzone.classList.add('is-busy');
      setState('uploading');

      var projectId = els.project && els.project.value ? els.project.value : null;

      fetch(createUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          filename: selected.name,
          filesize: selected.size,
          project_id: projectId
        })
      })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            return { ok: r.ok, status: r.status, body: body };
          });
        })
        .then(function (res) {
          if (res.status === 402 || (res.body && res.body.code === 'quota_exceeded')) {
            throw new Error(res.body.error || t.errQuota);
          }
          if (!res.ok || !res.body.uploadURL) {
            throw new Error((res.body && res.body.error) || t.errGeneric);
          }
          videoId = res.body.videoId;
          beginTusUpload(res.body.uploadURL);
        })
        .catch(function (err) {
          if (cancelled) return;
          showError(err && err.message ? err.message : t.errGeneric);
          setState('idle');
        });
    }

    function beginTusUpload(uploadUrl) {
      if (els.progressLabel) els.progressLabel.textContent = t.uploading;

      upload = new window.tus.Upload(selected, {
        // The server already created this one-time URL — do NOT pass `endpoint`.
        uploadUrl: uploadUrl,
        chunkSize: 50 * 1024 * 1024,        // 50 MB chunks (tus minimum is 5 MB)
        retryDelays: [0, 3000, 5000, 10000, 20000],
        removeFingerprintOnSuccess: true,
        storeFingerprintForResuming: true,
        onError: function (err) {
          if (cancelled) return;
          var message = t.errNetwork;
          if (err && err.originalRequest) {
            var code = err.originalRequest.getStatus();
            if (code === 401 || code === 403) message = t.errGeneric;
            else if (code === 413) message = t.errSize;
          }
          showError(message);
          setState('idle');
        },
        onProgress: function (bytesUploaded, bytesTotal) {
          var pct = bytesTotal ? (bytesUploaded / bytesTotal) * 100 : 0;
          updateProgress(pct);
          if (els.progressDetail) {
            els.progressDetail.textContent =
              formatBytes(bytesUploaded) + ' ' + t.of + ' ' + formatBytes(bytesTotal);
          }
          if (els.progressLabel) els.progressLabel.textContent = t.uploaded;
        },
        onSuccess: function () {
          if (cancelled) return;
          updateProgress(100);
          if (els.progressDetail) els.progressDetail.textContent = '';
          showProcessing();
          beginPolling();
        }
      });

      upload.start();
    }

    // --- Status polling (fallback for a delayed webhook) --------------------
    function showProcessing() {
      var hint = document.getElementById('vu-processing-hint');
      if (hint) hint.textContent = t.processing;
      setState('processing');
      announce(t.processing);
    }

    function stopPolling() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function beginPolling() {
      stopPolling();
      pollCount = 0;
      pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
      pollStatus();
    }

    function pollStatus() {
      if (cancelled || videoId === null) return;
      pollCount += 1;

      if (pollCount > MAX_POLL_ATTEMPTS) {
        showError(t.errGeneric);
        return;
      }

      fetch(urlForVideo(statusUrlTemplate, videoId), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      })
        .then(function (r) { return r.json(); })
        .then(function (v) {
          if (cancelled) return;
          if (v.status === 'ready') {
            stopPolling();
            showReady(v);
          } else if (v.status === 'error') {
            stopPolling();
            showError(v.error_message || t.errGeneric);
            setState('idle');
          }
          // 'pending' / 'processing' -> keep waiting
        })
        .catch(function () {
          // Transient network blips are expected; the next tick retries.
          if (pollCount > MAX_POLL_ATTEMPTS) showError(t.errNetwork);
        });
    }

    function showReady(v) {
      if (els.player) {
        els.player.innerHTML = '';
        if (v.thumbnail) {
          var poster = document.createElement('img');
          poster.src = v.thumbnail;
          poster.alt = '';
          poster.style.cssText =
            'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;';
          els.player.style.cssText = 'position:relative;';
          els.player.appendChild(poster);
        }
        if (v.embed) {
          var frame = document.createElement('iframe');
          frame.src = v.embed;
          frame.title = v.title || 'Video player';
          frame.loading = 'lazy';
          frame.setAttribute('allow',
            'accelerometer; gyroscope; autoplay; encrypted-media; picture-in-picture');
          frame.setAttribute('allowfullscreen', '');
          frame.style.cssText = 'position:relative;z-index:1;border:none;border-radius:16px;';
          els.player.appendChild(frame);
        }
        if (v.embed) {
          // Aspect-ratio box so the player keeps a sane height before it loads.
          els.player.style.aspectRatio = '16 / 9';
          els.player.style.background = '#0f172a';
          els.player.style.borderRadius = '16px';
          els.player.style.overflow = 'hidden';
        } else {
          els.player.style.cssText = 'display:none;';
        }
      }
      var okMessage = root.querySelector('[data-vu-state="ready"] .vu-alert span');
      if (okMessage) {
        okMessage.textContent = str('readyTitle', 'Your video is ready') + ' — ' +
          str('readyHint', 'It is ready to publish.');
      }
      setState('ready');
      announce(str('readyTitle', 'Your video is ready'));
    }

    // --- Cancel ------------------------------------------------------------
    /* Aborting the tus transfer only stops the bytes moving. The server-side row
     * still holds a reservation against the user's storage allowance, so it has
     * to be released explicitly or the space is lost until the reaper runs. */
    function releaseServerReservation(id) {
      if (id === null || !cancelUrlTemplate) return;
      var url = urlForVideo(cancelUrlTemplate, id);
      fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        credentials: 'same-origin',
        keepalive: true
      }).catch(function () {
        // Best effort: the abandoned-upload reaper will catch it regardless.
      });
    }

    if (els.cancel) {
      els.cancel.addEventListener('click', function () {
        cancelled = true;
        stopPolling();
        if (upload) { try { upload.abort(true); } catch (e) { /* not started */ } }
        upload = null;
        releaseServerReservation(videoId);
        videoId = null;
        showError(t.cancelled);
        setState('idle');
        els.input.value = '';
      });
    }

    // Closing the tab mid-upload must not leak the reservation either.
    window.addEventListener('pagehide', function () {
      if (!cancelled && videoId !== null) releaseServerReservation(videoId);
    });

    // --- Icons -------------------------------------------------------------
    if (window.lucide) {
      try { window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } }); }
      catch (e) { window.lucide.createIcons(); }
    }
  });
})();
