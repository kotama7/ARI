/* pipeline.js — the 6-step pipeline, with step 3 (Experiment) as the only
 * branching core (a BFTS-mini), 4-6 converging to a single post-BFTS line (Pa2).
 * Reuses the existing step1..6 labels from the i18n dict (no new prose / no
 * emoji duplication). Self-contained strip (not an overlay) to stay CLS-free on
 * the responsive grid.
 */
(function () {
  if (!window.ARIAnim) return;
  var A = window.ARIAnim, el = A.el;
  var root = document.getElementById('anim-pipeline');
  if (!root) return;

  var CX = [100, 290, 480, 670, 860, 1050], CY = 70, R = 30;
  // reached = how many main steps are lit; mini = bfts-mini state at step 3
  var STEPS = [
    { reached: 0, mini: 'hidden' },
    { reached: 1, mini: 'hidden' },
    { reached: 2, mini: 'hidden' },
    { reached: 3, mini: 'running' },
    { reached: 3, mini: 'resolved' },
    { reached: 4, mini: 'resolved' },
    { reached: 5, mini: 'resolved' },
    { reached: 6, mini: 'resolved' }
  ];

  var title = document.createElement('h4'); title.className = 'anim-title'; title.id = 'anim-pl-title';
  var desc = document.createElement('p'); desc.className = 'anim-desc'; desc.id = 'anim-pl-desc';
  var svg = el('svg', {
    viewBox: '0 0 1150 210', class: 'anim-svg', preserveAspectRatio: 'xMidYMid meet',
    role: 'img', 'aria-labelledby': 'anim-pl-title anim-pl-desc'
  });
  var svgTitle = el('title', {}); var svgDesc = el('desc', {});
  svg.appendChild(svgTitle); svg.appendChild(svgDesc);

  // connectors between main steps
  var segs = [];
  for (var s = 0; s < 5; s++) {
    var ln = el('line', { x1: CX[s] + R, y1: CY, x2: CX[s + 1] - R, y2: CY, class: 'pl-seg' });
    segs.push(ln); svg.appendChild(ln);
  }
  // main step circles + labels
  var stepEls = [];
  for (var k = 0; k < 6; k++) {
    var g = el('g', { class: 'pl-step' });
    var c = el('circle', { cx: CX[k], cy: CY, r: R, class: 'pl-dot' });
    var num = el('text', { x: CX[k], y: CY + 6, class: 'pl-num', 'text-anchor': 'middle' }); num.textContent = String(k + 1);
    var lab = el('text', { x: CX[k], y: CY + R + 24, class: 'pl-label', 'text-anchor': 'middle' });
    g.appendChild(c); g.appendChild(num); g.appendChild(lab);
    stepEls.push({ g: g, label: lab }); svg.appendChild(g);
  }
  // bfts-mini under step 3
  var mini = el('g', { class: 'pl-mini' });
  var mEdges = [
    el('line', { x1: 480, y1: CY + R, x2: 440, y2: 150, class: 'anim-edge' }),
    el('line', { x1: 480, y1: CY + R, x2: 520, y2: 150, class: 'anim-edge' }),
    el('line', { x1: 520, y1: 150, x2: 500, y2: 195, class: 'anim-edge is-dashed' })
  ];
  mEdges.forEach(function (e) { mini.appendChild(e); });
  var mNodes = [
    el('circle', { cx: 440, cy: 150, r: 13, class: 'pl-mini-dot', 'data-mini': 'a' }),
    el('circle', { cx: 520, cy: 150, r: 13, class: 'pl-mini-dot', 'data-mini': 'b' }),
    el('circle', { cx: 500, cy: 195, r: 13, class: 'pl-mini-dot', 'data-mini': 'c' })
  ];
  mNodes.forEach(function (n) { mini.appendChild(n); });
  svg.appendChild(mini);

  var controls = document.createElement('div'); controls.className = 'anim-controls';
  controls.innerHTML =
    '<button type="button" class="anim-ctl" data-act="play" data-key-play="anim-ctl-play" data-key-pause="anim-ctl-pause" aria-pressed="false">▶</button>' +
    '<button type="button" class="anim-ctl" data-act="step" data-key="anim-ctl-step">⏭</button>' +
    '<button type="button" class="anim-ctl" data-act="restart" data-key="anim-ctl-restart">↺</button>';
  var status = document.createElement('p'); status.className = 'anim-status'; status.id = 'anim-pl-status';
  status.setAttribute('aria-live', 'polite');

  root.appendChild(title); root.appendChild(desc); root.appendChild(svg);
  root.appendChild(controls); root.appendChild(status);

  function render(i) {
    var st = STEPS[i];
    stepEls.forEach(function (e, k) {
      var cls = 'pl-step';
      if (k + 1 < st.reached) cls += ' is-done';
      else if (k + 1 === st.reached) cls += ' is-current';
      e.g.setAttribute('class', cls);
    });
    segs.forEach(function (e, k) { e.setAttribute('class', 'pl-seg' + (k + 1 < st.reached ? ' is-done' : '')); });
    mini.setAttribute('class', 'pl-mini' + (st.mini === 'hidden' ? ' is-hidden' : ''));
    var states = st.mini === 'running' ? ['is-running', 'is-running', 'is-hidden']
      : st.mini === 'resolved' ? ['is-success', 'is-failed', 'is-success'] : ['is-pending', 'is-pending', 'is-hidden'];
    mNodes.forEach(function (n, k) { n.setAttribute('class', 'pl-mini-dot ' + states[k]); });
    mEdges[2].setAttribute('class', 'anim-edge is-dashed' + (st.mini === 'resolved' ? '' : ' is-hidden'));
  }
  function refreshText() {
    title.textContent = A.t('anim-pl-title'); desc.textContent = A.t('anim-pl-desc');
    svgTitle.textContent = A.t('anim-pl-title'); svgDesc.textContent = A.t('anim-pl-desc');
    stepEls.forEach(function (e, k) { e.label.textContent = A.t('step' + (k + 1) + '-title'); });
  }
  refreshText();
  var KMAP = ['anim-pl-desc', 'step1-title', 'step2-title', 'anim-pl-core', 'step4-title', 'step5-title', 'step6-title', 'anim-pl-done'];
  var p = A.player({
    root: root, steps: STEPS.length, render: render, statusEl: status,
    statusKey: function (i) { return KMAP[i]; }, controls: controls, autoplay: true, interval: 1500
  });
  A.bindLang(function () { refreshText(); p.refresh(); render(0); });
})();
