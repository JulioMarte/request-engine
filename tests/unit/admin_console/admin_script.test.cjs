// Executes the shipped UI script. DOM doubles do not certify a browser or APIs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(resolve(__dirname, '../../../src/request_engine/entrypoints/http/admin_console/static/admin.js'), 'utf8');

function world(confirm = true, next = null, passwordLogin = {}) {
  const events = {};
  const classes = new Set();
  const document = {
    body: {dataset: {csrf: 'csrf'}, classList: {
      toggle(name, enabled) {if (enabled) classes.add(name); else classes.delete(name);},
      contains(name) {return classes.has(name);},
    }},
    documentElement: {classList: {add() {}}},
    activeElement: null,
    addEventListener(name, fn) {(events[name] ||= []).push(fn);},
    querySelectorAll() {return [];},
    querySelector() {return null;},
    getElementById() {return null;},
  };
  class Element {
    constructor(kind) {this.kind = kind; this.disabled = false; this.attributes = new Map(); this.classList = {contains() {return false;}};}
    focus() {document.activeElement = this;}
    setAttribute(name, value) {this.attributes.set(name, value);}
    removeAttribute(name) {this.attributes.delete(name);}
    getAttribute(name) {return this.attributes.get(name);}
    matches(selector) {return (selector === 'form[data-password-login]' && this.passwordLogin === true) || (selector === 'form[data-password-step-up]' && this.passwordStepUp === true) || (selector === 'form[data-password-recovery-complete]' && this.passwordRecovery === true) || (selector === 'form[data-session-logout]' && this.sessionLogout === true);}
    closest(selector) {
      if (selector === 'form') return this.form || null;
      return selector === this.kind ? this : null;
    }
  }
  const first = new Element('a');
  const last = new Element('a');
  const sidebar = new Element('#admin-sidebar');
  sidebar.querySelector = () => first;
  sidebar.querySelectorAll = () => [first, last];
  const toggle = new Element('.menu-toggle');
  const scrim = new Element('.nav-scrim');
  const frame = new Element('#admin-frame');
  let mobile = true;
  const dialogs = [];
  const windowEvents = {};
  const window = {
    matchMedia: () => ({matches: mobile}),
    addEventListener(name, fn) {windowEvents[name] = fn;},
    confirm(message) {dialogs.push(message); return confirm;},
    crypto: {randomUUID: () => '1111-2222'},
    location: {href: "", assign(url) {this.href = url;}},
  };
  document.getElementById = id => ({'admin-sidebar': sidebar, 'admin-frame': frame}[id] || null);
  document.querySelector = selector => selector === 'input[name="next"]' && next !== null ? {value: next} : ({'.menu-toggle': toggle, '.nav-scrim': scrim}[selector] || null);
  const calls = [];
  const written = [];
  document.open = () => written.push('open');
  document.write = html => written.push(html);
  document.close = () => written.push('close');
  class FormDataDouble {
    constructor(form) {this.entries = new Map(form.fields || []);}
    get(name) {return this.entries.get(name);}
  }
  const credential = {id: "fixture", type: "public-key", rawId: new ArrayBuffer(0),
    response: {clientDataJSON: new ArrayBuffer(0), authenticatorData: new ArrayBuffer(0), signature: new ArrayBuffer(0), userHandle: null}};
  runInNewContext(source, {document, window, Element, HTMLFormElement: Element, HTMLInputElement: Element, FormData: FormDataDouble, Array, Date, Math, btoa, atob,
    navigator: {credentials: {get: async () => credential}},
    fetch: async (url, options) => {calls.push({url, options}); if (passwordLogin.fetch) return passwordLogin.fetch(url, options); return {ok: true, json: async () => ({public_key: {challenge: "", allowCredentials: []}})};},
  });
  function emit(name, data = {}) {(events[name] || []).forEach(fn => fn(data));}
  emit('DOMContentLoaded');
  return {emit, first, last, sidebar, toggle, scrim, frame, document, dialogs, Element, window, calls, written,
    desktop() {mobile = false; windowEvents.resize();}};
}

