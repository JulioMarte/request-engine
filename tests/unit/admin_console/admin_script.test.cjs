// Executes the shipped UI script. DOM doubles do not certify a browser or APIs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(resolve(__dirname, '../../../src/request_engine/entrypoints/http/admin_console/static/admin.js'), 'utf8');

function world(confirm = true, next = null) {
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
    location: {href: ""},
  };
  document.getElementById = id => ({'admin-sidebar': sidebar, 'admin-frame': frame}[id] || null);
  document.querySelector = selector => selector === 'input[name="next"]' && next !== null ? {value: next} : ({'.menu-toggle': toggle, '.nav-scrim': scrim}[selector] || null);
  const calls = [];
  const credential = {id: "fixture", type: "public-key", rawId: new ArrayBuffer(0),
    response: {clientDataJSON: new ArrayBuffer(0), authenticatorData: new ArrayBuffer(0), signature: new ArrayBuffer(0), userHandle: null}};
  runInNewContext(source, {document, window, Element, HTMLFormElement: Element, HTMLInputElement: Element, Array, Date, Math, btoa, atob,
    navigator: {credentials: {get: async () => credential}},
    fetch: async (url, options) => {calls.push({url, options}); return {ok: true, json: async () => ({public_key: {challenge: "", allowCredentials: []}})};},
  });
  function emit(name, data = {}) {(events[name] || []).forEach(fn => fn(data));}
  emit('DOMContentLoaded');
  return {emit, first, last, sidebar, toggle, scrim, frame, document, dialogs, Element, window, calls,
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
