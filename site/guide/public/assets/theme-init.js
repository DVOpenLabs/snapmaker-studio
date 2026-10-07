// Runs before the page paints so the saved theme never flashes. Kept as a separate file so the page can be served with a
// strict Content-Security-Policy (no inline script).
(function () {
  var d = document.documentElement;
  d.classList.add("js");
  try {
    var t = localStorage.getItem("sg.theme");
    if (t === "light" || t === "dark") d.dataset.theme = t;
  } catch (e) { /* storage blocked: the default theme is used */ }
})();