test('mobile navigation makes only the drawer accessible and returns focus on Escape', () => {
  const s = world();
  assert.equal(s.sidebar.inert, true);
  assert.equal(s.frame.inert, false);
  s.emit('click', {target: s.toggle});
  assert.equal(s.sidebar.inert, false);
  assert.equal(s.frame.inert, true);
  assert.equal(s.sidebar.getAttribute('aria-modal'), 'true');
  assert.equal(s.toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(s.document.activeElement, s.first);
  let prevented = false;
  s.emit('keydown', {key: 'Escape', preventDefault() {prevented = true;}});
  assert.equal(prevented, true);
  assert.equal(s.frame.inert, false);
  assert.equal(s.sidebar.inert, true);
  assert.equal(s.document.activeElement, s.toggle);
});

test('Tab and Shift+Tab wrap between drawer links and close control', () => {
  const s = world();
  s.emit('click', {target: s.toggle});
  s.scrim.focus();
  let prevented = 0;
  s.emit('keydown', {key: 'Tab', preventDefault() {prevented++;}});
  assert.equal(s.document.activeElement, s.first);
  s.emit('keydown', {key: 'Tab', shiftKey: true, preventDefault() {prevented++;}});
  assert.equal(s.document.activeElement, s.scrim);
  assert.equal(prevented, 2);
});

test('desktop resize removes modal and inert state', () => {
  const s = world();
  s.emit('click', {target: s.toggle});
  s.desktop();
  assert.equal(s.sidebar.inert, false);
  assert.equal(s.frame.inert, false);
  assert.equal(s.sidebar.getAttribute('role'), undefined);
  assert.equal(s.sidebar.getAttribute('aria-modal'), undefined);
  assert.equal(s.toggle.getAttribute('aria-expanded'), 'false');
});

test('confirmation falls back to an actual confirmation when dialog is unsupported', () => {
  const s = world();
  const element = new s.Element();
  element.setAttribute('data-confirm', 'Revoke this binding?');
  let issued = 0;
  s.emit('htmx:confirm', {detail: {elt: element, issueRequest(value) {if (value) issued++;}}, preventDefault() {}});
  assert.equal(s.dialogs.length, 1);
  assert.equal(s.dialogs[0], 'Revoke this binding?');
  assert.equal(issued, 1);
});

for (const finish of ['htmx:afterRequest', 'htmx:sendError', 'htmx:timeout']) {
  test(`request state restores enabled buttons after ${finish}`, () => {
    const s = world();
    const form = new s.Element('form');
    const submit = new s.Element('button');
    const unavailable = new s.Element('button');
    unavailable.disabled = true;
    form.querySelectorAll = selector => selector === 'button[type=submit]' ? [submit, unavailable] : [submit].filter(button => button.getAttribute('data-request-disabled'));
    const trigger = new s.Element('button');
    trigger.form = form;
    const detail = {elt: trigger};
    s.emit('htmx:beforeRequest', {detail});
    assert.equal(form.getAttribute('aria-busy'), 'true');
    assert.equal(submit.disabled, true);
    s.emit(finish, {detail});
    assert.equal(form.getAttribute('aria-busy'), undefined);
    assert.equal(submit.disabled, false);
    assert.equal(unavailable.disabled, true); // Cannot enable a pre-existing forbidden action.
  });
}


test('a declined fallback confirmation sends no request', () => {
  const s = world(false);
  const element = new s.Element();
  element.setAttribute('data-confirm', 'Revoke this binding?');
  let issued = 0;
  s.emit('htmx:confirm', {detail: {elt: element, issueRequest() {issued++;}}, preventDefault() {}});
  assert.equal(s.dialogs.length, 1);
  assert.equal(issued, 0);
});

test('reusing a confirmation dialog clears a previous approval before Escape', () => {
  const s = world();
  const element = new s.Element();
  element.setAttribute('data-confirm', 'Revoke this binding?');
  const listeners = new Map();
  const dialog = {open: false, returnValue: 'confirm', showModal() {this.open = true;},
    addEventListener(name, fn) {listeners.set(name, fn);},
    removeEventListener(name) {listeners.delete(name);}};
  s.document.getElementById = id => id === 'confirm-dialog' ? dialog : null;
  let issued = 0;
  s.emit('htmx:confirm', {detail: {elt: element, issueRequest() {issued++;}}, preventDefault() {}});
  assert.equal(dialog.returnValue, 'cancel');
  // Escape closes without changing returnValue. The old approval must not apply.
  dialog.open = false;
  listeners.get('close')();
  assert.equal(issued, 0);
  assert.equal(listeners.size, 0);
});


for (const next of ['/account/security', '/staff-invitations/accept', '/', 'https://foreign.test/account/security', '//foreign.test/account/security', '/account/security?next=https://foreign.test', '/account/security/other', null]) {
  test(`passkey login only redirects to accepted destinations: ${next}`, async () => {
    const s = world(true, next);
    const button = new s.Element();
    button.id = 'passkey-login-btn';
    s.emit('click', {target: button});
    await new Promise(resolve => setImmediate(resolve));
    const accepted = next === '/account/security' || next === '/staff-invitations/accept';
    assert.equal(s.window.location.href, accepted ? next : '/');
    assert.equal(s.calls.length, 2);
    assert.equal(s.calls[0].url, '/login/webauthn/options');
    assert.equal(s.calls[1].url, '/login/webauthn/complete');
  });
}

// Executes the real submit handler with transport/DOM doubles. Browser Origin,
// cookie acceptance and HTML parsing require separate browser evidence.
function passwordForm(s) {
  const form = new s.Element('form');
  form.passwordLogin = true;
  form.action = 'http://localhost:8002/login';
  const button = new s.Element('button');
  const status = {textContent: ''};
  const password = {value: 'audit-password-not-a-real-secret'};
  form.fields = [['login_handle', 'audit@example.invalid'], ['password', password.value], ['next', '/account/security']];
  form.querySelector = selector => ({'button[type=submit]': button, '[data-password-login-status]': status, 'input[name="password"]': password}[selector] || null);
  let prevented = 0;
  return {form, button, status, password, submit() {
    s.emit('submit', {target: form, preventDefault() {prevented++;}});
  }, get prevented() {return prevented;}};
}

test('password login posts credential form with same-origin cookies and follows the server redirect', async () => {
  const s = world(true, null, {fetch: async () => ({redirected: true, url: 'http://localhost:8002/account/security'})});
  const login = passwordForm(s);
  login.submit();
  assert.equal(login.prevented, 1);
  assert.equal(login.form.getAttribute('aria-busy'), 'true');
  assert.equal(login.button.disabled, true);
  assert.equal(login.status.textContent, 'Iniciando sesión…');
  assert.equal(s.calls.length, 1);
  const {url, options} = s.calls[0];
  assert.equal(url, 'http://localhost:8002/login');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.redirect, 'follow');
  assert.equal(options.body.get('login_handle'), 'audit@example.invalid');
  assert.equal(options.body.get('password'), 'audit-password-not-a-real-secret');
  assert.equal(options.body.get('next'), '/account/security');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.window.location.href, 'http://localhost:8002/account/security');
  assert.deepEqual(s.written, []);
});

