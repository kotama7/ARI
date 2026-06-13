/* anim-core.js — shared, dependency-free loader for the ARI algorithm
 * animations (see docs/README.md, "Homepage static site"). One IntersectionObserver, one
 * rAF-driven state-machine player, reduced-motion handling and i18n binding,
 * reused by bfts.js / react.js / pipeline.js / virsci.js.
 *
 * Build-less: no framework, no external request. SVG is generated inline by
 * each algorithm module. State transitions are discrete index changes (CSS
 * eases the visuals), so there is no runtime layout work → no CLS.
 */
window.ARIAnim = (function () {
  var reduce = false;
  try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; }
  catch (e) { reduce = false; }

  // Shared IntersectionObserver: init a block when it first scrolls into view,
  // and report enter/leave so the player can pause off-screen.
  var visCbs = [];
  var io = null;
  if (typeof IntersectionObserver === 'function') {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var rec = visCbs.filter(function (r) { return r.el === en.target; })[0];
        if (rec) rec.cb(en.isIntersecting);
      });
    }, { threshold: 0.35 });
  }
  function observe(el, cb) {
    if (!io) { cb(true); return; }          // no IO support → treat as visible
    visCbs.push({ el: el, cb: cb });
    io.observe(el);
  }

  // Current-language lookup for status / label strings (follows the switcher).
  function t(key) {
    var l = 'en';
    try { l = localStorage.getItem('ari-lang') || 'en'; } catch (e) {}
    var d = (window.LANGS || {})[l] || (window.LANGS || {}).en || {};
    return d[key] != null ? d[key] : '';
  }

  // Tiny SVG element helper.
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, kids) {
    var n = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (kids) kids.forEach(function (c) { n.appendChild(c); });
    return n;
  }

  /* player(cfg):
   *   cfg.root        — container element
   *   cfg.steps       — number of discrete states
   *   cfg.render(i)   — apply state i to the DOM (pure visual diff)
   *   cfg.statusKey(i)— i18n key for the aria-live status of state i
   *   cfg.statusEl    — the aria-live element
   *   cfg.controls    — element holding [data-act] buttons
   *   cfg.autoplay    — loop automatically once visible (else single pass)
   *   cfg.interval    — ms per state (default 1500)
   */
  function player(cfg) {
    var i = 0, playing = false, timer = null;
    var interval = cfg.interval || 1500;

    function applyStatus() {
      if (cfg.statusEl && cfg.statusKey) {
        var s = t(cfg.statusKey(i));
        if (s) cfg.statusEl.textContent = s;
      }
    }
    function show(n) { i = ((n % cfg.steps) + cfg.steps) % cfg.steps; cfg.render(i); applyStatus(); }
    function setPlayBtn(on) {
      var b = cfg.controls && cfg.controls.querySelector('[data-act="play"]');
      if (!b) return;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.textContent = on ? '⏸' : '▶';
      var key = on ? b.getAttribute('data-key-pause') : b.getAttribute('data-key-play');
      if (key && t(key)) b.setAttribute('aria-label', t(key));
    }
    function refreshLabels() {
      if (cfg.controls) {
        var btns = cfg.controls.querySelectorAll('[data-act]');
        for (var j = 0; j < btns.length; j++) {
          var b = btns[j];
          if (b.getAttribute('data-act') !== 'play') {
            var k = b.getAttribute('data-key');
            if (k && t(k)) b.setAttribute('aria-label', t(k));
          }
        }
      }
      setPlayBtn(playing);
      applyStatus();
    }
    function stop() { playing = false; if (timer) { clearTimeout(timer); timer = null; } setPlayBtn(false); }
    function tick() {
      timer = setTimeout(function () {
        var atEnd = i === cfg.steps - 1;
        if (atEnd && !cfg.autoplay) { stop(); return; }
        show(i + 1);
        tick();
      }, interval);
    }
    function play() {
      if (reduce || playing) return;            // reduced-motion never auto-runs
      playing = true; setPlayBtn(true); tick();
    }
    function pause() { stop(); }
    function step() { stop(); show(i + 1); }
    function restart() { stop(); show(0); if (cfg.autoplay) play(); }

    // wire controls
    if (cfg.controls) {
      cfg.controls.addEventListener('click', function (e) {
        var b = e.target.closest('[data-act]');
        if (!b) return;
        var act = b.getAttribute('data-act');
        if (act === 'play') { playing ? pause() : play(); }
        else if (act === 'step') step();
        else if (act === 'restart') restart();
      });
    }

    // initial paint + lazy/visibility behaviour
    refreshLabels();
    if (reduce) {
      show(cfg.steps - 1);                      // final frame, static
    } else {
      show(0);
      observe(cfg.root, function (vis) {
        if (vis) { if (cfg.autoplay) play(); }
        else { stop(); }
      });
    }
    return { play: play, pause: pause, step: step, restart: restart, show: show, refresh: refreshLabels };
  }

  // Re-pull i18n status text when the language changes.
  function bindLang(refresh) {
    var prev = window.setLang;
    if (typeof prev === 'function' && !prev.__animWrapped) {
      window.setLang = function (l) { prev(l); try { refresh(); } catch (e) {} };
      window.setLang.__animWrapped = true;
    }
  }

  return { reduce: reduce, observe: observe, t: t, el: el, player: player, bindLang: bindLang };
})();
