/* Service worker. Content scripts are still bound by the page's CORS rules, and
   a page on espn.com cannot reach a local HTTP server at all. The service
   worker can, because host_permissions grants it 127.0.0.1:8787 directly --
   which is why the extension needs no sink window. */
const HELPER = 'http://127.0.0.1:8787/api/ingest';

async function send(rows, draftId, diag) {
  const r = await fetch(HELPER, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draftId: draftId || '', picks: rows, diag: diag || null })
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function badge(text, color) {
  chrome.action.setBadgeText({ text: text });
  chrome.action.setBadgeBackgroundColor({ color: color });
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.type !== 'ff-picks') return;
  send(msg.picks || [], msg.draftId, msg.diag)
    .then(res => {
      badge(String(res.total || 0), '#0a7d33');
      reply({ ok: true, total: res.total, added: res.added });
    })
    .catch(err => {
      badge('!', '#cc0000');
      // The helper is unreachable, so this cannot be logged there. Keep it here
      // -- chrome://extensions -> service worker -> Console has the trail.
      console.warn('[FF Research] helper unreachable:', String(err.message || err),
                   'picks queued:', (msg.picks || []).length);
      reply({ ok: false, error: String(err.message || err) });
    });
  return true;                       // keep the channel open for the async reply
});