test('pending password login rejects a second submit without creating another session request', async () => {
  let finish;
  const response = new Promise(resolve => {finish = resolve;});
  const s = world(true, null, {fetch: () => response});
  const login = passwordForm(s);
  login.submit();
  login.submit();
  assert.equal(login.prevented, 2);
  assert.equal(s.calls.length, 1);
  assert.equal(login.form.getAttribute('aria-busy'), 'true');
  finish({redirected: true, url: 'http://localhost:8002/'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.window.location.href, 'http://localhost:8002/');
});

test('invalid password renders the server error document without treating HTTP 401 as a transport failure', async () => {
  const html = '<!doctype html><html><body><p role="alert">Invalid login or password</p><input name="password" type="password"></body></html>';
  const s = world(true, null, {fetch: async () => ({ok: false, status: 401, redirected: false, text: async () => html})});
  const login = passwordForm(s);
  login.submit();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.written, ['open', html, 'close']);
  assert.equal(s.window.location.href, '');
  assert.equal(s.calls.length, 1);
});

test('password login network failure clears the secret, reports the error and permits a retry', async () => {
  const s = world(true, null, {fetch: async () => {throw new Error('Network unavailable');}});
  const login = passwordForm(s);
  login.submit();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(login.form.getAttribute('aria-busy'), undefined);
  assert.equal(login.button.disabled, false);
  assert.equal(login.password.value, '');
  assert.equal(login.status.textContent, 'Network unavailable');
  assert.equal(s.window.location.href, '');
  assert.deepEqual(s.written, []);
  login.submit();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls.length, 2);
});

test('ordinary form submissions keep their native behavior and do not send credentials through the login handler', () => {
  const s = world();
  const form = new s.Element('form');
  let prevented = false;
  s.emit('submit', {target: form, preventDefault() {prevented = true;}});
  assert.equal(prevented, false);
  assert.equal(s.calls.length, 0);
});

