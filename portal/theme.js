(function () {
  "use strict";
  var KEY = "nfcore-theme";
  function read() {
    try { var v = window.localStorage.getItem(KEY); return v === "dark" || v === "light" ? v : "light"; }
    catch { return "light"; }
  }
  /** @param {string} theme */
  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#08121f" : "#f3f6fb");
  }
  apply(read());
  document.addEventListener("DOMContentLoaded", function () {
    var element = document.getElementById("theme-toggle");
    if (!(element instanceof HTMLButtonElement)) return;
    var button = element;
    function sync() {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      button.textContent = dark ? "Tema claro" : "Tema escuro";
      button.setAttribute("aria-label", dark ? "Mudar para o tema claro" : "Mudar para o tema escuro");
    }
    sync();
    button.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(next);
      try { window.localStorage.setItem(KEY, next); } catch { /* o tema vale apenas nesta sessão */ }
      sync();
    });
  });
})();
