/* ============================================================
   ADA Agent — Secure AI Executive Assistant
   Frontend Logic — app.js
   ============================================================ */

'use strict';

// ── State ────────────────────────────────────────────────────
const state = {
  sessionId:       null,
  userId:          null,
  instructionType: 'draft',
  currentView:     'dashboard',
  llmReady:        false,
};

// ── API helpers ──────────────────────────────────────────────

async function api(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ── Toast ────────────────────────────────────────────────────

function toast(msg, type = 'info') {
  const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `
    <span style="font-size:15px;flex-shrink:0;">${icons[type] || 'ℹ'}</span>
    <span style="flex:1;">${escHtml(msg)}</span>
    <div class="toast-progress"></div>
  `;
  const container = document.getElementById('toast-container');
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('removing');
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

// ── Auth ─────────────────────────────────────────────────────

async function doLogin() {
  const userId   = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl    = document.getElementById('login-error');
  const btn      = document.getElementById('login-btn');

  if (!userId || !password) {
    errEl.textContent = 'Please enter your email and password.';
    errEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Signing in…';
  errEl.style.display = 'none';

  try {
    const data = await api('POST', '/auth/login', { user_id: userId, password });
    await _onAuthSuccess(data, userId);
  } catch (err) {
    errEl.textContent = err.message || 'Login failed. Please try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sign In';
  }
}

async function _onAuthSuccess(data, userId) {
  state.sessionId = data.session_id;
  state.userId    = data.user_id;

  try {
    const health = await api('GET', '/health');
    state.llmReady = health.llm_ready === true;
  } catch (_) {
    state.llmReady = false;
  }

  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app').style.display = 'flex';
  updateSessionBadge();
  showView('dashboard');
  loadDashboard();
  loadAuditEventTypes();
  toast('Welcome, ' + userId + '!', 'success');
}

async function doLogout() {
  if (state.sessionId) {
    await api('POST', `/auth/logout?session_id=${state.sessionId}`).catch(() => {});
  }
  state.sessionId = null;
  state.userId    = null;
  state.llmReady  = false;
  document.getElementById('app').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('login-pass').value = '';
  document.getElementById('new-chat-btn').style.display = 'none';
  toast('Logged out successfully', 'info');
}

function updateSessionBadge() {
  const userEl   = document.getElementById('session-user-label');
  const dot      = document.getElementById('session-dot');
  const statusTx = document.getElementById('session-status-text');
  const avatar   = document.getElementById('user-avatar');

  if (state.sessionId) {
    userEl.textContent   = state.userId || 'User';
    dot.className        = 'status-dot online';
    statusTx.textContent = 'Online';
    avatar.textContent   = (state.userId || 'U').charAt(0).toUpperCase();
  } else {
    userEl.textContent   = 'Not logged in';
    dot.className        = 'status-dot offline';
    statusTx.textContent = 'Offline';
    avatar.textContent   = '?';
  }
}

function updateLlmPill() {
  const pill = document.getElementById('llm-pill');
  const text = document.getElementById('llm-pill-text');
  pill.style.display = 'inline-flex';
  if (state.llmReady) {
    pill.className = 'llm-pill ready';
    text.textContent = 'LLM Ready';
  } else {
    pill.className = 'llm-pill offline';
    text.textContent = 'LLM Offline';
  }
}

// Allow Enter key on login form
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-pass').addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });
  document.getElementById('login-user').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('login-pass').focus();
  });
  document.getElementById('signup-pass2').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSignUp();
  });
});

function switchAuthTab(tab) {
  const isSignIn = tab === 'signin';
  document.getElementById('form-signin').style.display = isSignIn ? 'block' : 'none';
  document.getElementById('form-signup').style.display = isSignIn ? 'none' : 'block';
  document.getElementById('tab-signin').classList.toggle('active', isSignIn);
  document.getElementById('tab-signup').classList.toggle('active', !isSignIn);
  document.getElementById('login-error').style.display = 'none';
  document.getElementById('login-error').textContent = '';
}

