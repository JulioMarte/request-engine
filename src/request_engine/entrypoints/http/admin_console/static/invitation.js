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
  } catch (_) { message.textContent = 'No se pudo guardar la invitación en este navegador. Vuelva a abrir el enlace original después de iniciar sesión.'; }
  const form = document.getElementById('invitation-accept-form');
  let reviewedToken = null;
  async function reviewInvitation() {
    if (!form || !token) return;
    const candidate = token;
    form.elements.token.value = candidate;
    form.querySelector('button').disabled = true;
    message.textContent = 'Verificando el negocio y la fecha de vencimiento de la invitación…';
    try {
      const response = await fetch('/staff-invitations/preview', {
        method: 'POST', body: new FormData(form), credentials: 'same-origin'
      });
      const result = await response.json();
      // Forgetting a link while its preview is in flight must not restore it.
      if (token !== candidate) return;
      if (!response.ok || !result.ok) {
        message.textContent = result.error || 'No se pudo verificar esta invitación.';
        return;
      }
      const expires = new Date(result.expires_at);
      if (typeof result.organization_display_name !== 'string' || !Number.isFinite(expires.getTime())) {
        message.textContent = 'Los datos de la invitación están incompletos. Pida un enlace nuevo.';
        return;
      }
      document.getElementById('invitation-organization').textContent = result.organization_display_name;
      const expiry = document.getElementById('invitation-expiry');
      expiry.textContent = expires.toLocaleString(); expiry.dateTime = result.expires_at;
      document.getElementById('invitation-preview').hidden = false;
      reviewedToken = candidate;
      message.textContent = 'Revise el negocio que aparece abajo antes de aceptar. Al aceptar, se vuelve a verificar la invitación.';
      form.querySelector('button').disabled = false;
    } catch (_) {
      if (token === candidate) message.textContent = 'No se pudo verificar la invitación. Recargue la página para intentarlo de nuevo.';
    }
  }
  if (token) {
    message.textContent = 'Invitación cargada. Inicie sesión con su propia cuenta antes de aceptar.';
    if (form) reviewInvitation();
  } else message.textContent = 'No hay ninguna invitación cargada. Abra el enlace del correo de invitación.';
  document.getElementById('invitation-cancel').addEventListener('click', () => {
    try { sessionStorage.removeItem(key); } catch (_) {}
    if (form) { form.elements.token.value = ''; form.querySelector('button').disabled = true; }
    token = null; reviewedToken = null;
    document.getElementById('invitation-preview').hidden = true;
    message.textContent = 'Se olvidó la invitación en esta pestaña.';
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
        message.textContent = 'Ya forma parte del negocio. No se le dieron permisos de administrador. Pida a su administrador que revise su acceso.';
        const link = document.createElement('a');
        link.href = '/my-organizations'; link.className = 'button secondary';
        link.textContent = 'Ver mis negocios'; root.appendChild(link); return;
      }
      message.textContent = result.error || 'No se pudo aceptar la invitación.';
    } catch (_) { message.textContent = 'No se confirmó el resultado. Vuelva a intentarlo con esta misma invitación.'; }
    button.disabled = false;
  });
})();
