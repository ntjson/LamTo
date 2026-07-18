/**
 * Wallet signing for staff dual-control forms.
 *
 * Classic (non-module) script: binds submit interceptors on forms marked
 * `data-signed-form`. Prefer server-provided EIP-712 typed data via:
 *   - form attribute data-typed-data='{...}'
 *   - child <script type="application/json" data-typed-data>
 *   - global window.lamtoBuildTypedData(form)
 *
 * When data-expected-signer is set, ALWAYS re-sign with that account (never
 * trust a pre-filled signature or MetaMask's display alone).
 */
(function (global) {
  "use strict";

  function randomBytes32() {
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

  function normalizeAccount(addr) {
    return addr ? String(addr).toLowerCase() : "";
  }

  /** MetaMask often returns recovery id 0/1; server expects 27/28. */
  function normalizeSignatureHex(sig) {
    if (!sig || typeof sig !== "string") return sig;
    var hex = sig.startsWith("0x") || sig.startsWith("0X") ? sig.slice(2) : sig;
    if (hex.length !== 130) return sig;
    var v = parseInt(hex.slice(128, 130), 16);
    if (v === 0 || v === 1) {
      hex = hex.slice(0, 128) + (v + 27).toString(16);
    }
    return "0x" + hex.toLowerCase();
  }

  /**
   * Prefer MetaMask when Brave Wallet also injects window.ethereum.
   * Watching the MetaMask panel while Brave answers request() causes
   * "signed as <other address>" even when the panel shows the right account.
   */
  function getEthereumProvider() {
    var eth = global.ethereum;
    if (!eth) return null;
    if (Array.isArray(eth.providers) && eth.providers.length) {
      var i;
      for (i = 0; i < eth.providers.length; i++) {
        var p = eth.providers[i];
        if (p && p.isMetaMask && !p.isBraveWallet) return p;
      }
      for (i = 0; i < eth.providers.length; i++) {
        if (eth.providers[i] && eth.providers[i].isMetaMask) return eth.providers[i];
      }
      return eth.providers[0];
    }
    return eth;
  }

  async function signTypedData(account, typedData) {
    var eth = getEthereumProvider();
    if (!eth || typeof eth.request !== "function") {
      throw new Error("A compatible wallet is required to sign this decision.");
    }
    var payload = JSON.parse(JSON.stringify(typedData));
    if (payload.domain && typeof payload.domain.chainId === "string") {
      payload.domain.chainId = parseInt(payload.domain.chainId, 10);
    }
    if (payload.message && typeof payload.message.eventType === "string") {
      payload.message.eventType = parseInt(payload.message.eventType, 10);
    }
    return eth.request({
      method: "eth_signTypedData_v4",
      params: [account, JSON.stringify(payload)],
    });
  }

  function expectedSigner(form) {
    return normalizeAccount(
      (form && form.getAttribute("data-expected-signer")) ||
        (form && form.dataset && form.dataset.expectedSigner) ||
        ""
    );
  }

  async function resolveSignerAccount(form) {
    var eth = getEthereumProvider();
    if (!eth || typeof eth.request !== "function") {
      throw new Error("A compatible wallet is required to sign this decision.");
    }
    var providerLabel =
      eth.isMetaMask && !eth.isBraveWallet
        ? "MetaMask"
        : eth.isBraveWallet
          ? "Brave Wallet"
          : "injected wallet";
    var accounts = await eth.request({ method: "eth_requestAccounts" });
    if (!accounts || !accounts.length) {
      throw new Error(
        "No account from " + providerLabel + ". Unlock it and connect this site."
      );
    }
    var expected = expectedSigner(form);
    if (expected) {
      for (var i = 0; i < accounts.length; i++) {
        if (normalizeAccount(accounts[i]) === expected) {
          return accounts[i];
        }
      }
      throw new Error(
        "Form requires " +
          expected +
          " but " +
          providerLabel +
          " only exposed: " +
          accounts.map(normalizeAccount).join(", ") +
          ". Open THAT wallet extension (not a different panel), connect the " +
          "required account to this site. If Brave Wallet and MetaMask both " +
          "exist, disable Brave Wallet or set MetaMask as default."
      );
    }
    var selected = normalizeAccount(eth.selectedAddress);
    if (selected) {
      for (var j = 0; j < accounts.length; j++) {
        if (normalizeAccount(accounts[j]) === selected) {
          return accounts[j];
        }
      }
    }
    return accounts[0];
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

    // Never trust a pre-filled signature when the server declared a required
    // signer — stale Operator signatures were the main multi-account footgun.
    var mustReselect = !!expectedSigner(form);
    if (
      !mustReselect &&
      fieldValue(form, "signature") &&
      fieldValue(form, "event_id")
    ) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    try {
      // Drop any leftover signature from a previous attempt.
      setField(form, "signature", "");

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

      setStatus(form, "Requesting wallet account…");
      var account = await resolveSignerAccount(form);
      var expected = expectedSigner(form);
      if (expected && normalizeAccount(account) !== expected) {
        throw new Error(
          "Refusing to sign: resolved " +
            normalizeAccount(account) +
            " but form requires " +
            expected
        );
      }
      setStatus(
        form,
        "Sign in MetaMask as " +
          account +
          " (must match registered role wallet). Check the address IN THE SIGN POPUP, not only the header."
      );
      if (typedData.message.eventId) {
        setField(form, "event_id", typedData.message.eventId);
      }
      var signature = await signTypedData(account, typedData);
      signature = normalizeSignatureHex(signature);
      setField(form, "signature", signature);
      setStatus(form, "Submitting as " + account + " …");
      form.removeEventListener("submit", handleSignedSubmit);
      HTMLFormElement.prototype.submit.call(form);
    } catch (err) {
      var msg = (err && err.message) || String(err);
      setStatus(form, msg);
      global.alert(msg);
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
    resolveSignerAccount: resolveSignerAccount,
  };
  global.signTypedData = signTypedData;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindSignedForms(document);
    });
  } else {
    bindSignedForms(document);
  }
})(typeof window !== "undefined" ? window : globalThis);