function confirmationForm(s) {
  const form = new s.Element('form');
  form.passwordStepUp = true;
  form.setAttribute('data-retry-form', 'pending-operation');
  const password = {value: 'synthetic-current-password'};
  const button = new s.Element('button');
  const status = {textContent: ''};
  const section = {querySelector: () => status};
  form.closest = selector => selector === '[data-reauthentication]' ? section : null;
  form.querySelector = selector => ({'input[name="password"]': password, 'button[type=submit]': button}[selector] || null);
  const pending = {intent: 'unchanged-intent', revision: '17', submissions: 0, requestSubmit() {this.submissions++;}};
  const originalLookup = s.document.getElementById;
  s.document.getElementById = id => id === 'pending-operation' ? pending : originalLookup(id);
  return {form, password, button, status, pending, submit() {s.emit('submit', {target: form, preventDefault() {}});}};
}

test('password confirmation uses the current session, clears the secret and retries the unchanged pending form', async () => {
  const s = world(true, null, {fetch: async () => ({ok: true, json: async () => ({ok: true})})});
  const confirmation = confirmationForm(s);
  confirmation.submit();
  assert.equal(confirmation.password.value, '');
  assert.equal(s.calls[0].url, '/step-up/password');
  assert.equal(s.calls[0].options.credentials, 'same-origin');
  assert.equal(s.calls[0].options.headers['X-CSRF-Token'], 'csrf');
  assert.deepEqual(JSON.parse(s.calls[0].options.body), {password: 'synthetic-current-password'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(confirmation.pending.submissions, 1);
  assert.equal(confirmation.pending.intent, 'unchanged-intent');
  assert.equal(confirmation.pending.revision, '17');
  assert.equal(confirmation.button.disabled, false);
  assert.equal(s.window.location.href, '');
});

test('denied password confirmation does not retry or retain a password', async () => {
  const s = world(true, null, {fetch: async () => ({ok: false, status: 401, json: async () => ({error: {code: 'credential_invalid'}})})});
  const confirmation = confirmationForm(s);
  confirmation.submit();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(confirmation.password.value, '');
  assert.equal(confirmation.pending.submissions, 0);
  assert.equal(confirmation.pending.intent, 'unchanged-intent');
  assert.equal(confirmation.status.textContent, 'No se pudo verificar la llave de acceso o la contraseña. Intente de nuevo.');
  assert.equal(confirmation.form.getAttribute('aria-busy'), undefined);
  assert.equal(confirmation.button.disabled, false);
});

test('pending password confirmation admits one request and keeps the original revision', async () => {
  let finish;
  const response = new Promise(resolve => {finish = resolve;});
  const s = world(true, null, {fetch: () => response});
  const confirmation = confirmationForm(s);
  confirmation.submit();
  confirmation.submit();
  assert.equal(s.calls.length, 1);
  assert.equal(confirmation.password.value, '');
  finish({ok: true, json: async () => ({ok: true})});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(confirmation.pending.submissions, 1);
  assert.equal(confirmation.pending.revision, '17');
});

test('password recovery completion requires a new sign-in and never retries the admin action', async () => {
  const s = world(true, null, {fetch: async () => ({ok: true, json: async () => ({ok: true, requires_sign_in: true})})});
  const confirmation = confirmationForm(s);
  confirmation.form.passwordStepUp = false;
  confirmation.form.passwordRecovery = true;
  confirmation.submit();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls[0].url, '/account/security/recovery-complete');
  assert.equal(confirmation.password.value, '');
  assert.equal(confirmation.pending.submissions, 0);
  assert.match(confirmation.status.textContent, /Cierre sesión e inicie sesión con su contraseña/);
  assert.equal(s.window.location.href, '');
});

test('sign out uses same-origin fetch and follows the owner-backed logout redirect', async () => {
  const s = world(true, null, {fetch: async () => ({redirected: true, url: 'http://localhost:8002/login'})});
  const form = new s.Element('form');
  form.sessionLogout = true;
  form.action = 'http://localhost:8002/logout';
  const button = new s.Element('button');
  form.querySelector = selector => selector === 'button[type=submit]' ? button : null;
  s.emit('submit', {target: form, preventDefault() {}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls.length, 1);
  assert.equal(s.calls[0].url, 'http://localhost:8002/logout');
  assert.equal(s.calls[0].options.credentials, 'same-origin');
  assert.equal(s.window.location.href, 'http://localhost:8002/login');
});
