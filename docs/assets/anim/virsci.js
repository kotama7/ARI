/* virsci.js — VirSci multi-agent deliberation (Pa2).
 * Fidelity (§8.6): four personas with different backgrounds debate in
 * round-robin SERIAL order (one speak-edge at a time, one shared draft), the
 * best idea is selected by a running best_score update — there is NO voting
 * mechanism — and multi-round carries the previous draft (old_idea) forward
 * before the chosen idea is handed to BFTS.
 */
(function () {
  if (!window.ARIAnim) return;
  var A = window.ARIAnim, el = A.el;
  var root = document.getElementById('anim-virsci');
  if (!root) return;

  var DRAFT = { x: 250, y: 105, w: 140, h: 70 };
  var PERS = {
    senior: { x: 90, y: 70 }, critic: { x: 550, y: 70 },
    expert: { x: 90, y: 210 }, synth: { x: 550, y: 210 }
  };
  var STEPS = [
    {},
    { survey: 1 },
    { survey: 1, active: 'senior', score: '0.40' },
    { survey: 1, active: 'critic', score: '0.50' },
    { survey: 1, active: 'expert', score: '0.60' },
    { survey: 1, active: 'synth', score: '0.70' },
    { survey: 1, active: 'senior', score: '0.74', round: 2 },
    { survey: 1, score: '0.78', best: 1 },
    { survey: 1, score: '0.78', best: 1, tobfts: 1 }
  ];

  var title = document.createElement('h4'); title.className = 'anim-title'; title.id = 'anim-vs-title';
  var desc = document.createElement('p'); desc.className = 'anim-desc'; desc.id = 'anim-vs-desc';
  var svg = el('svg', {
    viewBox: '0 0 640 280', class: 'anim-svg', preserveAspectRatio: 'xMidYMid meet',
    role: 'img', 'aria-labelledby': 'anim-vs-title anim-vs-desc'
  });
  var svgTitle = el('title', {}); var svgDesc = el('desc', {});
  svg.appendChild(svgTitle); svg.appendChild(svgDesc);

  var cx = DRAFT.x + DRAFT.w / 2, cy = DRAFT.y + DRAFT.h / 2;
  // survey node + link
  var surveyG = el('g', { class: 'vs-survey' });
  var surveyLink = el('line', { x1: cx, y1: DRAFT.y, x2: cx, y2: 40, class: 'vs-link' });
  var surveyDot = el('circle', { cx: cx, cy: 28, r: 16, class: 'vs-survey-dot' });
  var surveyTx = el('text', { x: cx, y: 33, class: 'vs-survey-tx', 'text-anchor': 'middle' }); surveyTx.textContent = '📚';
  surveyG.appendChild(surveyLink); surveyG.appendChild(surveyDot); surveyG.appendChild(surveyTx);
  svg.appendChild(surveyG);

  // speak edges + persona nodes
  var edges = {}, nodes = {};
  Object.keys(PERS).forEach(function (k) {
    var p = PERS[k];
    var e = el('line', { x1: p.x, y1: p.y, x2: cx, y2: cy, class: 'vs-edge' });
    edges[k] = e; svg.appendChild(e);
  });
  Object.keys(PERS).forEach(function (k) {
    var p = PERS[k];
    var g = el('g', { class: 'vs-pers' });
    var c = el('circle', { cx: p.x, cy: p.y, r: 30, class: 'vs-dot' });
    var t = el('text', { x: p.x, y: p.y + 5, class: 'vs-pers-label', 'text-anchor': 'middle' });
    g.appendChild(c); g.appendChild(t); nodes[k] = { g: g, label: t }; svg.appendChild(g);
  });

  // draft card
  var draftG = el('g', { class: 'vs-draft' });
  var dRect = el('rect', { x: DRAFT.x, y: DRAFT.y, width: DRAFT.w, height: DRAFT.h, rx: 12, class: 'vs-draft-rect' });
  var dLabel = el('text', { x: cx, y: DRAFT.y + 24, class: 'vs-draft-label', 'text-anchor': 'middle' });
  var dScore = el('text', { x: cx, y: DRAFT.y + 48, class: 'vs-score', 'text-anchor': 'middle' });
  var dDims = el('text', { x: cx, y: DRAFT.y + 64, class: 'vs-dims', 'text-anchor': 'middle' });
  draftG.appendChild(dRect); draftG.appendChild(dLabel); draftG.appendChild(dScore); draftG.appendChild(dDims);
  svg.appendChild(draftG);

  // to-bfts handoff
  var bfG = el('g', { class: 'vs-tobfts is-hidden' });
  var bfArrow = el('line', { x1: DRAFT.x + DRAFT.w, y1: cy, x2: 600, y2: cy, class: 'vs-bf-arrow' });
  var bfTx = el('text', { x: 598, y: cy - 10, class: 'vs-bf-tx', 'text-anchor': 'end' });
  bfG.appendChild(bfArrow); bfG.appendChild(bfTx); svg.appendChild(bfG);

  var controls = document.createElement('div'); controls.className = 'anim-controls';
  controls.innerHTML =
    '<button type="button" class="anim-ctl" data-act="play" data-key-play="anim-ctl-play" data-key-pause="anim-ctl-pause" aria-pressed="false">▶</button>' +
    '<button type="button" class="anim-ctl" data-act="step" data-key="anim-ctl-step">⏭</button>' +
    '<button type="button" class="anim-ctl" data-act="restart" data-key="anim-ctl-restart">↺</button>';
  var status = document.createElement('p'); status.className = 'anim-status'; status.id = 'anim-vs-status';
  status.setAttribute('aria-live', 'polite');
  var caption = document.createElement('p'); caption.className = 'anim-caption'; caption.id = 'anim-vs-caption';

  root.appendChild(title); root.appendChild(desc); root.appendChild(svg);
  root.appendChild(controls); root.appendChild(status); root.appendChild(caption);

  function render(i) {
    var s = STEPS[i];
    surveyG.classList.toggle('is-on', !!s.survey);
    Object.keys(PERS).forEach(function (k) {
      nodes[k].g.classList.toggle('is-active', s.active === k);
      edges[k].classList.toggle('is-active', s.active === k);   // ONE speak-edge at a time
    });
    dScore.textContent = s.score ? (A.t('anim-vs-best') + ' ' + s.score) : '';
    dDims.textContent = s.score ? (A.t('anim-vs-novelty') + '×2 · ' + A.t('anim-vs-feasibility') + ' · ' + A.t('anim-vs-clarity')) : '';
    draftG.classList.toggle('is-best', !!s.best);
    dLabel.textContent = A.t('anim-vs-draft') + (s.round ? ' · ' + A.t('anim-vs-round') + ' ' + s.round : '');
    bfG.classList.toggle('is-hidden', !s.tobfts);
  }
  function refreshText() {
    title.textContent = A.t('anim-vs-title'); desc.textContent = A.t('anim-vs-desc');
    caption.textContent = A.t('anim-vs-caption');
    svgTitle.textContent = A.t('anim-vs-title'); svgDesc.textContent = A.t('anim-vs-desc');
    nodes.senior.label.textContent = A.t('anim-vs-senior');
    nodes.critic.label.textContent = A.t('anim-vs-critic');
    nodes.expert.label.textContent = A.t('anim-vs-expert');
    nodes.synth.label.textContent = A.t('anim-vs-synth');
    bfTx.textContent = A.t('anim-vs-tobfts');
  }
  refreshText();
  var KMAP = ['anim-vs-desc', 'anim-vs-survey', 'anim-vs-senior', 'anim-vs-critic', 'anim-vs-expert',
    'anim-vs-synth', 'anim-vs-round', 'anim-vs-best', 'anim-vs-tobfts'];
  var p = A.player({
    root: root, steps: STEPS.length, render: render, statusEl: status,
    statusKey: function (i) { return KMAP[i]; }, controls: controls, autoplay: true, interval: 1600
  });
  A.bindLang(function () { refreshText(); p.refresh(); render(0); });
})();
