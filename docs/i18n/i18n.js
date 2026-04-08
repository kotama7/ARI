(function() {
  var saved = 'en';
  try { saved = localStorage.getItem('ari-lang') || 'en'; } catch(e) {}

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
    ['en','ja','zh'].forEach(function(x) {
      var b = document.getElementById('btn-'+x);
      if(b) b.style.background = x===l ? '#2563eb' : 'rgba(255,255,255,0.08)';
    });
    try { localStorage.setItem('ari-lang', l); } catch(e) {}
  };

  function init() {
    window.setLang(saved);
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
