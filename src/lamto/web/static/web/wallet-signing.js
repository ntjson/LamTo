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
 *
 * User-facing strings come from window.lamtoI18n (injected by staff shell).
 */
(function (global) {
  "use strict";

  function t(key, vars) {
    var catalog = global.lamtoI18n || {};
    var text = catalog[key] || key;
    if (vars) {
      Object.keys(vars).forEach(function (name) {
        text = text.split("%(" + name + ")s").join(vars[name]);
      });
    }
    return text;
  }

  function randomBytes32() {
    if (!global.crypto || typeof global.crypto.getRandomValues !== "function") {
      throw new Error(t("secureRandomUnavailable"));
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
      throw new Error(t("walletRequired"));
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
      throw new Error(t("walletRequired"));
    }
    var providerLabel =
      eth.isMetaMask && !eth.isBraveWallet
        ? t("metaMask")
        : eth.isBraveWallet
          ? t("braveWallet")
          : t("injectedWallet");
    var accounts = await eth.request({ method: "eth_requestAccounts" });
    if (!accounts || !accounts.length) {
      throw new Error(t("noAccountFrom", { provider: providerLabel }));
    }
    var expected = expectedSigner(form);
    if (expected) {
      for (var i = 0; i < accounts.length; i++) {
        if (normalizeAccount(accounts[i]) === expected) {
          return accounts[i];
        }
      }
      throw new Error(t("walletNotConnected", { provider: providerLabel }));
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

  function setError(form, message) {
    var el = form.querySelector("[data-signing-error]");
    if (!el) return;
    el.textContent = message || "";
    el.hidden = !message;
  }

  function setBusy(form, busy) {
    if (busy) {
      form.setAttribute("aria-busy", "true");
    } else {
      form.removeAttribute("aria-busy");
    }
    var controls = form.querySelectorAll(
      'button[type="submit"], input[type="submit"]'
    );
    for (var i = 0; i < controls.length; i++) {
      if (busy) {
        controls[i]._lamtoWasDisabled = controls[i].disabled;
        controls[i].disabled = true;
      } else {
        controls[i].disabled = !!controls[i]._lamtoWasDisabled;
        delete controls[i]._lamtoWasDisabled;
      }
    }
  }

  function bindTypedDataOptions(form) {
    var optionsScript = form.querySelector(
      "script[type='application/json'][data-typed-data-options]"
    );
    var typedScript = form.querySelector(
      "script[type='application/json'][data-typed-data]"
    );
    var decision = form.querySelector('[name="decision"]');
    if (!optionsScript || !typedScript || !decision) return;
    var options = JSON.parse(optionsScript.textContent || "{}");
    decision.addEventListener("change", function () {
      if (!options[decision.value]) return;
      typedScript.textContent = JSON.stringify(options[decision.value]);
      setField(form, "signature", "");
      setError(form, "");
      setStatus(form, t("decisionUpdated"));
    });
  }

  async function handleSignedSubmit(event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-signed-form")) {
      return;
    }
    var submitControl = form.querySelector('[type="submit"]');
    if (
      submitControl &&
      submitControl.getAttribute("aria-disabled") === "true"
    ) {
      event.preventDefault();
      event.stopPropagation();
      setStatus(form, t("actionNotReady"));
      return;
    }

    // Never trust a pre-filled signature when the server declared a required
    // signer — stale Management signatures were the main multi-account footgun.
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
    setError(form, "");
    setBusy(form, true);

    try {
      // Drop any leftover signature from a previous attempt.
      setField(form, "signature", "");

      setStatus(form, t("preparingEvidence"));
      var typedData = parseTypedData(form);
      if (!typedData) {
        throw new Error(t("actionNotReadyRefresh"));
      }
      if (!typedData.message) {
        typedData.message = {};
      }
      if (!typedData.message.eventId) {
        typedData.message.eventId = randomBytes32();
      }

      setStatus(form, t("connectingWallet"));
      var account = await resolveSignerAccount(form);
      var expected = expectedSigner(form);
      if (expected && normalizeAccount(account) !== expected) {
        throw new Error(t("walletMismatch"));
      }
      setStatus(form, t("confirmInWallet"));
      if (typedData.message.eventId) {
        setField(form, "event_id", typedData.message.eventId);
      }
      var signature = await signTypedData(account, typedData);
      signature = normalizeSignatureHex(signature);
      setField(form, "signature", signature);
      setStatus(form, t("savingSigned"));
      form.removeEventListener("submit", handleSignedSubmit);
      HTMLFormElement.prototype.submit.call(form);
    } catch (err) {
      var msg = (err && err.message) || String(err);
      setStatus(form, t("signingStopped"));
      setError(form, msg + " " + t("checkAndRetry"));
      setBusy(form, false);
    }
  }


  function formatVnd(value) {
    var text = String(value == null ? "" : value).trim();
    if (!/^-?\d+$/.test(text)) return text;
    var sign = text.charAt(0) === "-" ? "-" : "";
    var digits = sign ? text.slice(1) : text;
    return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function bindReviewSummary(form) {
    if (!form.hasAttribute("data-review-form")) return;
    form.querySelectorAll("[data-review-value]").forEach(function (target) {
      var field = form.elements.namedItem(target.dataset.reviewValue);
      if (!field) return;
      var update = function () {
        var option = field.selectedOptions && field.selectedOptions[0];
        var raw = option ? option.textContent.trim() : field.value;
        if (raw === "" || raw == null) {
          target.innerHTML =
            '<span class="sr-only">' +
            t("notEnteredYet") +
            '</span><span aria-hidden="true">—</span>';
          return;
        }
        target.textContent = target.dataset.reviewValue.endsWith("_vnd")
          ? formatVnd(raw)
          : raw;
      };
      field.addEventListener("input", update);
      field.addEventListener("change", update);
      update();
    });
    var decision = form.elements.namedItem("decision");
    var label = form.querySelector("[data-decision-label]");
    var submit = form.querySelector("[data-decision-submit]");
    if (decision && label && submit) {
      var updateDecision = function () {
        var approving = decision.value === "APPROVE";
        label.textContent = approving ? t("approveProposal") : t("rejectForCorrection");
        submit.textContent = approving
          ? t("signAndApprove")
          : t("signAndReject");
      };
      decision.addEventListener("change", updateDecision);
      updateDecision();
    }
  }

  function bindSignedForms(root) {
    var scope = root || document;
    var forms = scope.querySelectorAll("form[data-signed-form]");
    for (var i = 0; i < forms.length; i++) {
      bindTypedDataOptions(forms[i]);
      bindReviewSummary(forms[i]);
      forms[i].addEventListener("submit", handleSignedSubmit);
      annotateMissingWallet(forms[i]);
    }
  }

  function annotateMissingWallet(form) {
    if (getEthereumProvider()) return;
    var hint = form.querySelector("[data-signing-status]");
    if (!hint) return;
    var expected = expectedSigner(form);
    if (!expected && !form.hasAttribute("data-signed-form")) return;
    hint.textContent = t("walletMissingHint");
    hint.classList.add("signing-status-warning");
  }

  function bindCopyButtons(root) {
    var scope = root || document;
    var buttons = scope.querySelectorAll("[data-copy]");
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].dataset.copyBound === "1") continue;
      buttons[i].dataset.copyBound = "1";
      buttons[i].addEventListener("click", function (event) {
        var btn = event.currentTarget;
        var value = btn.getAttribute("data-copy") || "";
        var baseLabel = btn.getAttribute("aria-label") || t("copy");
        function done(ok) {
          var previous = btn.textContent;
          var nextLabel = ok ? t("copied") : t("copyFailed");
          btn.textContent = nextLabel;
          btn.setAttribute("aria-label", nextLabel);
          if (!ok) {
            var status = btn.closest("form")
              ? btn.closest("form").querySelector("[data-signing-status]")
              : null;
            if (status) {
              status.textContent = t("copyFailedHint");
            }
          }
          global.setTimeout(function () {
            btn.textContent = previous;
            btn.setAttribute("aria-label", baseLabel);
          }, 1500);
        }
        if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
          global.navigator.clipboard.writeText(value).then(function () {
            done(true);
          }).catch(function () {
            done(false);
          });
          return;
        }
        done(false);
      });
    }
  }

  function bindBusyOnSubmit(root) {
    var scope = root || document;
    var forms = scope.querySelectorAll("form[data-busy-on-submit]");
    for (var i = 0; i < forms.length; i++) {
      if (forms[i].dataset.busyBound === "1") continue;
      forms[i].dataset.busyBound = "1";
      forms[i].addEventListener("submit", function (event) {
        var form = event.currentTarget;
        if (form.getAttribute("aria-busy") === "true") {
          event.preventDefault();
          return;
        }
        setBusy(form, true);
      });
    }
  }

  global.LamToWalletSigning = {
    signTypedData: signTypedData,
    bindSignedForms: bindSignedForms,
    bindCopyButtons: bindCopyButtons,
    bindBusyOnSubmit: bindBusyOnSubmit,
    handleSignedSubmit: handleSignedSubmit,
    bindTypedDataOptions: bindTypedDataOptions,
    bindReviewSummary: bindReviewSummary,
    formatVnd: formatVnd,
    parseTypedData: parseTypedData,
    randomBytes32: randomBytes32,
    resolveSignerAccount: resolveSignerAccount,
    t: t,
  };
  global.signTypedData = signTypedData;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindSignedForms(document);
      bindCopyButtons(document);
      bindBusyOnSubmit(document);
    });
  } else {
    bindSignedForms(document);
    bindCopyButtons(document);
    bindBusyOnSubmit(document);
  }
})(typeof window !== "undefined" ? window : globalThis);
