/* Single-source version injection (P2).
 *
 * The product version lives in ONE place — docs/version.json. This loader
 * fetches it at startup and writes it into every `#ari-version` /
 * `[data-version]` slot, so no version literal is hard-coded in index.html or
 * the i18n dictionaries (which previously drifted: HTML said v0.8.1 while the
 * footer-text dictionary said v0.8.0). The injected text is NOT a `t-` key, so
 * the i18n language switcher never overwrites it.
 *
 * fetch() is relative to the current document, so it resolves correctly under
 * the GitHub Pages sub-path (/ARI/version.json). On file:// previews fetch may
 * be blocked — the slot is simply left blank rather than showing a stale value.
 */
(function () {
  function apply(v) {
    var els = document.querySelectorAll('#ari-version, [data-version]');
    for (var i = 0; i < els.length; i++) { els[i].textContent = v; }
  }
  try {
    fetch('version.json', { cache: 'no-cache' })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.version) apply(d.version); })
      .catch(function () { /* offline / file:// — leave the slot blank */ });
  } catch (e) { /* fetch unavailable — leave the slot blank */ }
})();
