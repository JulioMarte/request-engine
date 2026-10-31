/* Personal passkey enrollment through the same-origin console. */
(function () {
  "use strict";
  function decode(value) {
    var raw = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); }).buffer;
  }
  function encode(value) {
    var bytes = new Uint8Array(value), binary = "";
    bytes.forEach(function (byte) { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  // Console errors are Spanish strings; an upstream envelope is shown generically.
  function errorText(data, fallback) {
    return data && typeof data.error === "string" ? data.error : fallback;
  }
  async function post(path, body) {
    var response = await fetch(path, {
      method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.assign({csrf_token: document.body.dataset.csrf}, body)),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(errorText(data, "No se pudo registrar la llave de acceso. Intente de nuevo."));
    return data;
  }
  document.addEventListener("submit", async function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("form[data-private-post]")) return;
    event.preventDefault();
    if (form.dataset.submitting === "true") return;
    var confirmation = form.getAttribute("data-confirm");
    if (confirmation && !window.confirm(confirmation)) return;
    var submitButton = form.querySelector("button[type=submit]");
    var status = form.querySelector("[data-private-post-status]");
    form.dataset.submitting = "true";
    if (submitButton) submitButton.disabled = true;
    if (status) status.textContent = "Procesando…";
    var privateBody = new FormData(form);
    form.querySelectorAll('input[type="password"]').forEach(function (input) { input.value = ""; });
    try {
      var response = await fetch(form.action, {method: "POST", body: privateBody, credentials: "same-origin", headers: {"X-Requested-With": "fetch"}});
      if ((response.headers.get("content-type") || "").includes("application/json")) {
        var data = await response.json();
        throw new Error(errorText(data, "No se pudo confirmar el resultado. Recargue la página antes de intentarlo de nuevo."));
      }
      var html = await response.text();
      // Keep the current GET address: refresh never repeats the secret-consuming POST.
      document.open();
      document.write(html);
      document.close();
    } catch (error) {
      form.dataset.submitting = "false";
      if (submitButton) submitButton.disabled = false;
      if (status) status.textContent = String(error.message || error);
    }
  });
  // Private forms cannot submit natively before the fetch handler is installed.
  document.querySelectorAll("form[data-private-post] button[type=submit]").forEach(function (button) {
    button.disabled = false;
  });
  var button = document.getElementById("account-passkey-register");
  if (!button) return;
  button.addEventListener("click", async function () {
    var status = document.getElementById("account-passkey-status");
    button.disabled = true;
    try {
      status.textContent = "Esperando su llave de acceso…";
      var data = await post("/account/security/passkey/options", {});
      var options = data.public_key;
      options.challenge = decode(options.challenge);
      options.user.id = decode(options.user.id);
      options.excludeCredentials = (options.excludeCredentials || []).map(function (item) {
        return Object.assign({}, item, {id: decode(item.id)});
      });
      var credential = await navigator.credentials.create({publicKey: options});
      if (!credential) throw new Error("Se canceló el registro de la llave de acceso.");
      var response = credential.response;
      await post("/account/security/passkey/complete", {credential: {
        id: credential.id, rawId: encode(credential.rawId), type: credential.type,
        response: {clientDataJSON: encode(response.clientDataJSON),
          attestationObject: encode(response.attestationObject),
          transports: response.getTransports ? response.getTransports() : []},
        clientExtensionResults: credential.getClientExtensionResults(),
      }});
      window.location.assign("/account/security");
    } catch (error) {
      status.textContent = error.name === "NotAllowedError" ? "Se canceló el registro de la llave de acceso. Intente de nuevo cuando esté listo." : String(error.message || error);
      button.disabled = false;
    }
  });
})();