async function doSignUp() {
  const userId   = document.getElementById('signup-user').value.trim();
  const password = document.getElementById('signup-pass').value;
  const password2 = document.getElementById('signup-pass2').value;
  const errEl    = document.getElementById('login-error');
  const btn      = document.getElementById('signup-btn');

  errEl.style.display = 'none';

  if (!userId) {
    errEl.textContent = 'Please enter your email address.';
    errEl.style.display = 'block'; return;
  }
  if (!userId.includes('@')) {
    errEl.textContent = 'Please enter a valid email address.';
    errEl.style.display = 'block'; return;
  }
  if (!password || password.length < 6) {
    errEl.textContent = 'Password must be at least 6 characters.';
    errEl.style.display = 'block'; return;
  }
  if (password !== password2) {
    errEl.textContent = 'Passwords do not match.';
    errEl.style.display = 'block'; return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Creating account…';

  try {
    const data = await api('POST', '/auth/register', { user_id: userId, password });
    await _onAuthSuccess(data, userId);
  } catch (err) {
    errEl.textContent = err.message || 'Registration failed. Please try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Account';
  }
}

// ── Navigation ───────────────────────────────────────────────

const VIEW_TITLES = {
  dashboard: 'Dashboard',
  chat:      'Chat with Agent',
  scheduled: 'Scheduled Drafts',
  tone:      'Tone Profiles',
  audit:     'Audit Log',
};

function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  const navEl = document.getElementById('nav-' + name);
  if (navEl) navEl.classList.add('active');
  document.getElementById('topbar-title').textContent = VIEW_TITLES[name] || name;
  state.currentView = name;

  // Show "New Chat" button only on chat view
  const newChatBtn = document.getElementById('new-chat-btn');
  newChatBtn.style.display = (name === 'chat') ? 'inline-flex' : 'none';

  // Lazy-load data
  if (name === 'dashboard') loadDashboard();
  if (name === 'scheduled') loadScheduled();
  if (name === 'tone')      loadToneProfiles();
  if (name === 'audit')     loadAuditLog();
}

// ── Dashboard ────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const [auditData, scheduledData, toneData] = await Promise.allSettled([
      api('GET', '/audit/logs?limit=10'),
      api('GET', '/schedule/drafts'),
      api('GET', '/tone/profiles'),
    ]);

    if (auditData.status === 'fulfilled') {
      const val = auditData.value.length;
      const el  = document.getElementById('stat-audit');
      animateStatValue(el, val);
      renderActivityFeed(auditData.value);
    }
    if (scheduledData.status === 'fulfilled') {
      const pending = scheduledData.value.filter(d => d.status === 'pending').length;
      const total   = scheduledData.value.length;
      const el      = document.getElementById('stat-scheduled');
      el.textContent = `${pending}/${total}`;
    }
    if (toneData.status === 'fulfilled') {
      const el = document.getElementById('stat-tone');
      animateStatValue(el, toneData.value.length);
    }

    document.getElementById('stat-session').textContent = state.sessionId ? 'Active' : 'None';
    document.getElementById('stat-user').textContent    = state.userId || '—';
  } catch (err) {
    console.error('Dashboard load error:', err);
  }
}

