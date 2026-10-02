(() => {
  const root = document.getElementById('invitation-accept');
  if (!root) return;
  const key = 'request-engine.staff-invitation';
  const message = document.getElementById('invitation-message');
  const fragment = new URLSearchParams(location.hash.slice(1));
  let token = fragment.get('token');
  history.replaceState(null, '', location.pathname);
  try {
    if (token) sessionStorage.setItem(key, JSON.stringify({token, storedAt: Date.now()}));
    else {
      const stored = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (stored && Date.now() - stored.storedAt < 30 * 60 * 1000) token = stored.token;
      else sessionStorage.removeItem(key);
    }
  } catch (_) { message.textContent = 'Storage is unavailable. Reopen the original invitation after signing in.'; }
  const form = document.getElementById('invitation-accept-form');
  if (token) {
    message.textContent = 'Invitation loaded. Sign in with your own account before accepting.';
    if (form) { form.elements.token.value = token; form.querySelector('button').disabled = false; }
  } else message.textContent = 'No invitation loaded. Open the link from your invitation email.';
  document.getElementById('invitation-cancel').addEventListener('click', () => {
    try { sessionStorage.removeItem(key); } catch (_) {}
    if (form) { form.elements.token.value = ''; form.querySelector('button').disabled = true; }
    token = null; message.textContent = 'Invitation forgotten on this tab.';
  });
  if (form) form.addEventListener('submit', async (event) => {
    event.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
      const result = await response.json();
      if (response.ok && result.ok) {
        try { sessionStorage.removeItem(key); } catch (_) {}
        token = null; form.elements.token.value = ''; form.hidden = true;
        document.getElementById('invitation-cancel').hidden = true;
        message.textContent = 'You joined the organization. No administrator permissions were granted. Ask your administrator to review your access.';
        const link = document.createElement('a');
        link.href = '/my-organizations'; link.className = 'button secondary';
        link.textContent = 'View my organizations'; root.appendChild(link); return;
      }
      message.textContent = result.error || 'Invitation could not be accepted.';
    } catch (_) { message.textContent = 'Result not confirmed. Retry this same invitation.'; }
    button.disabled = false;
  });
})();
