// JavaScript interaction proof, not browser/WebAuthn/provider certification.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(resolve(__dirname, '../../../src/request_engine/entrypoints/http/admin_console/static/invitation.js'), 'utf8');

function world() {
  const elements = {};
  for (const id of ['invitation-accept', 'invitation-message', 'invitation-accept-form', 'invitation-cancel', 'invitation-preview', 'invitation-organization', 'invitation-expiry']) {
    elements[id] = {hidden: id === 'invitation-preview', textContent: '', listeners: {}, addEventListener(event, fn) {this.listeners[event] = fn;}};
  }
  const button = {disabled: true};
  const form = elements['invitation-accept-form'];
  form.elements = {token: {value: ''}};
  form.querySelector = () => button;
  const calls = [];
  let complete;
  const pending = new Promise(resolve => {complete = resolve;});
  const stored = new Map();
  runInNewContext(source, {
    document: {getElementById: id => elements[id]},
    location: {hash: '#token=22222222-2222-4222-8222-222222222222.proof', pathname: '/staff-invitations/accept'},
    history: {replaceState() {}}, URLSearchParams, Date,
    sessionStorage: {setItem: (key, value) => stored.set(key, value), getItem: key => stored.get(key), removeItem: key => stored.delete(key)},
    FormData: class {},
    fetch: async (url, options) => {calls.push({url, options}); return pending;},
  });
  return {elements, button, calls, complete, stored};
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('accept stays disabled until a successful proof-bound preview', async () => {
  const state = world();
  assert.equal(state.button.disabled, true);
  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0].url, '/staff-invitations/preview');
  assert.equal(state.calls[0].options.method, 'POST');
  state.complete({ok: true, json: async () => ({ok: true, organization_display_name: '<img onerror=steal()>', expires_at: '2026-10-04T00:00:00Z'})});
  await flush();
  assert.equal(state.button.disabled, false);
  assert.equal(state.elements['invitation-preview'].hidden, false);
  // Untrusted names are assigned as text, not executable markup.
  assert.equal(state.elements['invitation-organization'].textContent, '<img onerror=steal()>');
  assert.equal(state.calls.length, 1); // Reviewing never submits acceptance.
});

test('forgetting an invitation cannot be undone by a late preview response', async () => {
  const state = world();
  state.elements['invitation-cancel'].listeners.click();
  state.complete({ok: true, json: async () => ({ok: true, organization_display_name: 'Old organization', expires_at: '2026-10-04T00:00:00Z'})});
  await flush();
  assert.equal(state.button.disabled, true);
  assert.equal(state.elements['invitation-preview'].hidden, true);
  assert.equal(state.elements['invitation-accept-form'].elements.token.value, '');
  assert.equal(state.stored.size, 0);
});

test('a failed preview does not enable acceptance or show an organization', async () => {
  const state = world();
  state.complete({ok: false, json: async () => ({error: 'Invitation unavailable'})});
  await flush();
  assert.equal(state.button.disabled, true);
  assert.equal(state.elements['invitation-preview'].hidden, true);
  assert.equal(state.elements['invitation-message'].textContent, 'Invitation unavailable');
});
