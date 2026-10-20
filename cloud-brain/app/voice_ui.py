VOICE_UI = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cortex — Your Assistant</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      color-scheme: dark;
      --bg: #0b0d10;
      --panel: #13171d;
      --panel-2: #1c222b;
      --line: #29323f;
      --text: #f3f4f6;
      --muted: #9ca3af;
      --accent: #60a5fa;
      --accent-glow: rgba(96, 165, 250, 0.15);
      --accent-2: #34d399;
      --warn: #fbbf24;
      --bad: #f87171;
    }
    html, body {
      height: 100%;
      width: 100%;
      overflow: hidden;
      font-family: 'Outfit', ui-sans-serif, system-ui, -apple-system, sans-serif;
      background: radial-gradient(circle at 50% 0%, #1e293b 0%, var(--bg) 60%);
      color: var(--text);
    }
    button, input, select { font: inherit; color: inherit; }
    button { cursor: pointer; border: none; background: none; }

    /*
     * LAYOUT STRATEGY — 3-level flexbox column:
     *   .shell (flex column, 100vh)
     *     .topbar   (flex: 0 0 auto — fixed height, never shrinks)
     *     .stage    (flex: 1 1 0 + min-height:0 — grows to fill space)
     *       .stage-left  (flex child, overflow:hidden)
     *       .stage-right (flex child, min-height:0, inner scroll)
     *         .chat-history (flex:1 1 0, min-height:0, overflow-y:auto)
     *     .dock     (flex: 0 0 auto — fixed height, ALWAYS at bottom)
     *
     * The dock can NEVER be pushed off-screen because:
     *  - .shell is exactly 100vh
     *  - .topbar and .dock use flex: 0 0 auto (do not shrink/grow)
     *  - .stage gets exactly the remaining space (flex: 1 1 0)
     *  - overflow is hidden at the shell level
     */

    .shell {
      display: flex;
      flex-direction: column;
      width: 100%;
      height: 100vh;
      max-width: 1200px;
      margin: 0 auto;
      overflow: hidden;
    }

    /* ── Topbar ─────────────────────────────────────────────────── */
    .topbar {
      flex: 0 0 auto;
      padding: 12px 24px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(13, 16, 21, 0.8);
      backdrop-filter: blur(12px);
    }
    .brand { display: flex; align-items: center; gap: 10px; }
    .eyebrow {
      color: var(--accent);
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      display: block;
    }
    h1 {
      font-size: 20px;
      font-weight: 600;
      letter-spacing: -0.02em;
      line-height: 1.1;
    }
    .top-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .voice-select {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 5px 10px;
      font-size: 12px;
      outline: none;
      max-width: 160px;
    }
    .toggle-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--muted);
      cursor: pointer;
    }
    .status-badge {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 3px 10px;
      font-size: 11px;
      font-weight: 600;
      color: var(--accent-2);
      background: rgba(52, 211, 153, 0.08);
      text-transform: capitalize;
      white-space: nowrap;
    }
    .status-badge.waiting_approval {
      color: var(--warn);
      background: rgba(251,191,36,.08);
      border-color: rgba(251,191,36,.3);
    }
    .status-badge.failed, .status-badge.blocked {
      color: var(--bad);
      background: rgba(248,113,113,.08);
      border-color: rgba(248,113,113,.3);
    }
    .clear-btn {
      height: 32px;
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 10px;
      font-size: 12px;
      transition: all 160ms;
      white-space: nowrap;
    }
    .clear-btn:hover {
      background: rgba(248,113,113,0.1);
      border-color: var(--bad);
      color: var(--bad);
    }

    /* ── Stage ──────────────────────────────────────────────────── */
    .stage {
      flex: 1 1 0;
      min-height: 0;
      display: grid;
      grid-template-columns: 240px 1fr;
      overflow: hidden;
    }

    /* ── Left ──────────────────────────────────────────────────── */
    .stage-left {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 18px;
      padding: 20px 16px;
      border-right: 1px solid var(--line);
      overflow: hidden;
    }
    .voiceButton {
      flex-shrink: 0;
      width: 130px;
      height: 130px;
      border: 2px solid rgba(96,165,250,0.4);
      border-radius: 50%;
      background: radial-gradient(circle, rgba(96,165,250,0.18) 0%, rgba(30,41,59,0.6) 100%);
      box-shadow: 0 0 30px var(--accent-glow);
      display: grid;
      place-items: center;
      transition: all 280ms ease;
    }
    .voiceButton:hover { transform: scale(1.04); border-color: var(--accent); }
    .voiceButton.listening {
      border-color: var(--warn);
      background: radial-gradient(circle, rgba(251,191,36,0.22) 0%, rgba(30,41,59,0.6) 100%);
      box-shadow: 0 0 40px rgba(251,191,36,0.25);
      animation: pulse 1.5s infinite;
    }
    .voiceIcon { font-size: 32px; }
    .transcript-box {
      width: 100%;
      min-height: 52px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: rgba(13,16,21,0.35);
      color: var(--muted);
      font-size: 12.5px;
      text-align: center;
      line-height: 1.5;
      word-break: break-word;
    }
    .approval {
      display: flex;
      gap: 8px;
      width: 100%;
    }
    .approval button {
      flex: 1;
      height: 34px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 12px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      transition: background 160ms;
    }
    #approve { background: var(--accent-2); color: #0b0d10; border-color: var(--accent-2); }
    #approve:hover { background: #059669; }
    #reject:hover { background: var(--bad); color: #0b0d10; border-color: var(--bad); }

    /* ── Right: chat ────────────────────────────────────────────── */
    .stage-right {
      display: flex;
      flex-direction: column;
      min-height: 0;
      overflow: hidden;
    }
    .chat-history {
      flex: 1 1 0;
      min-height: 0;
      overflow-y: auto;
      padding: 18px 18px 10px 18px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }
    .chat-history::-webkit-scrollbar { width: 5px; }
    .chat-history::-webkit-scrollbar-thumb { background: var(--line); border-radius: 3px; }

    .msg {
      max-width: 90%;
      border-radius: 14px;
      padding: 10px 14px;
      line-height: 1.65;
      font-size: 14px;
      animation: fadeIn 180ms ease;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .msg.user {
      align-self: flex-end;
      background: var(--accent);
      color: #0b0d10;
      border-bottom-right-radius: 4px;
      font-weight: 500;
    }
    .msg.cortex {
      align-self: flex-start;
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-bottom-left-radius: 4px;
    }
    .msg.thinking {
      color: var(--muted);
      font-style: italic;
      animation: fadeIn 180ms ease, blink 1.1s infinite;
    }

    /* ── Dock — ALWAYS locked at bottom ─────────────────────────── */
    .dock {
      flex: 0 0 auto;
      border-top: 1px solid var(--line);
      padding: 12px 20px;
      background: rgba(13,16,21,0.8);
      backdrop-filter: blur(12px);
    }
    .composer {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    #textInput {
      flex: 1;
      height: 44px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0 16px;
      background: var(--panel);
      outline: none;
      font-size: 14px;
      color: var(--text);
      transition: border-color 180ms;
    }
    #textInput:focus { border-color: var(--accent); }
    #textInput:disabled { opacity: 0.45; cursor: not-allowed; }
    .icon-btn {
      flex-shrink: 0;
      width: 44px;
      height: 44px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-2);
      display: grid;
      place-items: center;
      font-size: 16px;
      transition: all 160ms;
    }
    .icon-btn:hover:not(:disabled) { background: var(--line); }
    .icon-btn.send { background: var(--accent); color: #0b0d10; border-color: var(--accent); }
    .icon-btn.send:hover:not(:disabled) { background: #3b82f6; }
    .icon-btn:disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }

    /* ── Animations ─────────────────────────────────────────────── */
    @keyframes pulse {
      0%,100% { transform: scale(1); }
      50%      { transform: scale(1.04); }
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes blink {
      0%,100% { opacity: 1; }
      50%      { opacity: 0.35; }
    }

    /* ── Responsive ─────────────────────────────────────────────── */
    @media (max-width: 680px) {
      .stage {
        grid-template-columns: 1fr;
        grid-template-rows: auto 1fr;
      }
      .stage-left {
        flex-direction: row;
        justify-content: flex-start;
        padding: 10px 14px;
        gap: 10px;
        border-right: none;
        border-bottom: 1px solid var(--line);
        min-height: unset;
      }
      .voiceButton { width: 46px; height: 46px; }
      .voiceIcon   { font-size: 20px; }
      .transcript-box { min-height: 30px; font-size: 12px; text-align: left; }
      .approval    { display: none; }
    }
  </style>
</head>
<body>
<div class="shell">

  <!-- ── Topbar ─────────────────────────────────────────────── -->
  <header class="topbar">
    <div class="brand">
      <div>
        <span class="eyebrow">AI Assistant</span>
        <h1>Cortex</h1>
      </div>
    </div>
    <div class="top-controls">
      <select id="voiceSelect" class="voice-select" title="Select voice"></select>
      <label class="toggle-label">
        <input type="checkbox" id="continuousCheck" />
        <span>Continuous</span>
      </label>
      <button id="clearMemory" class="clear-btn">Clear Memory</button>
      <div id="statusBadge" class="status-badge">Ready</div>
    </div>
  </header>

  <!-- ── Stage ──────────────────────────────────────────────── -->
  <div class="stage">

    <!-- Left: mic, transcript, approval -->
    <div class="stage-left">
      <button id="mic" class="voiceButton" aria-label="Toggle voice" title="Click or press Option+Space">
        <span class="voiceIcon">🎙️</span>
      </button>
      <div id="transcript" class="transcript-box">Click the mic or type below to talk to Cortex.</div>
      <div id="approval" class="approval" hidden>
        <button id="approve">✅ Approve</button>
        <button id="reject">❌ Reject</button>
      </div>
    </div>

    <!-- Right: chat history -->
    <div class="stage-right">
      <div id="chatHistory" class="chat-history">
        <div class="msg cortex">Hello! I'm Cortex — your AI desktop assistant. Ask me anything or tell me what to do.</div>
      </div>
    </div>

  </div><!-- /stage -->

  <!-- ── Dock — always at bottom ────────────────────────────── -->
  <div class="dock">
    <div class="composer">
      <input id="textInput" type="text" placeholder="Ask anything or give a command…" autocomplete="off" />
      <button id="sendBtn" class="icon-btn send" aria-label="Send" title="Send (Enter)">➤</button>
      <button id="cancelBtn" class="icon-btn" aria-label="Cancel task" title="Cancel current task" hidden>🛑</button>
    </div>
  </div>

</div><!-- /shell -->

<script>
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  const mic           = document.getElementById('mic');
  const textInput     = document.getElementById('textInput');
  const sendBtn       = document.getElementById('sendBtn');
  const cancelBtn     = document.getElementById('cancelBtn');
  const statusBadge   = document.getElementById('statusBadge');
  const transcriptEl  = document.getElementById('transcript');
  const chatHistory   = document.getElementById('chatHistory');
  const approvalEl    = document.getElementById('approval');
  const approveBtn    = document.getElementById('approve');
  const rejectBtn     = document.getElementById('reject');
  const voiceSelect   = document.getElementById('voiceSelect');
  const continuousCheck = document.getElementById('continuousCheck');
  const clearMemory   = document.getElementById('clearMemory');

  let activeTask   = null;
  let recognition  = null;
  let isListening  = false;
  let isBusy       = false;
  const synth      = window.speechSynthesis;

  /* ── Voice list ──────────────────────────────────────────── */
  function populateVoiceList() {
    if (!synth) return;
    voiceSelect.innerHTML = '';
    synth.getVoices().forEach(v => {
      const opt = document.createElement('option');
      opt.textContent = v.name + ' (' + v.lang + ')';
      opt.value = v.name;
      if (v.default) opt.selected = true;
      voiceSelect.appendChild(opt);
    });
  }
  populateVoiceList();
  if (synth && synth.onvoiceschanged !== undefined) synth.onvoiceschanged = populateVoiceList;

  /* ── TTS ─────────────────────────────────────────────────── */
  function speak(text) {
    if (!synth || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 500));
    const voice = synth.getVoices().find(v => v.name === voiceSelect.value);
    if (voice) u.voice = voice;
    if (isListening && recognition) recognition.abort();
    u.onend = () => {
      if (isListening && recognition && continuousCheck.checked) {
        try { recognition.start(); } catch(e) {}
      }
    };
    synth.speak(u);
  }

  /* ── Chat bubbles ────────────────────────────────────────── */
  function appendMsg(sender, text, isThinking) {
    const el = document.createElement('div');
    el.className = 'msg ' + sender + (isThinking ? ' thinking' : '');
    el.textContent = text;
    if (isThinking) el.id = 'thinking-bubble';
    chatHistory.appendChild(el);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return el;
  }

  function removeThinking() {
    const el = document.getElementById('thinking-bubble');
    if (el) el.remove();
  }

  /* ── Status / task rendering ─────────────────────────────── */
  function setStatus(text, cls) {
    statusBadge.textContent = text;
    statusBadge.className   = 'status-badge' + (cls ? ' ' + cls : '');
  }

  function renderTask(task) {
    if (!task) return;
    activeTask = task;
    const s = (task.status || 'ready').replace(/_/g, ' ');
    setStatus(s, task.status);
    const needApproval = task.requiresApproval && task.status === 'waiting_approval';
    approvalEl.hidden = !needApproval;
    const terminal = ['completed','failed','blocked','canceled'];
    cancelBtn.hidden = !task || terminal.includes(task.status);
  }

  /* ── Busy lock: disables input while Cortex is thinking ───── */
  function setBusy(busy) {
    isBusy              = busy;
    textInput.disabled  = busy;
    sendBtn.disabled    = busy;
  }

  /* ── Core send ───────────────────────────────────────────── */
  async function sendCommand(value, source) {
    const cmd = (value || '').trim();
    if (!cmd || isBusy) return;

    /* Clear + refocus the input field immediately */
    textInput.value = '';
    textInput.focus();

    setBusy(true);
    setStatus(source === 'voice' ? 'Heard…' : 'Thinking…');
    transcriptEl.textContent = cmd;
    appendMsg('user', cmd);
    appendMsg('cortex', 'Thinking…', true);

    try {
      const res  = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: cmd, source: source || 'text' }),
      });
      const data = await res.json();
      removeThinking();
      const reply = data.message || 'Done.';
      appendMsg('cortex', reply);
      if (data.task) renderTask(data.task);
      else setStatus('Ready');
      speak(reply);
    } catch (err) {
      removeThinking();
      appendMsg('cortex', '⚠️  Cannot reach Cortex backend. Is the server running?');
      setStatus('Error', 'failed');
    } finally {
      setBusy(false);
      textInput.focus();
    }
  }

  /* ── Approval ────────────────────────────────────────────── */
  async function decide(approved) {
    if (!activeTask || isBusy) return;
    setBusy(true);
    try {
      const res  = await fetch('/tasks/' + activeTask.id + '/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      });
      const task = await res.json();
      renderTask(task);
      const msg = task.result || task.error || (approved ? 'Done.' : 'Cancelled.');
      appendMsg('cortex', msg);
      speak(msg);
    } catch(e) {
      appendMsg('cortex', 'Approval request failed.');
    } finally {
      setBusy(false);
      textInput.focus();
    }
  }

  /* ── Cancel ──────────────────────────────────────────────── */
  async function cancelTask() {
    if (!activeTask || isBusy) return;
    setBusy(true);
    try {
      const res  = await fetch('/tasks/' + activeTask.id + '/cancel', { method: 'POST' });
      const task = await res.json();
      renderTask(task);
      const msg = task.result || 'Task cancelled.';
      appendMsg('cortex', msg);
      speak(msg);
    } catch(e) {
      appendMsg('cortex', 'Could not cancel task.');
    } finally {
      setBusy(false);
      textInput.focus();
    }
  }

  /* ── Speech recognition ──────────────────────────────────── */
  function initRecognition() {
    if (!SpeechRecognition) return;
    recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.continuous     = false;

    recognition.onstart = () => {
      isListening = true;
      mic.classList.add('listening');
      setStatus('Listening…');
      transcriptEl.textContent = 'Listening…';
    };

    recognition.onresult = (e) => {
      const t = e.results[0][0].transcript;
      textInput.value = t;
      sendCommand(t, 'voice');
    };

    recognition.onerror = (e) => {
      transcriptEl.textContent = 'Voice error: ' + e.error;
      setStatus('Ready');
      isListening = false;
      mic.classList.remove('listening');
    };

    recognition.onend = () => {
      isListening = false;
      mic.classList.remove('listening');
      if (continuousCheck.checked && !isBusy && !synth.speaking) {
        try { recognition.start(); } catch(e) {}
      } else if (!isBusy) {
        setStatus('Ready');
      }
    };
  }

  function toggleListening() {
    if (!SpeechRecognition) {
      appendMsg('cortex', 'Speech recognition requires Chrome or Edge browser.');
      return;
    }
    if (!recognition) initRecognition();
    if (isListening) {
      continuousCheck.checked = false;
      recognition.stop();
    } else {
      recognition.start();
    }
  }

  /* ── Event wiring ────────────────────────────────────────── */
  mic.addEventListener('click', toggleListening);

  sendBtn.addEventListener('click', () => {
    const v = textInput.value;
    if (v.trim()) sendCommand(v, 'text');
  });

  textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const v = textInput.value;
      if (v.trim()) sendCommand(v, 'text');
    }
  });

  clearMemory.addEventListener('click', async () => {
    try {
      await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'clear history', source: 'text' }),
      });
      chatHistory.innerHTML = '<div class="msg cortex">Memory cleared. Ready for a fresh start!</div>';
      transcriptEl.textContent = 'Memory cleared.';
      speak('Memory cleared.');
      setStatus('Ready');
    } catch(e) {
      appendMsg('cortex', 'Failed to clear memory.');
    }
    textInput.focus();
  });

  approveBtn.addEventListener('click', () => decide(true));
  rejectBtn.addEventListener('click',  () => decide(false));
  cancelBtn.addEventListener('click',  cancelTask);

  /* Option+Space global shortcut */
  window.addEventListener('keydown', (e) => {
    if (e.altKey && e.code === 'Space') {
      e.preventDefault();
      toggleListening();
    }
  });

  /* Auto-focus the input on load */
  textInput.focus();
</script>
</body>
</html>
"""