function renderActivityFeed(entries) {
  const feed = document.getElementById('dashboard-activity-feed');
  if (!entries || !entries.length) {
    feed.innerHTML = `<div class="empty-state" style="padding:24px 0;">
      <div class="empty-icon">◉</div><p>No activity yet.</p></div>`;
    return;
  }

  const iconMap = {
    EMAIL_SENT:                    { icon: '✉', color: 'var(--success)' },
    DRAFT_CREATED:                 { icon: '✦', color: 'var(--accent)' },
    SESSION_STARTED:               { icon: '◉', color: 'var(--info)' },
    SESSION_EXPIRED:               { icon: '◌', color: 'var(--text-muted)' },
    AUTH_FAILED:                   { icon: '✕', color: 'var(--danger)' },
    PROMPT_INJECTION_DETECTED:     { icon: '⚠', color: 'var(--danger)' },
    APPROVAL_GATE_PRESENTED:       { icon: '⚑', color: 'var(--warning)' },
    SCHEDULED_DRAFT_REGISTERED:    { icon: '◷', color: 'var(--info)' },
    SCHEDULED_DRAFT_CANCELLED:     { icon: '✖', color: 'var(--text-muted)' },
    EMAIL_DELETED:                 { icon: '🗑', color: 'var(--danger)' },
  };

  feed.innerHTML = entries.slice(0, 10).map(e => {
    const meta  = iconMap[e.event_type] || { icon: '◈', color: 'var(--text-muted)' };
    return `
      <div class="activity-item">
        <div class="activity-icon" style="color:${meta.color};">${meta.icon}</div>
        <div class="activity-body">
          <div class="activity-text">${escHtml(e.description)}</div>
          <div class="activity-time">${eventTypeBadge(e.event_type)} · ${formatTime(e.timestamp)}</div>
        </div>
      </div>`;
  }).join('');
}

// ── Chat ─────────────────────────────────────────────────────

function setInstructionType(type, el) {
  state.instructionType = type;
  document.querySelectorAll('.type-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
}

function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendInstruction();
  }
}

async function sendInstruction() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text) return;
  if (!state.sessionId) { toast('Please log in first', 'error'); return; }

  appendChatMessage('user', null, text + (_attachedNotes ? `\n📎 ${_attachedNotes.name}` : ''));
  input.value = '';

  const btn = document.getElementById('send-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  const thinkingId = appendThinkingIndicator();

  try {
    const data = await api('POST', '/agent/instruct', {
      session_id:       state.sessionId,
      text,
      instruction_type: state.instructionType,
      payload: _attachedNotes ? { meeting_notes: _attachedNotes.content } : null,
    });
    removeThinkingIndicator(thinkingId);
    renderAgentResponse(data);
    // Clear attachment after sending
    removeAttachment();
  } catch (err) {
    removeThinkingIndicator(thinkingId);
    appendChatMessage('agent', 'error', `Error: ${err.message}`);
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send';
  }
}

