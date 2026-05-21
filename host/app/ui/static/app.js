const stateEl = document.querySelector('#state');
const eventsEl = document.querySelector('#events');
const hardwareLog = document.querySelector('#hardware-log');
const statusEl = document.querySelector('#connection-status');

async function refreshState() {
  const res = await fetch('/api/state');
  const json = await res.json();
  stateEl.textContent = JSON.stringify(json, null, 2);
}

function appendEvent(obj) {
  eventsEl.textContent = `${JSON.stringify(obj, null, 2)}\n\n${eventsEl.textContent}`.slice(0, 8000);
}

document.querySelector('#new-game').addEventListener('click', async () => {
  await fetch('/api/game/new', { method: 'POST' });
  await refreshState();
});

document.querySelector('#send-move').addEventListener('click', async () => {
  const uci = document.querySelector('#uci').value.trim();
  const res = await fetch('/api/move/human', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uci })
  });
  const json = await res.json();
  if (!res.ok) alert(json.detail || 'Move failed');
  await refreshState();
});

document.querySelectorAll('[data-action]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const res = await fetch(btn.dataset.action, { method: 'POST' });
    const json = await res.json();
    hardwareLog.textContent = JSON.stringify(json, null, 2);
    await refreshState();
  });
});

const wsProtocol = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${wsProtocol}://${location.host}/ws`);
ws.onopen = () => { statusEl.textContent = 'Live'; };
ws.onclose = () => { statusEl.textContent = 'Disconnected'; };
ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);
  appendEvent(event);
  refreshState();
};

refreshState();
