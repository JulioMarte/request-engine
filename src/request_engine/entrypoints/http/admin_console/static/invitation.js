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
  let reviewedToken = null;
  async function reviewInvitation() {
    if (!form || !token) return;
    const candidate = token;
    form.elements.token.value = candidate;
    form.querySelector('button').disabled = true;
    message.textContent = 'Checking the organization and invitation expiry…';
    try {
      const response = await fetch('/staff-invitations/preview', {
        method: 'POST', body: new FormData(form), credentials: 'same-origin'
      });
      const result = await response.json();
      // Forgetting a link while its preview is in flight must not restore it.
      if (token !== candidate) return;
      if (!response.ok || !result.ok) {
        message.textContent = result.error || 'Could not verify this invitation.';
        return;
      }
      const expires = new Date(result.expires_at);
      if (typeof result.organization_display_name !== 'string' || !Number.isFinite(expires.getTime())) {
        message.textContent = 'Invitation details are incomplete. Ask for a new link.';
        return;
      }
      document.getElementById('invitation-organization').textContent = result.organization_display_name;
      const expiry = document.getElementById('invitation-expiry');
      expiry.textContent = expires.toLocaleString(); expiry.dateTime = result.expires_at;
      document.getElementById('invitation-preview').hidden = false;
      reviewedToken = candidate;
      message.textContent = 'Review the organization below before accepting. Acceptance rechecks the invitation.';
      form.querySelector('button').disabled = false;
    } catch (_) {
      if (token === candidate) message.textContent = 'Could not verify the invitation. Reload to retry.';
    }
  }
  if (token) {
    message.textContent = 'Invitation loaded. Sign in with your own account before accepting.';
    if (form) reviewInvitation();
  } else message.textContent = 'No invitation loaded. Open the link from your invitation email.';
  document.getElementById('invitation-cancel').addEventListener('click', () => {
    try { sessionStorage.removeItem(key); } catch (_) {}
    if (form) { form.elements.token.value = ''; form.querySelector('button').disabled = true; }
    token = null; reviewedToken = null;
    document.getElementById('invitation-preview').hidden = true;
    message.textContent = 'Invitation forgotten on this tab.';
  });
  if (form) form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!token || reviewedToken !== token) return;
    const button = form.querySelector('button'); button.disabled = true;
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
