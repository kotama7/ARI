(function() {
  var saved = 'en';
  try { saved = localStorage.getItem('ari-lang') || 'en'; } catch(e) {}

  // Local-preview fallback for docs links. The VitePress build that serves
  // ./docs/ only exists in the assembled Pages artifact (.github/workflows/
  // pages.yml) — in the source tree (file:// or an IDE preview server) the
  // relative target resolves to docs/docs/ and 404s. Probe once; if the
  // relative docs root is unreachable, route every docs link to the deployed
  // site instead. Markup keeps relative hrefs so CI link checks still apply.
  var DOCS_ORIGIN = 'https://kotama7.github.io/ARI/';
  var docsBase = '';
  function rebaseDocsLinks() {
    if (!docsBase) return;
    var as = document.querySelectorAll('a[href^="docs/"]');
    for (var i = 0; i < as.length; i++) {
      as[i].setAttribute('href', docsBase + as[i].getAttribute('href'));
    }
  }
  function armDocsFallback() {
    function activate() {
      if (docsBase) return;
      docsBase = DOCS_ORIGIN;
      rebaseDocsLinks();
    }
    try {
      fetch('docs/', { method: 'HEAD' })
        .then(function (r) { if (!r.ok) activate(); })
        .catch(activate);
    } catch (e) { activate(); }
  }

  // After innerHTML replacement the new <video> elements need to be re-loaded
  // and explicitly .play()'d, because most browsers do not honor the autoplay
  // attribute on dynamically-inserted video elements.
  function kickAutoplayVideos() {
    var vids = document.querySelectorAll('video[autoplay]');
    for (var i = 0; i < vids.length; i++) {
      var v = vids[i];
      try {
        v.muted = true;       // muted is required by browser autoplay policies
        v.playsInline = true;
        v.load();
        var p = v.play();
        if (p && typeof p.catch === 'function') p.catch(function(){ /* blocked */ });
      } catch(e) { /* ignore */ }
    }
  }

  window.setLang = function(l) {
    var d = (window.LANGS || {})[l];
    if(!d) return;
    for(var k in d) { var el = document.getElementById('t-'+k); if(el) el.innerHTML = d[k]; }
    kickAutoplayVideos();
    // Keep <html lang> and <title> in sync with the active language (SEO / a11y).
    try { document.documentElement.lang = l; } catch(e) {}
    if (d['page-title']) { try { document.title = d['page-title']; } catch(e) {} }
    // Language buttons: active state via class (no inline color) + aria-pressed.
    // Report cards (P6): highlight the PDF that matches the active language.
    ['en','ja','zh'].forEach(function(x) {
      var b = document.getElementById('btn-'+x);
      if(b) {
        if (x === l) { b.classList.add('is-active'); } else { b.classList.remove('is-active'); }
        b.setAttribute('aria-pressed', x === l ? 'true' : 'false');
      }
      var c = document.getElementById('report-card-'+x);
      if(c) { if (x === l) { c.classList.add('is-default'); } else { c.classList.remove('is-default'); } }
    });
    // Cross-surface bridge (L3): deep-link the landing "Docs" links to the
    // matching VitePress locale so language continues across /  ↔  /docs/.
    var docHref = docsBase + (l === 'ja' ? 'docs/ja/' : l === 'zh' ? 'docs/zh/' : 'docs/');
    var dls = document.querySelectorAll('.js-docs-link');
    for (var di = 0; di < dls.length; di++) { dls[di].setAttribute('href', docHref); }
    try { localStorage.setItem('ari-lang', l); } catch(e) {}
  };

  function init() {
    window.setLang(saved);
    armDocsFallback();
    // First-paint fallback: some browsers (and VS Code preview iframes)
    // need a slight delay before the video element is ready to play.
    setTimeout(kickAutoplayVideos, 250);
    setTimeout(kickAutoplayVideos, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