function appendChatMessage(role, type, content) {
  const container = document.getElementById('chat-messages');
  const div       = document.createElement('div');
  div.className   = `chat-message ${role}`;

  const avatarHtml = role === 'user'
    ? `<div class="chat-avatar" style="font-size:12px;color:var(--text-muted);">You</div>`
    : `<div class="chat-avatar">A</div>`;

  const typeClass = type === 'error' ? 'error' : type === 'success' ? 'success' : 'info';
  const typeHtml  = type ? `<div class="msg-type ${typeClass}">${type.toUpperCase()}</div>` : '';
  const bubbleExtra = type === 'error' ? ' error-bubble' : '';

  div.innerHTML = `
    ${avatarHtml}
    <div class="chat-bubble${bubbleExtra}">${typeHtml}${escHtml(content)}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function appendThinkingIndicator() {
  const container = document.getElementById('chat-messages');
  const id  = 'thinking-' + Date.now();
  const div = document.createElement('div');
  div.className = 'chat-message agent';
  div.id = id;
  div.innerHTML = `
    <div class="chat-avatar">A</div>
    <div class="chat-bubble">${renderTypingDots()}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeThinkingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function renderAgentResponse(resp) {
  const container = document.getElementById('chat-messages');
  const div       = document.createElement('div');
  div.className   = 'chat-message agent';

  const typeClass = !resp.success || resp.type === 'error' ? 'error'
                  : resp.type === 'draft'                  ? 'draft'
                  : 'success';

  let bodyHtml = `<div class="msg-type ${typeClass}">${escHtml(resp.type.toUpperCase())}</div>`;
  bodyHtml += escHtml(resp.message);

  // Draft payload → beautiful email preview card
  if (resp.payload && resp.type === 'draft') {
    const draftObj = resp.payload.draft_id ? resp.payload : (resp.payload.draft || resp.payload);
    bodyHtml += renderDraftCard(draftObj);
  }

  // Approval gate
  if (resp.type === 'approval_gate' && resp.payload) {
    bodyHtml += renderApprovalGate(resp.payload, resp.response_id);
  }

  const bubbleExtra = (!resp.success || resp.type === 'error') ? ' error-bubble' : '';
  div.innerHTML = `
    <div class="chat-avatar">A</div>
    <div class="chat-bubble${bubbleExtra}">${bodyHtml}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function renderDraftCard(d) {
  const sources = d.context_summary && d.context_summary.data_sources
    ? d.context_summary.data_sources.join(', ')
    : '';
  const bodyText = escHtml(d.body || '');

  // Store the full draft object for send/copy actions
  const draftKey = 'draft_' + (d.draft_id || Date.now());
  // Ensure we store the actual draft fields, not a wrapper
  const draftObj = d.draft_id ? d : (d.draft || d);
  window[draftKey] = draftObj;

  return `
    <div class="draft-card">
      <div class="draft-card-header">
        <div class="draft-field">
          <span class="draft-field-label">To</span>
          <span class="draft-field-value">${escHtml(d.recipient || '')}</span>
        </div>
        <div class="draft-field">
          <span class="draft-field-label">Subject</span>
          <span class="draft-field-value">${escHtml(d.subject || '')}</span>
        </div>
      </div>
      <div class="draft-body">${bodyText}</div>
      <div class="draft-footer">
        <button class="btn btn-sm btn-secondary"
          onclick="copyDraftToClipboard('${draftKey}')">
          ⎘ Copy
        </button>
        <button class="btn btn-sm btn-primary"
          onclick="sendDraftDirectly('${draftKey}')">
          ↗ Send this draft
        </button>
        ${sources ? `<span class="draft-sources">📎 ${escHtml(sources)}</span>` : ''}
      </div>
    </div>`;
}

// Pending gate payloads waiting for confirmation
let _pendingSchedulePayload = null;
let _pendingSendPayload = null;

function renderApprovalGate(payload, responseId) {
  const safeId = escHtml(String(responseId || ''));
  const isSchedule = payload.gate_type === 'schedule';
  const isSend     = payload.gate_type === 'send';

  let detailsHtml = '';
  if (payload.recipient) detailsHtml += `<div class="gate-detail">
    <span class="label">To</span>
    <span>${escHtml(payload.recipient)}</span></div>`;
  if (payload.subject) detailsHtml += `<div class="gate-detail">
    <span class="label">Subject</span>
    <span>${escHtml(payload.subject)}</span></div>`;
  if (isSchedule && payload.send_time) detailsHtml += `<div class="gate-detail">
    <span class="label">Scheduled for</span>
    <span>${escHtml(formatTime(payload.send_time))}</span></div>`;

  // Show draft body preview
  let bodyPreview = '';
  const draftBody = payload.draft && payload.draft.body;
  if (draftBody) {
    bodyPreview = `<div class="draft-body" style="margin:10px 0;max-height:160px;overflow-y:auto;">
      ${escHtml(draftBody)}</div>`;
  }

  if (isSchedule) {
    _pendingSchedulePayload = { draft: payload.draft, send_time: payload.send_time };
  }
  if (isSend) {
    _pendingSendPayload = { draft: payload.draft };
  }

  const confirmAction = isSchedule ? `confirmSchedule()`
                      : isSend     ? `confirmSend()`
                      : `submitApproval('confirmed','${safeId}')`;
  const cancelAction  = isSchedule ? `cancelScheduleGate()`
                      : isSend     ? `cancelSendGate()`
                      : `submitApproval('cancelled','${safeId}')`;

  const gateTitle = isSchedule ? 'Schedule Confirmation'
                  : isSend     ? 'Send Confirmation'
                  : 'Approval Required';

  return `
    <div class="approval-gate">
      <div class="gate-header">⚑ ${gateTitle}</div>
      <div class="gate-detail">
        <span class="label">Action</span>
        <span>${escHtml(payload.gate_type || 'Sensitive action')}</span>
      </div>
      ${detailsHtml}
      ${bodyPreview}
      <div class="gate-actions">
        <button class="btn btn-success btn-sm" onclick="${confirmAction}">✓ Confirm</button>
        <button class="btn btn-danger btn-sm" onclick="${cancelAction}">✕ Cancel</button>
      </div>
    </div>`;
}

async function confirmSend() {
  if (!state.sessionId || !_pendingSendPayload) {
    toast('No pending send to confirm', 'error');
    return;
  }
  const payload = _pendingSendPayload;
  _pendingSendPayload = null;
  try {
    const data = await api('POST', '/agent/instruct', {
      session_id:       state.sessionId,
      text:             'confirm send',
      instruction_type: 'confirm_send',
      payload,
    });
    renderAgentResponse(data);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function cancelSendGate() {
  _pendingSendPayload = null;
  appendChatMessage('agent', 'info', 'Send cancelled.');
}

async function confirmSchedule() {
  if (!state.sessionId || !_pendingSchedulePayload) {
    toast('No pending schedule to confirm', 'error');
    return;
  }
  const payload = _pendingSchedulePayload;
  _pendingSchedulePayload = null;
  try {
    const data = await api('POST', '/agent/instruct', {
      session_id:       state.sessionId,
      text:             'confirm schedule',
      instruction_type: 'confirm_schedule',
      payload,
    });
    renderAgentResponse(data);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function cancelScheduleGate() {
  _pendingSchedulePayload = null;
  appendChatMessage('agent', 'info', 'Schedule cancelled.');
}

async function submitApproval(decision, responseId) {
  if (!state.sessionId) return;
  try {
    const data = await api('POST', '/agent/instruct', {
      session_id:       state.sessionId,
      text:             `approval_decision:${decision}:${responseId}`,
      instruction_type: 'approval',
    });
    renderAgentResponse(data);
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Meeting notes attachment ─────────────────────────────────

let _attachedNotes = null; // { name, content }

function handleNotesAttachment(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    _attachedNotes = { name: file.name, content: e.target.result };
    document.getElementById('attach-filename').textContent = '📄 ' + file.name;
    document.getElementById('attach-preview').style.display = 'flex';
    toast(`Attached: ${file.name}`, 'success');
  };
  reader.onerror = () => toast('Could not read file', 'error');

  // Only accept plain text formats
  const allowed = ['text/plain', 'text/markdown', ''];
  const ext = file.name.split('.').pop().toLowerCase();
  const allowedExts = ['txt', 'md'];
  if (!allowedExts.includes(ext)) {
    toast('Only .txt and .md files are supported. For PDFs, paste the text directly into the chat.', 'warning');
    event.target.value = '';
    return;
  }

  // Read as text
  reader.readAsText(file);

  // Reset input so same file can be re-attached
  event.target.value = '';
}

function removeAttachment() {
  _attachedNotes = null;
  document.getElementById('attach-preview').style.display = 'none';
  document.getElementById('attach-filename').textContent = '';
}



function copyDraftToClipboard(draftKey) {
  const draft = window[draftKey];
  const text = draft ? (draft.body || '') : draftKey;
  navigator.clipboard.writeText(text).then(() => {
    toast('Draft body copied to clipboard', 'success');
  }).catch(() => {
    toast('Could not copy to clipboard', 'error');
  });
}

async function sendDraftDirectly(draftKey) {
  if (!state.sessionId) { toast('Please log in first', 'error'); return; }
  const draft = window[draftKey];
  if (!draft) { toast('Draft not found', 'error'); return; }

  const thinkingId = appendThinkingIndicator();
  try {
    const data = await api('POST', '/agent/instruct', {
      session_id:       state.sessionId,
      text:             `Send email to ${draft.recipient}`,
      instruction_type: 'send',
      payload:          draft,
    });
    removeThinkingIndicator(thinkingId);
    renderAgentResponse(data);
  } catch (err) {
    removeThinkingIndicator(thinkingId);
    appendChatMessage('agent', 'error', `Error: ${err.message}`);
    toast(err.message, 'error');
  }
}

function renderTypingDots() {
  return `<div class="typing-dots">
    <span></span><span></span><span></span>
  </div>`;
}

function animateStatValue(el, target) {
  if (!el) return;
  const start    = 0;
  const duration = 600;
  const startTs  = performance.now();
  function step(ts) {
    const progress = Math.min((ts - startTs) / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── Scheduled Drafts ─────────────────────────────────────────

async function loadScheduled() {
  const filter = document.getElementById('schedule-filter').value;
  const url    = '/schedule/drafts' + (filter ? `?status_filter=${filter}` : '');
  const grid   = document.getElementById('scheduled-grid');
  grid.innerHTML = `<div class="empty-state"><div class="empty-icon">
    <span class="spinner"></span></div><p>Loading…</p></div>`;

  try {
    const drafts = await api('GET', url);
    if (!drafts.length) {
      grid.innerHTML = `<div class="empty-state">
        <div class="empty-icon">◷</div>
        <p>No scheduled drafts found.</p></div>`;
      return;
    }
    grid.innerHTML = `<div class="drafts-grid">
      ${drafts.map(d => {
        const initials = (d.recipient || '?').charAt(0).toUpperCase();
        const canCancel = d.status === 'pending' || d.status === 'awaiting_confirmation';
        return `
          <div class="draft-item-card">
            <div class="draft-item-header">
              <div class="recipient-avatar">${initials}</div>
              <div class="draft-item-meta">
                <div class="draft-item-recipient">${escHtml(d.recipient)}</div>
                <div class="draft-item-subject">${escHtml(d.subject)}</div>
              </div>
            </div>
            <div class="draft-item-footer">
              <div>
                ${scheduledStatusBadge(d.status)}
                <div class="draft-item-time" style="margin-top:4px;">
                  ${formatTime(d.scheduled_send_time)}
                </div>
              </div>
              ${canCancel
                ? `<button class="btn btn-sm btn-danger"
                     onclick="cancelScheduled('${escHtml(d.scheduled_draft_id)}')">
                     ✕ Cancel</button>`
                : ''}
            </div>
          </div>`;
      }).join('')}
    </div>`;
  } catch (err) {
    grid.innerHTML = `<div class="empty-state">
      <div class="empty-icon" style="color:var(--danger);">✕</div>
      <p style="color:var(--danger);">${escHtml(err.message)}</p></div>`;
  }
}

async function cancelScheduled(id) {
  if (!confirm('Cancel this scheduled draft?')) return;
  try {
    await api('DELETE', `/schedule/drafts/${id}`);
    toast('Scheduled draft cancelled', 'success');
    loadScheduled();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Tone Profiles ────────────────────────────────────────────

async function loadToneProfiles() {
  const container = document.getElementById('tone-profiles-container');
  container.innerHTML = `<div class="empty-state">
    <div class="empty-icon"><span class="spinner"></span></div>
    <p>Loading…</p></div>`;

  try {
    const profiles = await api('GET', '/tone/profiles');
    if (!profiles.length) {
      container.innerHTML = `<div class="empty-state">
        <div class="empty-icon">◈</div>
        <p>No tone profiles yet. Send emails to build recipient profiles.</p></div>`;
      return;
    }
    container.innerHTML = `<div class="tone-grid">
      ${profiles.map(p => {
        const initials = (p.recipient_email || '?').charAt(0).toUpperCase();
        return `
          <div class="tone-card">
            <div class="tone-card-header">
              <div class="tone-avatar">${initials}</div>
              <div>
                <div class="tone-email">${escHtml(p.recipient_email)}</div>
                <div class="tone-sample">${p.sample_size} email${p.sample_size !== 1 ? 's' : ''} analysed</div>
              </div>
            </div>
            <div class="tone-row">
              <span class="tone-row-label">Formality</span>
              ${formalityBadge(p.formality_level)}
            </div>
            <div class="tone-row">
              <span class="tone-row-label">Warmth</span>
              ${warmthBar(p.warmth_indicator)}
            </div>
            <div class="tone-row">
              <span class="tone-row-label">Technical</span>
              <span class="badge badge-muted">${escHtml(p.technical_language_usage)}</span>
            </div>
            <div class="tone-row">
              <span class="tone-row-label">Avg length</span>
              <span class="badge badge-muted">${escHtml(String(p.avg_sentence_length))}</span>
            </div>
            ${p.greeting_style ? `<div class="tone-row">
              <span class="tone-row-label">Greeting</span>
              <span class="tone-italic">"${escHtml(p.greeting_style)}"</span></div>` : ''}
            ${p.sign_off_style ? `<div class="tone-row">
              <span class="tone-row-label">Sign-off</span>
              <span class="tone-italic">"${escHtml(p.sign_off_style)}"</span></div>` : ''}
          </div>`;
      }).join('')}
    </div>`;
  } catch (err) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon" style="color:var(--danger);">✕</div>
      <p style="color:var(--danger);">${escHtml(err.message)}</p></div>`;
  }
}

