/**
 * Wallet signing for staff dual-control forms.
 *
 * Classic (non-module) script: binds submit interceptors on forms marked
 * `data-signed-form`. Prefer server-provided EIP-712 typed data via:
 *   - form attribute data-typed-data='{...}'
 *   - child <script type="application/json" data-typed-data>
 *   - global window.lamtoBuildTypedData(form)
 *
 * If event_id and signature are already filled (manual/tests), submit proceeds.
 * Otherwise requests eth_requestAccounts + eth_signTypedData_v4 and populates
 * the form fields before POST.
 */
(function (global) {
  "use strict";

  function randomBytes32() {
    // Event IDs must be cryptographically random (spec 2.2): a predictable ID
    // would leak submission ordering to chain observers. No Math.random fallback.
    if (!global.crypto || typeof global.crypto.getRandomValues !== "function") {
      throw new Error("Secure random generator unavailable; cannot sign evidence.");
    }
    var bytes = new Uint8Array(32);
    global.crypto.getRandomValues(bytes);
    var hex = "";
    for (var j = 0; j < bytes.length; j++) {
      hex += bytes[j].toString(16).padStart(2, "0");
    }
    return "0x" + hex;
  }

  async function signTypedData(account, typedData) {
    if (!global.ethereum || typeof global.ethereum.request !== "function") {
      throw new Error("A compatible wallet is required to sign this decision.");
    }
    return global.ethereum.request({
      method: "eth_signTypedData_v4",
      params: [account, JSON.stringify(typedData)],
    });
  }

  function parseTypedData(form) {
    if (form.dataset && form.dataset.typedData) {
      return JSON.parse(form.dataset.typedData);
    }
    var script = form.querySelector(
      "script[type='application/json'][data-typed-data], script.typed-data-json"
    );
    if (script && script.textContent) {
      return JSON.parse(script.textContent);
    }
    if (typeof global.lamtoBuildTypedData === "function") {
      return global.lamtoBuildTypedData(form);
    }
    return null;
  }

  function setField(form, name, value) {
    var input = form.querySelector('[name="' + name + '"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      form.appendChild(input);
    }
    input.value = value;
  }

  function fieldValue(form, name) {
    var input = form.querySelector('[name="' + name + '"]');
    return input && input.value ? String(input.value).trim() : "";
  }

  function setStatus(form, message) {
    var el = form.querySelector("[data-signing-status]");
    if (el) {
      el.textContent = message;
    }
  }

  async function handleSignedSubmit(event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-signed-form")) {
      return;
    }
    // Allow pre-filled signatures (manual entry / automated tests).
    if (fieldValue(form, "signature") && fieldValue(form, "event_id")) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    try {
      setStatus(form, "Preparing wallet signature…");
      var typedData = parseTypedData(form);
      if (!typedData) {
        throw new Error(
          "No typed data on this form. Provide data-typed-data JSON, or fill event_id and signature manually."
        );
      }
      if (!typedData.message) {
        typedData.message = {};
      }
      if (!typedData.message.eventId) {
        typedData.message.eventId = randomBytes32();
      }

      if (!global.ethereum || typeof global.ethereum.request !== "function") {
        throw new Error("A compatible wallet is required to sign this decision.");
      }
      setStatus(form, "Requesting wallet account…");
      var accounts = await global.ethereum.request({ method: "eth_requestAccounts" });
      var account = accounts && accounts[0];
      if (!account) {
        throw new Error("No wallet account available.");
      }
      setStatus(form, "Sign the typed data in your wallet…");
      var signature = await signTypedData(account, typedData);
      setField(form, "event_id", typedData.message.eventId);
      setField(form, "signature", signature);
      setStatus(form, "Submitting…");
      form.removeEventListener("submit", handleSignedSubmit);
      // Native submit skips listeners we just unbound.
      HTMLFormElement.prototype.submit.call(form);
    } catch (err) {
      var msg = (err && err.message) || String(err);
      setStatus(form, msg);
      if (!form.querySelector("[data-signing-status]")) {
        global.alert(msg);
      }
    }
  }

  function bindSignedForms(root) {
    var scope = root || document;
    var forms = scope.querySelectorAll("form[data-signed-form]");
    for (var i = 0; i < forms.length; i++) {
      forms[i].addEventListener("submit", handleSignedSubmit);
    }
  }

  global.LamToWalletSigning = {
    signTypedData: signTypedData,
    bindSignedForms: bindSignedForms,
    handleSignedSubmit: handleSignedSubmit,
    parseTypedData: parseTypedData,
    randomBytes32: randomBytes32,
  };
  // Back-compat alias used by some templates/tests.
  global.signTypedData = signTypedData;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindSignedForms(document);
    });
  } else {
    bindSignedForms(document);
  }
})(typeof window !== "undefined" ? window : globalThis);
