/**
 * Skillifly AI — Client-side Controller
 * Manages chat interactions, clarification pills, action previews, undo, and live builder form sync.
 */

(function () {
  'use strict';

  const root = document.getElementById('agent-copilot-root');
  if (!root) return;

  const lang = root.dataset.lang || 'en';
  const csrfToken = root.dataset.csrf || getCookie('csrftoken');

  const triggerBtn = document.getElementById('agent-copilot-trigger');
  const drawer = document.getElementById('agent-copilot-drawer');
  const backdrop = document.getElementById('agent-drawer-backdrop');
  const closeBtn = document.getElementById('agent-btn-close');
  const resetBtn = document.getElementById('agent-btn-reset');
  const messagesContainer = document.getElementById('agent-messages-container');
  const welcomeCard = document.getElementById('agent-welcome-card');
  const quickRepliesContainer = document.getElementById('agent-quick-replies');
  const typingIndicator = document.getElementById('agent-typing-indicator');
  const chatForm = document.getElementById('agent-chat-form');
  const chatInput = document.getElementById('agent-chat-input');
  const sendBtn = document.getElementById('agent-send-btn');
  const soundBtn = document.getElementById('agent-btn-sound');
  const soundIconOn = document.getElementById('agent-sound-icon-on');
  const soundIconOff = document.getElementById('agent-sound-icon-off');
  const micBtn = document.getElementById('agent-mic-btn');
  const listeningBar = document.getElementById('agent-listening-bar');
  const micStatus = document.getElementById('agent-mic-status');
  const micStatusText = document.getElementById('agent-mic-status-text');
  const confirmOverlay = document.getElementById('agent-confirm-overlay');
  const confirmOkBtn = document.getElementById('agent-confirm-ok');
  const confirmCancelBtn = document.getElementById('agent-confirm-cancel');
  const confirmModal = confirmOverlay ? confirmOverlay.querySelector('.agent-confirm-modal') : null;

  let isLoaded = false;
  let isSending = false;
  let soundEnabled = localStorage.getItem('skillifly_agent_sound') !== '0';
  let audioCtx = null;
  let recognition = null;
  let isListening = false;

  // -------------------------------------------------------------------------
  // Sound & Speech Synthesis Engine
  // -------------------------------------------------------------------------
  function initAudio() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        audioCtx = new AudioContext();
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
  }

  function playTone(freq, type, duration, gainValue = 0.12) {
    if (!soundEnabled) return;
    try {
      initAudio();
      if (!audioCtx) return;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type || 'sine';
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      gain.gain.setValueAtTime(gainValue, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch (e) {}
  }

  function playSendSound() {
    if (!soundEnabled) return;
    try {
      initAudio();
      if (!audioCtx) return;
      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.exponentialRampToValueAtTime(680, now + 0.12);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.12);
    } catch (e) {}
  }

  function playReceiveSound() {
    if (!soundEnabled) return;
    try {
      initAudio();
      if (!audioCtx) return;
      const now = audioCtx.currentTime;
      [587, 880].forEach((freq, i) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, now + i * 0.08);
        gain.gain.setValueAtTime(0.1, now + i * 0.08);
        gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.08 + 0.12);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now + i * 0.08);
        osc.stop(now + i * 0.08 + 0.12);
      });
    } catch (e) {}
  }

  function playSuccessSound() {
    if (!soundEnabled) return;
    try {
      initAudio();
      if (!audioCtx) return;
      const now = audioCtx.currentTime;
      [523.25, 659.25, 783.99].forEach((freq) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, now);
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.25);
      });
    } catch (e) {}
  }

  function updateSoundUI() {
    if (!soundBtn) return;
    if (soundEnabled) {
      soundBtn.classList.add('is-active');
      soundBtn.classList.remove('is-muted');
      if (soundIconOn) soundIconOn.style.display = 'block';
      if (soundIconOff) soundIconOff.style.display = 'none';
      soundBtn.title = (lang === 'ar') ? 'الصوت مفعّل (اضغط للكتم)' : 'Sound On (Click to mute)';
    } else {
      soundBtn.classList.remove('is-active');
      soundBtn.classList.add('is-muted');
      if (soundIconOn) soundIconOn.style.display = 'none';
      if (soundIconOff) soundIconOff.style.display = 'block';
      soundBtn.title = (lang === 'ar') ? 'الصوت مكتوم (اضغط للتفعيل)' : 'Sound Muted (Click to unmute)';
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    }
  }

  if (soundBtn) {
    soundBtn.addEventListener('click', function () {
      initAudio();
      soundEnabled = !soundEnabled;
      localStorage.setItem('skillifly_agent_sound', soundEnabled ? '1' : '0');
      updateSoundUI();
      if (soundEnabled) {
        playTone(520, 'sine', 0.15);
      }
    });
    updateSoundUI();
  }

  // Voice Reading (TTS)
  function speakText(text) {
    if (!soundEnabled || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      let clean = text
        .replace(/\*\*|__|[*_`#]/g, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/\(\*.*?\*\)/g, '')
        .replace(/[\n\r]+/g, ' ')
        .trim();

      if (!clean) return;

      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.lang = (lang === 'ar') ? 'ar-SA' : 'en-US';
      utterance.rate = (lang === 'ar') ? 0.95 : 1.05;

      const voices = window.speechSynthesis.getVoices();
      if (voices && voices.length > 0) {
        if (lang === 'ar') {
          const arVoice = voices.find(v => v.lang.startsWith('ar'));
          if (arVoice) utterance.voice = arVoice;
        } else {
          const enVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha')));
          if (enVoice) utterance.voice = enVoice;
        }
      }

      window.speechSynthesis.speak(utterance);
    } catch (e) {
      console.warn('SpeechSynthesis error:', e);
    }
  }

  // Voice Input (Speech-to-Text via Mic)
  let micStatusTimer = null;

  function showMicStatus(text, type) {
    if (!micStatus || !micStatusText) return;
    micStatusText.textContent = text;
    micStatus.className = 'agent-mic-status' + (type ? ' is-' + type : '');
    micStatus.style.display = 'flex';
    if (micStatusTimer) clearTimeout(micStatusTimer);
    micStatusTimer = setTimeout(hideMicStatus, 5000);
  }

  function hideMicStatus() {
    if (micStatusTimer) {
      clearTimeout(micStatusTimer);
      micStatusTimer = null;
    }
    if (micStatus) micStatus.style.display = 'none';
  }

  function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    // Check for secure context: the Web Speech API requires HTTPS or localhost.
    const isSecure = window.isSecureContext;
    const isLocalhost = /^(localhost|127\.0\.0\.1|::1)(:\d+)?$/.test(window.location.hostname);

    if (!SpeechRecognition) {
      if (micBtn) {
        micBtn.title = (lang === 'ar') ? 'المتصفح لا يدعم الإدخال الصوتي' : 'Voice input not supported in this browser';
        micBtn.classList.add('is-disabled');
      }
      showMicStatus(
        (lang === 'ar')
          ? 'المتصفح الحالي لا يدعم الإدخال الصوتي. يرجى استخدام Chrome أو Edge.'
          : 'Current browser does not support voice input. Please use Chrome or Edge.',
        ''
      );
      return;
    }

    if (!isSecure && !isLocalhost) {
      if (micBtn) {
        micBtn.title = (lang === 'ar') ? 'يحتاج اتصال آمن (HTTPS) لتشغيل المايك' : 'A secure (HTTPS) connection is required for the mic';
        micBtn.classList.add('is-disabled');
      }
      showMicStatus(
        (lang === 'ar')
          ? 'تحتاج حماية HTTPS فتح الموقع عبر رابط آمن لتشغيل الميكروفون.'
          : 'Voice input needs a secure HTTPS connection. Please open the site over HTTPS.',
        ''
      );
      return;
    }

    if (micBtn) {
      micBtn.classList.remove('is-disabled');
      micBtn.title = (lang === 'ar') ? 'اضغط للتحدث بالصوت' : 'Click to speak';
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.lang = (lang === 'ar') ? 'ar-EG' : 'en-US';

    recognition.onstart = function () {
      isListening = true;
      initAudio();
      if (micBtn) micBtn.classList.add('is-recording');
      if (listeningBar) listeningBar.style.display = 'flex';
      hideMicStatus();
      playTone(550, 'sine', 0.1);
    };

    recognition.onresult = function (event) {
      let currentTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        currentTranscript += event.results[i][0].transcript;
      }
      if (currentTranscript) {
        chatInput.value = currentTranscript;
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
      }
      if (event.results[event.results.length - 1] && event.results[event.results.length - 1].isFinal) {
        showMicStatus(
          (lang === 'ar') ? 'تم التقاط صوتك، جاري الإرسال...' : 'Heard you — sending...',
          'is-info'
        );
      }
    };

    recognition.onerror = function (event) {
      console.warn('Speech recognition error:', event.error);
      stopListening();

      const ar = lang === 'ar';
      let msg = ar ? 'حدث خطأ في التعرف على الصوت، حاول مرة أخرى.' : 'Speech recognition error. Please try again.';
      let type = '';
      switch (event.error) {
        case 'not-allowed':
        case 'service-not-allowed':
          msg = ar
            ? 'لم يسمح بالوصول إلى الميكروفون. اضغط على أيقونة الميكروفون في شريط عنوان المتصفح وفعّل الوصول.'
            : 'Microphone access was denied. Tap the mic icon in your browser address bar and allow access.';
          break;
        case 'no-speech':
          msg = ar ? 'لم أسمع صوتاً، حاول مرة أخرى.' : 'No speech detected. Try again.';
          break;
        case 'audio-capture':
          msg = ar ? 'لم يتم العثور على ميكروفون متصل بجهازك.' : 'No microphone was found on this device.';
          break;
        case 'network':
          msg = ar
            ? 'الاتصال الصوتي يحتاج إنترنت، تحقق من اتصالك وجرب مجدداً.'
            : 'Voice recognition requires internet. Check your connection and try again.';
          break;
      }
      showMicStatus(msg, type);
    };

    recognition.onend = function () {
      stopListening();
      if (chatInput.value.trim().length > 0) {
        setTimeout(() => {
          if (!isSending && chatInput.value.trim().length > 0) {
            sendMessage();
          }
        }, 300);
      }
    };
  }

  function startListening() {
    // Request mic permission explicitly so the browser prompts on first use.
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      if (!localStorage.getItem('skillifly_mic_allowed')) {
        try {
          navigator.mediaDevices.getUserMedia({ audio: true }).then(function () {
            localStorage.setItem('skillifly_mic_allowed', '1');
            beginRecognition();
          }).catch(function () {
            localStorage.setItem('skillifly_mic_allowed', '0');
            if (micBtn) micBtn.classList.add('is-disabled');
            showMicStatus(
              (lang === 'ar')
                ? 'لم يسمح بالوصول إلى الميكروفون. فعّل الوصول من إعدادات المتصفح.'
                : 'Microphone access was denied. Please allow it in your browser settings.',
              ''
            );
          });
          return;
        } catch (e) {
          // getUserMedia not available → fall through to recognition directly
        }
      }
    }
    beginRecognition();
  }

  function beginRecognition() {
    if (!recognition) setupSpeechRecognition();
    if (!recognition) return;
    try {
      recognition.start();
    } catch (e) {
      // If already started, stop then restart on next interaction.
      try { recognition.stop(); } catch (e2) {}
      isListening = false;
      if (micBtn) micBtn.classList.remove('is-recording');
      if (listeningBar) listeningBar.style.display = 'none';
    }
  }

  function stopListening() {
    isListening = false;
    if (micBtn) micBtn.classList.remove('is-recording');
    if (listeningBar) listeningBar.style.display = 'none';
  }

  if (micBtn) {
    micBtn.addEventListener('click', function () {
      if (micBtn.classList.contains('is-disabled')) {
        // Tap on the capsule to retry after permissions/HTTPS are corrected
        showMicStatus(
          (lang === 'ar')
            ? 'تعذر الوصول إلى الميكروفون. تحقق من HTTPS والأذونات وحاول مرة أخرى.'
            : 'Mic unavailable. Check HTTPS & permissions, then try again.',
          ''
        );
        return;
      }
      if (isListening) {
        if (recognition) recognition.stop();
      } else {
        startListening();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function parseMarkdown(text) {
    if (!text) return '';
    let parsed = escapeHtml(text);
    // Bold **text**
    parsed = parsed.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic *text*
    parsed = parsed.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Code `code`
    parsed = parsed.replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.1);padding:2px 4px;border-radius:4px;">$1</code>');
    // Markdown links [text](url)
    parsed = parsed.replace(/\[(.*?)\]\((https?:\/\/.*?)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#a5b4fc;text-decoration:underline;">$1</a>');
    // Line breaks
    parsed = parsed.replace(/\n/g, '<br>');
    return parsed;
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // -------------------------------------------------------------------------
  // Drawer Toggles
  // -------------------------------------------------------------------------
  function openDrawer() {
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    chatInput.focus();
    playTone(520, 'sine', 0.08, 0.06);
    if (!isLoaded) {
      loadHistory();
    }
  }

  function closeDrawer() {
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    stopListening();
  }

  triggerBtn.addEventListener('click', openDrawer);
  closeBtn.addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && drawer.classList.contains('is-open')) {
      closeDrawer();
    }
  });

  // -------------------------------------------------------------------------
  // Load History
  // -------------------------------------------------------------------------
  async function loadHistory() {
    try {
      const res = await fetch('/agent/history/', {
        headers: { 'Accept': 'application/json' },
      });
      if (!res.ok) return;
      const data = await res.json();
      isLoaded = true;

      if (data.messages && data.messages.length > 0) {
        if (welcomeCard) welcomeCard.style.display = 'none';
        data.messages.forEach(msg => {
          appendMessageBubble(msg.sender, msg.text, msg.actions, msg.created_at);
          if (msg.quick_replies && msg.quick_replies.length > 0) {
            renderQuickReplies(msg.quick_replies);
          }
        });
        scrollToBottom();
      }
    } catch (err) {
      console.warn('Could not load agent history:', err);
    }
  }

  // -------------------------------------------------------------------------
  // Custom Confirmation Modal
  // -------------------------------------------------------------------------
  if (confirmOverlay) {
    confirmOkBtn.addEventListener('click', function () {
      closeConfirmModal(true);
    });
    confirmCancelBtn.addEventListener('click', function () {
      closeConfirmModal(false);
    });
    confirmOverlay.addEventListener('click', function (e) {
      if (e.target === confirmOverlay) closeConfirmModal(false);
    });
    document.addEventListener('keydown', function (e) {
      if (confirmOverlay.classList.contains('is-open') && e.key === 'Escape') {
        closeConfirmModal(false);
      }
    });
  }

  let confirmResolve = null;

  function openConfirmModal() {
    confirmOverlay.classList.add('is-open');
    confirmOverlay.setAttribute('aria-hidden', 'false');
    if (confirmOkBtn) confirmOkBtn.focus();
    document.body.style.overflow = 'hidden';
    return new Promise((resolve) => {
      confirmResolve = resolve;
    });
  }

  function closeConfirmModal(value) {
    confirmOverlay.classList.remove('is-open');
    confirmOverlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (confirmResolve) {
      const resolve = confirmResolve;
      confirmResolve = null;
      resolve(value);
    }
  }

  // -------------------------------------------------------------------------
  // Reset Conversation
  // -------------------------------------------------------------------------
  resetBtn.addEventListener('click', async function () {
    const confirmed = await openConfirmModal();
    if (!confirmed) return;

    try {
      const res = await fetch('/agent/clear/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
      });
      if (res.ok) {
        const msgs = messagesContainer.querySelectorAll('.agent-msg');
        msgs.forEach(m => m.remove());
        if (welcomeCard) {
          welcomeCard.style.display = 'block';
        }
        quickRepliesContainer.style.display = 'none';
        quickRepliesContainer.innerHTML = '';
      }
    } catch (err) {
      console.error('Error clearing agent chat:', err);
    }
  });

  // -------------------------------------------------------------------------
  // Render Messages & Action Cards
  // -------------------------------------------------------------------------
  function appendMessageBubble(sender, text, actions = [], time = '') {
    const isUser = sender === 'user';
    const msgDiv = document.createElement('div');
    msgDiv.className = `agent-msg ${isUser ? 'is-user' : 'is-agent'}`;

    const bubble = document.createElement('div');
    bubble.className = 'agent-msg-bubble';
    bubble.innerHTML = parseMarkdown(text);

    // Append Action Cards if present
    if (actions && actions.length > 0) {
      actions.forEach(act => {
        const actionCard = renderActionCard(act);
        if (actionCard) bubble.appendChild(actionCard);
      });
    }

    msgDiv.appendChild(bubble);

    if (time) {
      const timeSpan = document.createElement('span');
      timeSpan.className = 'agent-msg-time';
      timeSpan.textContent = time;
      msgDiv.appendChild(timeSpan);
    }

    messagesContainer.appendChild(msgDiv);
    scrollToBottom();
  }

  function renderActionCard(action) {
    if (!action || !action.action_type) return null;

    const card = document.createElement('div');
    card.className = 'agent-action-card';

    const header = document.createElement('div');
    header.className = 'agent-action-header';

    const badge = document.createElement('span');
    badge.className = 'agent-action-badge';
    badge.innerHTML = `
      <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
      </svg>
      ${escapeHtml(action.action_type.replace(/_/g, ' '))}
    `;
    header.appendChild(badge);

    // Undo Button if snapshot_id exists
    if (action.snapshot_id) {
      const undoBtn = document.createElement('button');
      undoBtn.type = 'button';
      undoBtn.className = 'agent-undo-btn';
      undoBtn.textContent = lang === 'ar' ? 'تراجع (Undo)' : 'Undo';
      undoBtn.addEventListener('click', () => handleUndo(action.snapshot_id, card, undoBtn));
      header.appendChild(undoBtn);
    }

    card.appendChild(header);

    const details = document.createElement('div');
    details.className = 'agent-action-details';
    details.textContent = action.message || 'Changes applied successfully.';
    card.appendChild(details);

    return card;
  }

  // -------------------------------------------------------------------------
  // Handle Undo
  // -------------------------------------------------------------------------
  async function handleUndo(snapshotId, cardEl, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = lang === 'ar' ? 'جاري التراجع...' : 'Undoing...';

    try {
      const res = await fetch(`/agent/undo/${snapshotId}/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
      });
      const data = await res.json();
      if (data.success) {
        btnEl.textContent = lang === 'ar' ? 'تم التراجع ✓' : 'Undone ✓';
        btnEl.style.background = 'rgba(16, 185, 129, 0.2)';
        btnEl.style.color = '#10b981';

        // Re-sync builder if state is returned
        if (data.portfolio_state) {
          syncBuilderDOM(data.portfolio_state);
        }
      } else {
        btnEl.textContent = 'Error';
        alert(data.error || 'Could not undo changes.');
      }
    } catch (err) {
      console.error('Error executing undo:', err);
      btnEl.disabled = false;
      btnEl.textContent = 'Undo';
    }
  }

  // -------------------------------------------------------------------------
  // Quick Replies
  // -------------------------------------------------------------------------
  function renderQuickReplies(replies) {
    quickRepliesContainer.innerHTML = '';
    if (!replies || replies.length === 0) {
      quickRepliesContainer.style.display = 'none';
      return;
    }

    replies.forEach(reply => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'agent-quick-chip';
      chip.textContent = reply;
      chip.addEventListener('click', () => {
        chatInput.value = reply;
        sendMessage();
      });
      quickRepliesContainer.appendChild(chip);
    });

    quickRepliesContainer.style.display = 'flex';
    scrollToBottom();
  }

  // Button & Pill clicks inside messages container (Starter cards, quick replies, suggestions)
  messagesContainer.addEventListener('click', function (e) {
    const btn = e.target.closest('.agent-pill-btn, .agent-quick-chip, [data-prompt]');
    if (btn) {
      const prompt = btn.getAttribute('data-prompt') || btn.textContent.trim();
      if (prompt) {
        chatInput.value = prompt;
        sendMessage();
      }
    }
  });

  // -------------------------------------------------------------------------
  // Send Message
  // -------------------------------------------------------------------------
  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isSending) return;

    isSending = true;
    sendBtn.disabled = true;
    chatInput.value = '';
    chatInput.style.height = 'auto';

    if (welcomeCard) welcomeCard.style.display = 'none';
    quickRepliesContainer.style.display = 'none';

    // Show User Message Bubble immediately
    appendMessageBubble('user', text);
    playSendSound();

    // Show Typing Indicator
    typingIndicator.style.display = 'flex';
    scrollToBottom();

    try {
      const res = await fetch('/agent/chat/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          language: lang,
        }),
      });

      const json = await res.json();
      typingIndicator.style.display = 'none';

      if (json.success && json.data) {
        const data = json.data;
        appendMessageBubble('agent', data.message, data.actions);

        // Sound Feedback & Voice Reading
        if (data.actions && data.actions.length > 0) {
          playSuccessSound();
        } else {
          playReceiveSound();
        }
        speakText(data.message);

        if (data.quick_replies && data.quick_replies.length > 0) {
          renderQuickReplies(data.quick_replies);
        }

        // Live DOM sync for builder forms
        if (data.actions && data.actions.length > 0) {
          data.actions.forEach(action => {
            syncBuilderFromAction(action);
          });
        }
      } else {
        appendMessageBubble('agent', json.error || 'An unexpected error occurred.');
        playReceiveSound();
      }
    } catch (err) {
      typingIndicator.style.display = 'none';
      appendMessageBubble('agent', 'Network connection error. Please try again.');
      playReceiveSound();
      console.error('Chat error:', err);
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }

  chatForm.addEventListener('submit', function (e) {
    e.preventDefault();
    sendMessage();
  });

  chatInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  chatInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  // -------------------------------------------------------------------------
  // Live Builder DOM Sync
  // -------------------------------------------------------------------------
  function syncBuilderFromAction(action) {
    if (!action) return;

    // Dispatch global event for custom theme or portfolio listeners
    window.dispatchEvent(new CustomEvent('skillifly:agent-applied', { detail: action }));

    // 1. Personal Info Sync
    if (action.action_type === 'update_personal_info' && action.diff) {
      const diff = action.diff;
      const fieldMap = {
        'full_name': ['fullname', 'full_name'],
        'title': ['title'],
        'bio': ['bio'],
        'booking_url': ['booking_url'],
        'phone': ['phone'],
        'email': ['email'],
      };

      for (const [key, valObj] of Object.entries(diff)) {
        const names = fieldMap[key] || [key];
        names.forEach(name => {
          const input = document.querySelector(`[name="${name}"]`);
          if (input) {
            input.value = valObj.new;
            input.classList.add('agent-field-updated');
            setTimeout(() => input.classList.remove('agent-field-updated'), 3000);
          }
        });
      }
    }

    // 2. Theme Sync
    if (action.action_type === 'change_theme') {
      const reloadBanner = document.createElement('div');
      reloadBanner.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;background:#10b981;color:#fff;padding:12px 18px;border-radius:10px;font-weight:600;box-shadow:0 10px 25px rgba(0,0,0,0.4);cursor:pointer;';
      reloadBanner.textContent = lang === 'ar'
        ? 'تم تغيير الثيم بنجاح! انقر هنا لتحديث المعاينة'
        : 'Theme changed successfully! Click to reload preview';
      reloadBanner.addEventListener('click', () => window.location.reload());
      document.body.appendChild(reloadBanner);
      setTimeout(() => reloadBanner.remove(), 8000);
    }
  }

  function syncBuilderDOM(state) {
    if (!state || !state.personal_info) return;
    const pi = state.personal_info;
    const inputs = {
      'fullname': pi.full_name,
      'title': pi.title,
      'bio': pi.bio,
      'booking_url': pi.booking_url,
      'phone': pi.phone,
      'email': pi.email,
    };
    for (const [name, val] of Object.entries(inputs)) {
      const el = document.querySelector(`[name="${name}"]`);
      if (el) el.value = val || '';
    }
  }

})();
