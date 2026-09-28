/* Request Engine admin console browser helpers: WebAuthn ceremonies + HTMX CSRF.
   No inline script is used; the CSP allows only this same-origin file. */
(function () {
  "use strict";

  var csrf = document.body ? document.body.dataset.csrf || "" : "";

  function readCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function writeCookie(name, value) {
    document.cookie =
      name + "=" + encodeURIComponent(value) + "; path=/; max-age=2592000; samesite=lax";
  }

  function rememberPasswordHandle() {
    var passwordForm = document.querySelector('form[action="/login"]');
    if (!passwordForm) return;
    passwordForm.addEventListener("submit", function () {
      var field = passwordForm.querySelector('input[name="login_handle"]');
      if (field && field.value) writeCookie("re_admin_handle", field.value.trim());
    });
  }

  document.addEventListener("DOMContentLoaded", rememberPasswordHandle);

  function b64url(buffer) {
    var bytes = new Uint8Array(buffer);
    var binary = "";
    for (var i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function fromB64url(value) {
    var normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    var pad = "=".repeat((4 - (normalized.length % 4)) % 4);
    var binary = atob(normalized + pad);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function creationOptions(publicKey) {
    var options = Object.assign({}, publicKey);
    options.challenge = fromB64url(publicKey.challenge);
    options.user = Object.assign({}, publicKey.user, { id: fromB64url(publicKey.user.id) });
    options.excludeCredentials = (publicKey.excludeCredentials || []).map(function (item) {
      return Object.assign({}, item, { id: fromB64url(item.id) });
    });
    return options;
  }

  function requestOptions(publicKey) {
    var options = Object.assign({}, publicKey);
    options.challenge = fromB64url(publicKey.challenge);
    options.allowCredentials = (publicKey.allowCredentials || []).map(function (item) {
      return Object.assign({}, item, { id: fromB64url(item.id) });
    });
    return options;
  }

  function serializeRegistration(credential) {
    return {
      id: credential.id,
      rawId: b64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: b64url(credential.response.clientDataJSON),
        attestationObject: b64url(credential.response.attestationObject),
        transports: credential.response.getTransports ? credential.response.getTransports() : [],
      },
      clientExtensionResults: credential.getClientExtensionResults
        ? credential.getClientExtensionResults()
        : {},
    };
  }

  function serializeAssertion(credential) {
    return {
      id: credential.id,
      rawId: b64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: b64url(credential.response.clientDataJSON),
        authenticatorData: b64url(credential.response.authenticatorData),
        signature: b64url(credential.response.signature),
        userHandle: credential.response.userHandle ? b64url(credential.response.userHandle) : null,
      },
      clientExtensionResults: credential.getClientExtensionResults
        ? credential.getClientExtensionResults()
        : {},
    };
  }

  function errorText(data, status) {
    if (data && data.error) {
      if (typeof data.error === "string") return data.error;
      if (typeof data.error.message === "string") return data.error.message;
      if (typeof data.error.code === "string") return data.error.code;
    }
    return "HTTP " + status;
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) throw new Error(errorText(data, response.status));
        return data;
      });
    });
  }

  function stepUp() {
    return postJson("/step-up/options")
      .then(function (data) {
        return navigator.credentials.get({ publicKey: requestOptions(data.public_key) });
      })
      .then(function (credential) {
        return postJson("/step-up/complete", { credential: serializeAssertion(credential) });
      });
  }

  function setupPasskey() {
    return postJson("/setup/webauthn/options")
      .then(function (data) {
        return navigator.credentials.create({ publicKey: creationOptions(data.public_key) });
      })
      .then(function (credential) {
        return postJson("/setup/webauthn/complete", {
          credential: serializeRegistration(credential),
        });
      })
      .then(function () {
        window.location.href = "/setup?step=recovery";
      });
  }

  function passkeyLogin() {
    return postJson("/login/webauthn/options", {})
      .then(function (data) {
        return navigator.credentials.get({ publicKey: requestOptions(data.public_key) });
      })
      .then(function (credential) {
        return postJson("/login/webauthn/complete", {
          credential: serializeAssertion(credential),
        });
      })
      .then(function () {
        window.location.href = "/";
      });
  }

  document.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["X-CSRF-Token"] = csrf;
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (target.classList.contains("step-up-btn")) {
      var status = document.querySelector(".step-up-status");
      if (status) status.textContent = "Waiting for passkey…";
      stepUp()
        .then(function () { window.location.reload(); })
        .catch(function (error) { if (status) status.textContent = String(error.message || error); });
    }
    if (target.id === "setup-passkey-btn") {
      var setupStatus = document.getElementById("setup-passkey-status");
      if (setupStatus) setupStatus.textContent = "Waiting for passkey…";
      setupPasskey().catch(function (error) {
        if (setupStatus) setupStatus.textContent = String(error.message || error);
      });
    }
    if (target.id === "passkey-login-btn") {
      var loginStatus = document.getElementById("passkey-login-status");
      if (loginStatus) loginStatus.textContent = "Waiting for passkey…";
      passkeyLogin().catch(function (error) {
        if (loginStatus) loginStatus.textContent = String(error.message || error);
      });
    }
  });
})();
