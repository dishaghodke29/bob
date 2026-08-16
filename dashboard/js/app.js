/**
 * BOB Dashboard — app.js
 * Main application logic:
 *  • WebSocket connection to BOB brain
 *  • Joystick → move commands
 *  • Rotation slider → omega
 *  • Chat form → LLM chat
 *  • Emotion buttons
 *  • Telemetry display (IMU, ToF, state)
 *  • Camera feed watchdog
 */

(function () {
  'use strict';

  // ── Config ────────────────────────────────────────────────────────────────
  const WS_URL    = `ws://${location.host}/ws`;
  const RECONNECT = 2500;   // ms between reconnect attempts
  const SEND_HZ   = 20;     // drive command rate

  // ── State ─────────────────────────────────────────────────────────────────
  let ws        = null;
  let connected = false;
  let vy = 0, vx = 0, omega = 0;
  let autoMode  = false;
  let sendInterval = null;

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const $dot        = document.getElementById('status-dot');
  const $statusTxt  = document.getElementById('status-text');
  const $stateBadge = document.getElementById('state-badge');
  const $modeTag    = document.getElementById('mode-tag');
  const $rotSlider  = document.getElementById('rotate-slider');
  const $rotVal     = document.getElementById('rotate-val');
  const $chatMsgs   = document.getElementById('chat-messages');
  const $chatInput  = document.getElementById('chat-input');
  const $sendBtn    = document.getElementById('btn-send');
  const $chatForm   = document.getElementById('chat-form');
  const $obstVal    = document.getElementById('obstacle-val');
  const $estopVal   = document.getElementById('estop-val');
  const $imuOkVal   = document.getElementById('imu-ok-val');
  const $llmVal     = document.getElementById('llm-val');
  const $axVal      = document.getElementById('ax-val');
  const $ayVal      = document.getElementById('ay-val');
  const $azVal      = document.getElementById('az-val');
  const $tofDist    = document.getElementById('tof-dist');
  const $camFeed    = document.getElementById('camera-feed');
  const $camOverlay = document.getElementById('camera-overlay');

  // ── WebSocket ─────────────────────────────────────────────────────────────

  function connect() {
    try { ws = new WebSocket(WS_URL); } catch { scheduleReconnect(); return; }

    ws.onopen = () => {
      connected = true;
      setStatus('connected', 'Connected');
      startSendLoop();
    };

    ws.onclose = () => {
      connected = false;
      setStatus('error', 'Disconnected');
      stopSendLoop();
      scheduleReconnect();
    };

    ws.onerror = () => {
      setStatus('error', 'Error');
    };

    ws.onmessage = (ev) => {
      try { handleMsg(JSON.parse(ev.data)); }
      catch { /* ignore */ }
    };
  }

  function scheduleReconnect() {
    setTimeout(connect, RECONNECT);
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // ── Message handlers ──────────────────────────────────────────────────────

  function handleMsg(msg) {
    if (msg.type === 'telemetry') {
      const d = msg.data || {};
      updateGauges({ roll: d.roll, pitch: d.pitch });
      if ($axVal)   $axVal.textContent   = (d.ax ?? 0).toFixed(2);
      if ($ayVal)   $ayVal.textContent   = (d.ay ?? 0).toFixed(2);
      if ($azVal)   $azVal.textContent   = (d.az ?? 1).toFixed(2);
      if ($estopVal) {
        $estopVal.textContent  = d.estop ? 'ACTIVE' : 'OFF';
        $estopVal.className    = 'stat-val ' + (d.estop ? 'error' : 'ok');
      }
      if ($imuOkVal) {
        $imuOkVal.textContent = d.ok ? 'OK' : 'ERR';
        $imuOkVal.className   = 'stat-val ' + (d.ok ? 'ok' : 'error');
      }
    }

    if (msg.type === 'tof') {
      if (window.drawToF) drawToF(msg.grid);
      if ($tofDist && msg.min_cm !== undefined) {
        $tofDist.textContent = `${msg.min_cm} cm`;
      }
      if ($obstVal && msg.min_cm !== undefined) {
        $obstVal.textContent = `${msg.min_cm} cm`;
        $obstVal.className   = 'stat-val ' + (msg.min_cm < 30 ? 'warn' : 'ok');
      }
    }

    if (msg.type === 'state') {
      if ($stateBadge) $stateBadge.textContent = (msg.name || 'IDLE').toUpperCase();
      if ($llmVal) {
        $llmVal.textContent = msg.llm_ready ? 'READY' : 'LOADING';
        $llmVal.className   = 'stat-val ' + (msg.llm_ready ? 'ok' : 'warn');
      }
    }

    if (msg.type === 'chat_response') {
      appendMsg('bob', msg.text || '…');
      $sendBtn.disabled = false;
    }
  }

  // ── Drive loop ────────────────────────────────────────────────────────────

  function startSendLoop() {
    stopSendLoop();
    sendInterval = setInterval(() => {
      if (!autoMode) {
        send({ action: 'move', vy, vx, omega });
      }
    }, 1000 / SEND_HZ);
  }

  function stopSendLoop() {
    if (sendInterval) { clearInterval(sendInterval); sendInterval = null; }
  }

  // ── Joystick ──────────────────────────────────────────────────────────────

  document.addEventListener('joystick-move', (e) => {
    vy = e.detail.vy;
    vx = e.detail.vx;
  });

  // ── Rotation slider ───────────────────────────────────────────────────────

  if ($rotSlider) {
    $rotSlider.addEventListener('input', () => {
      omega = parseInt($rotSlider.value, 10);
      if ($rotVal) $rotVal.textContent = omega;
    });
    // Snap back to 0 on release
    $rotSlider.addEventListener('change', () => {
      $rotSlider.value = '0';
      omega = 0;
      if ($rotVal) $rotVal.textContent = '0';
    });
  }

  // ── Buttons ───────────────────────────────────────────────────────────────

  document.getElementById('btn-estop')?.addEventListener('click', () => {
    send({ action: 'estop' });
  });

  document.getElementById('btn-stop')?.addEventListener('click', () => {
    vy = vx = omega = 0;
    send({ action: 'stop' });
  });

  document.getElementById('btn-auto')?.addEventListener('click', () => {
    autoMode = !autoMode;
    send({ action: autoMode ? 'auto' : 'move', vy: 0, vx: 0, omega: 0 });
    if ($modeTag) $modeTag.textContent = autoMode ? 'AUTO' : 'MANUAL';
    document.getElementById('btn-auto').textContent = autoMode ? '🤖 Auto ✓' : '🤖 Auto';
  });

  document.getElementById('btn-calib')?.addEventListener('click', () => {
    send({ action: 'calibrate' });
  });

  // ── Emotion buttons ───────────────────────────────────────────────────────

  const EMOTIONS = [
    { name: 'idle',      icon: '😐', label: 'IDLE'     },
    { name: 'happy',     icon: '😁', label: 'HAPPY'    },
    { name: 'listening', icon: '👂', label: 'LISTEN'   },
    { name: 'thinking',  icon: '🤔', label: 'THINK'    },
    { name: 'speaking',  icon: '💬', label: 'SPEAK'    },
    { name: 'alert',     icon: '🚨', label: 'ALERT'    },
    { name: 'sleeping',  icon: '😴', label: 'SLEEP'    },
    { name: 'surprised', icon: '😲', label: 'SURPRISE' },
  ];

  const $emoGrid = document.getElementById('emotion-grid');
  if ($emoGrid) {
    EMOTIONS.forEach(({ name, icon, label }) => {
      const btn = document.createElement('button');
      btn.className = 'emo-btn';
      btn.id = `emo-${name}`;
      btn.innerHTML = `<span class="emo-icon">${icon}</span>${label}`;
      btn.addEventListener('click', () => {
        document.querySelectorAll('.emo-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        send({ action: 'emotion', name });
      });
      $emoGrid.appendChild(btn);
    });
  }

  // ── Chat ──────────────────────────────────────────────────────────────────

  if ($chatForm) {
    $chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = $chatInput?.value.trim();
      if (!text || !connected) return;
      appendMsg('user', text);
      $chatInput.value = '';
      $sendBtn.disabled = true;
      send({ action: 'chat', text });
      // Show typing indicator
      appendTyping();
    });
  }

  function appendMsg(from, text) {
    removeTyping();
    const div = document.createElement('div');
    div.className = `msg ${from === 'bob' ? 'bob-msg' : 'user-msg'}`;
    div.innerHTML = `
      <span class="msg-name">${from === 'bob' ? 'BOB' : 'YOU'}</span>
      <span class="msg-text">${escHtml(text)}</span>
    `;
    $chatMsgs?.appendChild(div);
    $chatMsgs?.scrollTo(0, $chatMsgs.scrollHeight);
  }

  let typingEl = null;
  function appendTyping() {
    removeTyping();
    typingEl = document.createElement('div');
    typingEl.className = 'msg bob-msg msg-typing';
    typingEl.innerHTML = `
      <span class="msg-name">BOB</span>
      <span class="msg-text">thinking…</span>
    `;
    $chatMsgs?.appendChild(typingEl);
    $chatMsgs?.scrollTo(0, $chatMsgs.scrollHeight);
  }

  function removeTyping() {
    typingEl?.remove();
    typingEl = null;
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Camera feed watchdog ──────────────────────────────────────────────────

  let camOk = false;
  if ($camFeed) {
    $camFeed.addEventListener('load',  () => { camOk = true;  if ($camOverlay) $camOverlay.classList.remove('visible'); });
    $camFeed.addEventListener('error', () => { camOk = false; if ($camOverlay) $camOverlay.classList.add('visible'); });
    // Periodic watchdog: reload if src goes stale
    setInterval(() => {
      if (!camOk && $camFeed) {
        $camFeed.src = `/video_feed?t=${Date.now()}`;
      }
    }, 8000);
  }

  // ── Status helpers ────────────────────────────────────────────────────────

  function setStatus(state, text) {
    if ($dot) {
      $dot.className = `status-dot ${state}`;
    }
    if ($statusTxt) $statusTxt.textContent = text;
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  setStatus('', 'Connecting…');
  connect();

})();
