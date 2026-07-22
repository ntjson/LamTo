// Behaviour for the two data- attributes the staff templates already ship:
// data-busy-on-submit (loading state) and data-copy (hash copy button).
(function () {
  "use strict";

  // Loading state. Marks the form busy and blocks the double submit; the
  // browser is navigating away, so there is nothing to reset.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.hasAttribute("data-busy-on-submit")) return;
    if (form.getAttribute("aria-busy") === "true") {
      event.preventDefault();
      return;
    }
    form.setAttribute("aria-busy", "true");
  });

  // Copy a hash. Announces the result in place: the button is the only thing
  // the user is looking at, and a silent copy is indistinguishable from a
  // broken one.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var strings = window.lamtoI18n || {};
    var value = button.getAttribute("data-copy");
    var original = button.textContent;
    var done = function (message) {
      button.textContent = message;
      window.setTimeout(function () {
        button.textContent = original;
      }, 2000);
    };
    if (!navigator.clipboard) {
      done(strings.copyFailed || "Copy failed");
      return;
    }
    navigator.clipboard.writeText(value).then(
      function () {
        done(strings.copied || "Copied");
      },
      function () {
        done(strings.copyFailed || "Copy failed");
      }
    );
  });
})();