// ── Audit Log ────────────────────────────────────────────────

async function loadAuditEventTypes() {
  try {
    const data = await api('GET', '/audit/event-types');
    const sel  = document.getElementById('audit-event-filter');
    (data.event_types || []).forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

async function loadAuditLog() {
  const sessionFilter = document.getElementById('audit-session-filter').value.trim();
  const eventFilter   = document.getElementById('audit-event-filter').value;
  const timeline      = document.getElementById('audit-timeline');
  timeline.innerHTML  = `<div class="empty-state" style="padding:24px 0;">
    <div class="empty-icon"><span class="spinner"></span></div>
    <p>Loading…</p></div>`;

  let url = '/audit/logs?limit=100';
  if (sessionFilter) url += `&session_id=${encodeURIComponent(sessionFilter)}`;
  if (eventFilter)   url += `&event_type=${encodeURIComponent(eventFilter)}`;

  try {
    const entries = await api('GET', url);
    if (!entries.length) {
      timeline.innerHTML = `<div class="empty-state" style="padding:24px 0;">
        <div class="empty-icon">◉</div>
        <p>No audit events found.</p></div>`;
      return;
    }

    const dotClass = (type) => {
      if (['EMAIL_SENT','PERMISSION_GRANTED'].includes(type))          return 'dot-success';
      if (['AUTH_FAILED','PROMPT_INJECTION_DETECTED','EMAIL_DELETED'].includes(type)) return 'dot-danger';
      if (['SESSION_EXPIRED','APPROVAL_GATE_PRESENTED','SCHEDULED_DRAFT_CANCELLED'].includes(type)) return 'dot-warning';
      if (['DRAFT_CREATED','SCHEDULED_DRAFT_REGISTERED'].includes(type)) return 'dot-info';
      if (['SESSION_STARTED'].includes(type))                           return 'dot-accent';
      return '';
    };

    const iconMap = {
      EMAIL_SENT:                 '✉',
      DRAFT_CREATED:              '✦',
      SESSION_STARTED:            '◉',
      SESSION_EXPIRED:            '◌',
      AUTH_FAILED:                '✕',
      PROMPT_INJECTION_DETECTED:  '⚠',
      APPROVAL_GATE_PRESENTED:    '⚑',
      SCHEDULED_DRAFT_REGISTERED: '◷',
      SCHEDULED_DRAFT_CANCELLED:  '✖',
      EMAIL_DELETED:              '🗑',
      PERMISSION_GRANTED:         '✓',
      PERMISSION_REVOKED:         '⊘',
    };

    timeline.innerHTML = entries.map(e => `
      <div class="audit-event">
        <div class="audit-event-dot ${dotClass(e.event_type)}"></div>
        <div class="audit-event-card">
          <div class="audit-event-icon">${iconMap[e.event_type] || '◈'}</div>
          <div class="audit-event-body">
            <div class="audit-event-desc">${escHtml(e.description)}</div>
            <div class="audit-event-meta">
              ${eventTypeBadge(e.event_type)}
              <span class="audit-event-session">${escHtml(e.session_id.substring(0,16))}…</span>
              <span class="audit-event-time">${formatTime(e.timestamp)}</span>
            </div>
          </div>
        </div>
      </div>`).join('');
  } catch (err) {
    timeline.innerHTML = `<div class="empty-state" style="padding:24px 0;">
      <div class="empty-icon" style="color:var(--danger);">✕</div>
      <p style="color:var(--danger);">${escHtml(err.message)}</p></div>`;
  }
}

// ── Helpers ──────────────────────────────────────────────────

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

function eventTypeBadge(type) {
  const map = {
    EMAIL_SENT:                  'badge-success',
    DRAFT_CREATED:               'badge-accent',
    SESSION_STARTED:             'badge-info',
    SESSION_EXPIRED:             'badge-warning',
    AUTH_FAILED:                 'badge-danger',
    PROMPT_INJECTION_DETECTED:   'badge-danger',
    PERMISSION_GRANTED:          'badge-success',
    PERMISSION_REVOKED:          'badge-warning',
    EMAIL_DELETED:               'badge-danger',
    APPROVAL_GATE_PRESENTED:     'badge-warning',
    SCHEDULED_DRAFT_REGISTERED:  'badge-info',
    SCHEDULED_DRAFT_CANCELLED:   'badge-muted',
  };
  const cls = map[type] || 'badge-muted';
  return `<span class="badge ${cls}">${escHtml(type)}</span>`;
}

function scheduledStatusBadge(status) {
  const map = {
    pending:                'badge-info',
    awaiting_confirmation:  'badge-warning',
    sent:                   'badge-success',
    cancelled:              'badge-muted',
    held:                   'badge-warning',
  };
  return `<span class="badge ${map[status] || 'badge-muted'}">${escHtml(status)}</span>`;
}

function formalityBadge(level) {
  const levels = { very_formal: 5, formal: 4, neutral: 3, informal: 2, casual: 1 };
  const filled = levels[level] || 3;
  const dots   = Array.from({ length: 5 }, (_, i) =>
    `<div class="formality-dot${i < filled ? ' filled' : ''}"></div>`
  ).join('');
  return `<div class="formality-dots" title="${escHtml(level)}">${dots}</div>`;
}

function warmthBar(value) {
  const pct = Math.min(100, Math.round((value || 0) * 100));
  // cold=blue, warm=orange gradient
  const hue  = Math.round(200 - pct * 1.4); // 200 (blue) → 60 (orange)
  const color = `hsl(${hue}, 80%, 55%)`;
  return `<div class="warmth-bar-wrap">
    <div class="warmth-bar-track">
      <div class="warmth-bar-fill" style="width:${pct}%;background:${color};"></div>
    </div>
    <span style="font-size:11px;color:var(--text-muted);">${pct}%</span>
  </div>`;
}
