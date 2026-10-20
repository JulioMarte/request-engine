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

  // Some Chromium configurations omit Origin on a top-level same-origin form
  // navigation. The admin CSRF boundary intentionally rejects that request.
  // Submit every setup mutation through fetch instead; fetch is same-origin,
  // carries the setup cookie, and causes Chromium to emit Origin reliably.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("form[data-setup-session], form[data-setup-form]")) return;
    event.preventDefault();
    var button = form.querySelector("button[type=submit]");
    var status = form.querySelector("[data-setup-session-status], [data-setup-form-status]");
    if (button) button.disabled = true;
    if (status) status.textContent = "Processing…";
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      redirect: "follow",
    }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.error || "Could not start setup session");
        });
      }
      // Identity validation and invalid submissions redirect. Recovery-code
      // issuance and final claim return HTML directly; replace the document for
      // those responses instead of navigating to a POST-only URL.
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      return response.text().then(function (html) {
        document.open();
        document.write(html);
        document.close();
      });
    }).catch(function (error) {
      if (button) button.disabled = false;
      if (status) status.textContent = String(error.message || error);
    });
  });

  // Fetch also supplies Origin for password login without weakening the
  // same-origin guard. Server-rendered errors retain the GET login address.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || (!form.matches("form[data-password-login]") && !form.matches("form[data-session-logout]"))) return;
    event.preventDefault();
    if (form.getAttribute("aria-busy") === "true") return;
    var button = form.querySelector("button[type=submit]");
    var status = form.querySelector("[data-password-login-status]");
    form.setAttribute("aria-busy", "true");
    if (button) button.disabled = true;
    if (status) status.textContent = "Signing in…";
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      redirect: "follow",
    }).then(function (response) {
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      // Invalid credentials return rendered HTML with a non-success status.
      return response.text().then(function (html) {
        document.open();
        document.write(html);
        document.close();
      });
    }).catch(function (error) {
      form.removeAttribute("aria-busy");
      if (button) button.disabled = false;
      var password = form.querySelector('input[name="password"]');
      if (password) password.value = "";
      if (status) status.textContent = String(error.message || error);
    });
  });

  function initializeFormIntents(root) {
    var fields = (root || document).querySelectorAll("input[data-form-intent]");
    fields.forEach(function (field) {
      if (field.value) return;
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        field.value = window.crypto.randomUUID().replace(/-/g, "");
      } else {
        field.value = "intent-" + Date.now() + "-" + Math.random().toString(36).slice(2);
      }
    });
  }

  function newIntentId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replace(/-/g, "");
    }
    return "intent-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  }

  function rotateIntentForEditedDraft(event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    var form = target.closest("form");
    if (!form || target.matches('input[name="_intent_id"], input[name="_csrf"]')) return;
    var intent = form.querySelector('input[name="_intent_id"][data-form-intent]');
    if (intent) intent.value = newIntentId();
    if (form.id === "staff-plan") {
      var reviewed = document.getElementById("staff-plan-result");
      if (reviewed) reviewed.replaceChildren();
    }
  }

  document.addEventListener("DOMContentLoaded", function () { initializeFormIntents(document); });
  document.addEventListener("htmx:afterSwap", function (event) {
    initializeFormIntents(event.detail.target || document);
  });
  document.addEventListener("input", rotateIntentForEditedDraft);
  document.addEventListener("change", rotateIntentForEditedDraft);

  function navigationElements() {
    return {
      sidebar: document.getElementById("admin-sidebar"),
      toggle: document.querySelector(".menu-toggle"),
      scrim: document.querySelector(".nav-scrim"),
      frame: document.getElementById("admin-frame"),
    };
  }

  function setNavigation(open, returnFocus) {
    var elements = navigationElements();
    if (!elements.sidebar || !elements.toggle) return;
    var mobile = window.matchMedia("(max-width: 900px)").matches;
    document.body.classList.toggle("nav-open", mobile && open);
    elements.toggle.setAttribute("aria-expanded", mobile && open ? "true" : "false");
    elements.sidebar.inert = mobile && !open;
    if (elements.frame) elements.frame.inert = mobile && open;
    if (mobile && open) {
      elements.sidebar.setAttribute("role", "dialog");
      elements.sidebar.setAttribute("aria-modal", "true");
    } else {
      elements.sidebar.removeAttribute("role");
      elements.sidebar.removeAttribute("aria-modal");
    }
    if (elements.scrim) elements.scrim.tabIndex = mobile && open ? 0 : -1;
    if (mobile && open) {
      var firstLink = elements.sidebar.querySelector("a");
      if (firstLink) firstLink.focus();
    } else if (returnFocus) {
      elements.toggle.focus();
    }
  }

  document.addEventListener("DOMContentLoaded", function () { setNavigation(false, false); });
  window.addEventListener("resize", function () { setNavigation(false, false); });
  document.addEventListener("keydown", function (event) {
    if (!document.body.classList.contains("nav-open")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setNavigation(false, true);
    }
    if (event.key === "Tab") {
      var elements = navigationElements();
      var links = Array.from(elements.sidebar.querySelectorAll("a[href], button:not(:disabled)"));
      if (elements.scrim) links.push(elements.scrim);
      if (!links.length) return;
      var first = links[0];
      var last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest(".menu-toggle")) {
      setNavigation(!document.body.classList.contains("nav-open"), false);
      return;
    }
    if (target.closest(".nav-scrim")) {
      setNavigation(false, true);
    } else if (target.closest("#admin-sidebar a") && window.matchMedia("(max-width: 900px)").matches) {
      setNavigation(false, false);
    }
  });

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

  function reauthenticationStatus(element) {
    var section = element.closest("[data-reauthentication]");
    return section ? section.querySelector(".step-up-status") : document.querySelector(".step-up-status");
  }

  function retryConfirmedForm(element, status) {
    var formId = element.getAttribute("data-retry-form");
    var form = formId ? document.getElementById(formId) : null;
    if (status) status.textContent = formId ? "Confirmed. Retrying…" : "Current session confirmed.";
    if (form && form.requestSubmit) form.requestSubmit();
  }

  function enablePasswordConfirmation(root) {
    (root || document).querySelectorAll("form[data-password-step-up] button[type=submit], form[data-password-recovery-complete] button[type=submit]").forEach(function (button) {
      button.disabled = false;
    });
  }
  document.addEventListener("DOMContentLoaded", function () { enablePasswordConfirmation(document); });
  document.addEventListener("htmx:afterSwap", function (event) { enablePasswordConfirmation(event.detail.target || document); });
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || (!form.matches("form[data-password-step-up]") && !form.matches("form[data-password-recovery-complete]"))) return;
    event.preventDefault();
    if (form.getAttribute("aria-busy") === "true") return;
    var password = form.querySelector('input[name="password"]');
    var value = password ? password.value : "";
    if (password) password.value = "";
    var status = reauthenticationStatus(form);
    var button = form.querySelector("button[type=submit]");
    form.setAttribute("aria-busy", "true");
    if (button) button.disabled = true;
    if (status) status.textContent = "Confirming current session…";
    var recovery = form.matches("form[data-password-recovery-complete]");
    postJson(recovery ? "/account/security/recovery-complete" : "/step-up/password", { password: value })
      .then(function () {
        if (recovery) {
          if (status) status.textContent = "Recovery completed. Sign out, then sign in with your password to start a normal session.";
        } else retryConfirmedForm(form, status);
      })
      .catch(function (error) { if (status) status.textContent = String(error.message || error); })
      .finally(function () {
        value = "";
        form.removeAttribute("aria-busy");
        if (button) button.disabled = false;
      });
  });

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
        var nextInput = document.querySelector('input[name="next"]');
        var next = nextInput ? nextInput.value : "/";
        window.location.href = next === "/staff-invitations/accept" || next === "/account/security"
          ? next : "/";
      });
  }

  document.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["X-CSRF-Token"] = csrf;
  });

  document.addEventListener("htmx:confirm", function (event) {
    var element = event.detail.elt;
    var message = element && element.getAttribute ? element.getAttribute("data-confirm") : null;
    if (!message) return;
    event.preventDefault();
    var dialog = document.getElementById("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {
      if (window.confirm(message)) event.detail.issueRequest(true);
      return;
    }
    if (dialog.open) return;
    dialog.returnValue = "cancel";
    var messageNode = document.getElementById("confirm-message");
    if (messageNode) messageNode.textContent = message;
    dialog.showModal();
    dialog.addEventListener("close", function onClose() {
      dialog.removeEventListener("close", onClose);
      if (dialog.returnValue === "confirm") event.detail.issueRequest(true);
    });
  });

  function requestForm(event) {
    var element = event.detail && event.detail.elt;
    return element && element.closest ? element.closest("form") : null;
  }

  function finishFormRequest(event) {
    var form = requestForm(event);
    if (!form) return;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("[data-request-disabled]").forEach(function (button) {
      button.disabled = false;
      button.removeAttribute("data-request-disabled");
    });
  }

  document.addEventListener("htmx:beforeRequest", function (event) {
    var form = requestForm(event);
    if (!form) return;
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll("button[type=submit]").forEach(function (button) {
      if (button.disabled) return;
      button.setAttribute("data-request-disabled", "true");
      button.disabled = true;
    });
  });
  document.addEventListener("htmx:afterRequest", finishFormRequest);
  document.addEventListener("htmx:sendError", finishFormRequest);
  document.addEventListener("htmx:timeout", finishFormRequest);

  document.addEventListener("input", function (event) {
    var input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.matches("[data-table-filter]")) return;
    var query = input.value.trim().toLowerCase();
    var rows = Array.from(document.querySelectorAll("[data-filter-row]"));
    var visible = 0;
    rows.forEach(function (row) {
      var match = !query || (row.dataset.search || "").includes(query);
      row.hidden = !match;
      if (match) visible += 1;
    });
    var status = document.getElementById("filter-status");
    if (status) status.textContent = visible + " of " + rows.length + " loaded results shown";
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("form[data-secret-lookup]")) return;
    event.preventDefault();
    var input = form.querySelector('input[name="binding_id"]');
    var value = input ? input.value.trim() : "";
    if (value) window.location.href = "/resources/secrets/" + encodeURIComponent(value);
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (target.classList.contains("step-up-btn")) {
      var status = reauthenticationStatus(target);
      if (status) status.textContent = "Waiting for passkey…";
      stepUp()
        .then(function () {
          retryConfirmedForm(target, status);
        })
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
  // Nested controls submit named scalar fields; the server reconstructs only
  // canonical schema properties and keeps owner validation authoritative.
  document.addEventListener("change", function (event) {
    var target = event.target;
    if (!(target instanceof Element) || !target.matches("[data-include-structured], [data-structured-mode]")) return;
    var group = target.closest("[data-structured-input]");
    var controls = group ? group.querySelector("[data-structured-controls]") : null;
    var include = group ? group.querySelector(":scope > label > [data-include-structured]") : null;
    var mode = group ? group.querySelector(":scope > label > [data-structured-mode]") : null;
    if (controls) controls.disabled = (include && !include.checked) || (mode && mode.value === "null");
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    var add = target.closest("[data-array-add]");
    if (add) {
      var editor = add.closest("[data-array-editor]");
      if (!editor) return;
      var rows = editor.querySelector(":scope > [data-array-rows]");
      var template = editor.querySelector(":scope > template[data-array-template]");
      if (!rows || !template || rows.children.length >= 100) return;
      var next = Number(editor.dataset.nextIndex || "0");
      var html = template.innerHTML.split(editor.dataset.indexToken).join(String(next));
      editor.dataset.nextIndex = String(next + 1);
      rows.insertAdjacentHTML("beforeend", html);
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      var entry = rows.lastElementChild;
      var input = entry ? entry.querySelector("input:not([type=hidden]), select, textarea") : null;
      if (input) input.focus();
    }
    var remove = target.closest("[data-array-remove]");
    if (remove) {
      var row = remove.closest("[data-array-row]");
      var parent = row ? row.parentElement : null;
      if (row) row.remove();
      if (parent) parent.dispatchEvent(new Event("input", { bubbles: true }));
      var nextButton = parent && parent.parentElement ? parent.parentElement.querySelector(":scope > [data-array-add]") : null;
      if (nextButton) nextButton.focus();
    }
  });
  // Hide the mobile sidebar only after its controls are actually installed.
  document.documentElement.classList.add("js-navigation");
})();
