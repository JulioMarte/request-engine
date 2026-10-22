const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.resolve(__dirname, "../../../src/request_engine/entrypoints/http/admin_console/static/account-security.js"), "utf8");

function world({confirmation = true, registration = false, networkFailure = false} = {}) {
  const listeners = {}, calls = [], writes = [], locations = [];
  const secret = {value: "private-input-secret"};
  const status = {textContent: ""}, button = {disabled: false, addEventListener(name, callback) { listeners[name] = callback; }};
  class Form {
    constructor() { this.dataset = {}; this.action = "http://console/account/security/recovery-codes"; }
    matches(value) { return value === "form[data-private-post]"; }
    getAttribute() { return "Replace offline recovery codes?"; }
    querySelectorAll() { return [secret]; }
    querySelector(selector) { return selector.includes("button") ? button : status; }
  }
  const document = {
    body: {dataset: {csrf: "private-csrf"}},
    addEventListener(name, callback) { listeners[name] = callback; },
    querySelectorAll() { return [button]; },
    getElementById(id) { return id === "account-passkey-register" ? (registration ? button : null) : status; },
    open() {}, write(html) { writes.push(html); }, close() {},
  };
  const context = {document, HTMLFormElement: Form, FormData: class {},
    window: {confirm() { return confirmation; }, location: {assign(value) { locations.push(value); }}},
    fetch: async (url, options) => {
      calls.push({url, options});
      if (networkFailure) throw new Error("network unavailable");
      return {ok: true, headers: {get() { return "text/html"; }}, text: async () => "<p>one-time response</p>",
        json: async () => ({public_key: {challenge: "Y2hhbGxlbmdl", user: {id: "dXNlcg"}}})};
    },
    navigator: {credentials: {create: async () => { const error = new Error("user canceled"); error.name = "NotAllowedError"; throw error; }}},
    atob: value => Buffer.from(value, "base64").toString("binary"), btoa: value => Buffer.from(value, "binary").toString("base64"),
  };
  vm.runInNewContext(source, context);
  return {listeners, calls, writes, locations, status, button, Form, secret};
}

test("canceling offline-code replacement sends no request", async () => {
  const env = world({confirmation: false});
  let prevented = false;
  await env.listeners.submit({target: new env.Form(), preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(env.calls.length, 0);
  assert.equal(env.writes.length, 0);
});

test("secret-consuming POST uses fetch and preserves the GET address", async () => {
  const env = world();
  const form = new env.Form();
  await env.listeners.submit({target: form, preventDefault() {}});
  assert.equal(env.calls.length, 1);
  assert.equal(env.calls[0].options.method, "POST");
  assert.equal(env.calls[0].options.credentials, "same-origin");
  assert.equal(env.writes.length, 1);
  assert.equal(env.locations.length, 0);
  await env.listeners.submit({target: form, preventDefault() {}});
  assert.equal(env.calls.length, 1, "a duplicate in-flight submission cannot replace codes again");
});

test("canceling a passkey prompt in the script harness never completes registration", async () => {
  const env = world({registration: true});
  await env.listeners.click();
  assert.equal(env.calls.length, 1);
  assert.equal(env.calls[0].url, "/account/security/passkey/options");
  assert.equal(env.button.disabled, false);
  assert.match(env.status.textContent, /Se canceló el registro de la llave de acceso/);
  assert.equal(env.locations.length, 0);
});


test("failed private submission clears secret inputs before the network result", async () => {
  const env = world({networkFailure: true});
  await env.listeners.submit({target: new env.Form(), preventDefault() {}});
  assert.equal(env.secret.value, "");
  assert.equal(env.button.disabled, false);
  assert.equal(env.writes.length, 0);
  assert.match(env.status.textContent, /network unavailable/);
});
