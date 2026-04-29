import { state } from '../state.js';

let body = null;
let renderedCount = 0;

export function initAgentLog() {
  body = document.querySelector('#agent-log .panel-body');

  state.on('agentLog', () => {
    body.innerHTML = '';
    renderedCount = 0;
    const log = state.get('agentLog');
    const count = state.get('mode') === 'live'
      ? log?.entries?.length || 0
      : state.get('visibleLogCount') || 0;
    if (count > 0) {
      renderUpTo(count);
    } else {
      showEmptyState();
    }
  });

  state.on('visibleLogCount', (count) => {
    if (count <= 0) {
      body.innerHTML = '';
      renderedCount = 0;
      showEmptyState();
      body.scrollTop = 0;
      return;
    }
    renderUpTo(count);
  });
}

function showEmptyState() {
  if (body.querySelector('.empty-state')) return;
  body.innerHTML = '<div class="empty-state"><div class="icon">\u{1F4CB}</div>Select a scenario and press Play</div>';
}

function renderUpTo(count) {
  const log = state.get('agentLog');
  if (!log) return;

  // Remove empty state if present
  const empty = body.querySelector('.empty-state');
  if (empty) empty.remove();

  // Append any entries that haven't been rendered yet
  while (renderedCount < count && renderedCount < log.entries.length) {
    const entry = log.entries[renderedCount];
    const el = createEntryElement(entry, renderedCount);
    body.appendChild(el);
    renderedCount++;
  }

  // Auto-scroll to bottom
  body.scrollTop = body.scrollHeight;
}

function createEntryElement(entry, index) {
  const el = document.createElement('div');
  el.className = `log-entry ${entry.type}`;
  el.dataset.index = index;

  // Add channel class (telegram, etc.)
  if (entry.channel) {
    el.classList.add(entry.channel);
  }

  // Add tool data attribute for CSS targeting
  if (entry.tool) {
    el.dataset.tool = entry.tool;
  }

  if (entry.type === 'tool_result' && entry.result && !entry.result.success) {
    el.classList.add('failed');
  }

  const label = document.createElement('div');
  label.className = 'label';

  const content = document.createElement('div');
  content.className = 'log-entry-content';

  switch (entry.type) {
    case 'inbound':
      content.classList.add('content-inbound');
      label.innerHTML = formatInboundLabel(entry);
      renderTelegramMessage(content, entry, 'incoming');
      break;
    case 'tool_call':
      content.classList.add('content-tool-call');
      label.innerHTML = formatToolCallLabel(entry);
      content.textContent = JSON.stringify(entry.arguments, null, 2);
      break;
    case 'tool_result':
      content.classList.add('content-tool-result');
      label.innerHTML = formatToolResultLabel(entry);
      renderToolResult(content, entry);
      break;
    case 'outbound':
      content.classList.add('content-outbound');
      label.innerHTML = formatOutboundLabel(entry);
      renderTelegramReply(content, entry);
      break;
  }

  el.appendChild(label);
  el.appendChild(content);
  return el;
}

function formatInboundLabel(entry) {
  if (entry.channel === 'telegram') {
    return '<span class="channel-icon">\u{1F4E9}</span> Telegram Message';
  }
  return '\u25B6 User Message';
}

function formatOutboundLabel(entry) {
  if (entry.channel === 'telegram') {
    return '<span class="channel-icon">\u{1F4E4}</span> Telegram Reply';
  }
  return '\u25C0 Agent Response';
}

function formatToolCallLabel(entry) {
  const tool = entry.tool || '';
  const icons = {
    web_search: '\u{1F50D}',
    send_message: '\u{1F4AC}',
    gui_task: '\u25B6',
  };
  const icon = icons[tool] || '\u25B6';
  return `${icon} Tool Call: ${tool}`;
}

function formatToolResultLabel(entry) {
  const tool = entry.tool || '';
  const icons = {
    web_search: '\u{1F50D}',
    send_message: '\u{1F4AC}',
    gui_task: '\u25C0',
  };
  const icon = icons[tool] || '\u25C0';
  return `${icon} Tool Result: ${tool}`;
}

function renderToolResult(content, entry) {
  const r = entry.result || {};
  const statusColor = r.success ? 'var(--accent-green)' : 'var(--accent-red)';
  const statusText = r.success ? 'Success' : 'Failed';

  let html = `<span style="color:${statusColor}">${statusText}</span>`;
  if (r.steps_taken != null) {
    html += ` &mdash; ${r.steps_taken} steps`;
  }
  if (r.summary) {
    html += `<br/>${r.summary}`;
  }
  content.innerHTML = html;
}

function renderTelegramReply(content, entry) {
  if (entry.channel !== 'telegram') {
    content.textContent = entry.content;
    return;
  }

  const bubble = document.createElement('div');
  bubble.className = 'telegram-reply-bubble';

  const lines = String(entry.content || '').split('\n');
  let listEl = null;

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      listEl = null;
      const spacer = document.createElement('div');
      spacer.className = 'telegram-reply-spacer';
      bubble.appendChild(spacer);
      continue;
    }

    if (trimmed.startsWith('•')) {
      if (!listEl) {
        listEl = document.createElement('div');
        listEl.className = 'telegram-reply-list';
        bubble.appendChild(listEl);
      }
      const item = document.createElement('div');
      item.className = 'telegram-reply-item';

      const bullet = document.createElement('span');
      bullet.className = 'telegram-reply-bullet';
      bullet.textContent = '•';

      const text = document.createElement('span');
      text.className = 'telegram-reply-item-text';
      text.textContent = trimmed.slice(1).trim();

      item.append(bullet, text);
      listEl.appendChild(item);
      continue;
    }

    listEl = null;
    const paragraph = document.createElement('div');
    paragraph.className = 'telegram-reply-paragraph';
    paragraph.textContent = line;
    bubble.appendChild(paragraph);
  }

  content.replaceChildren(bubble);
}

function renderTelegramMessage(content, entry, variant = 'incoming') {
  if (entry.channel !== 'telegram') {
    content.textContent = entry.content;
    return;
  }

  const bubble = document.createElement('div');
  bubble.className = `telegram-message-bubble ${variant}`;

  const text = document.createElement('div');
  text.className = 'telegram-message-text';
  text.textContent = String(entry.content || '');

  bubble.appendChild(text);
  content.replaceChildren(bubble);
}
