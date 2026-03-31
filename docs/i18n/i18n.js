(function() {
  var saved = 'en';
  try { saved = localStorage.getItem('ari-lang') || 'en'; } catch(e) {}
  window.setLang = function(l) {
    var d = (window.LANGS || {})[l];
    if(!d) return;
    for(var k in d) { var el = document.getElementById('t-'+k); if(el) el.innerHTML = d[k]; }
    ['en','ja','zh'].forEach(function(x) {
      var b = document.getElementById('btn-'+x);
      if(b) b.style.background = x===l ? '#2563eb' : 'rgba(255,255,255,0.08)';
    });
    try { localStorage.setItem('ari-lang', l); } catch(e) {}
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { window.setLang(saved); });
  } else {
    window.setLang(saved);
  }
})();
