/* bfts.js — flagship Best-First Tree Search animation (Pa1).
 * Faithful to docs.html / index.html prose and §8.6 fidelity notes:
 *   - frontier is chosen by the LLM on peer-review scores (a ring marks it),
 *     NOT a greedy heuristic; the deterministic fallback is not drawn.
 *   - a failed node spawns a DEBUG child on a DASHED edge (not an in-place retry).
 *   - canonical colours only: success/failed/running/pending.
 *   - score_threshold retirement applies to EVALUATED nodes scoring < 0.3.
 *   - config values (50 / 5 / 4 / 0.3) are shown verbatim in the caption.
 * Build-less: inline SVG, fixed coordinates, no layout work at runtime.
 */
(function () {
  if (!window.ARIAnim) return;
  var A = window.ARIAnim, el = A.el;
  var root = document.getElementById('anim-bfts');
  if (!root) return;

  var VB_W = 760, VB_H = 480, R = 26;
  // id, x, y, node type, parent, edge style
  var NODES = [
    { id: 'n0', x: 380, y: 52, ab: 'DR',  parent: null, edge: null },
    { id: 'n1', x: 230, y: 178, ab: 'IM', parent: 'n0', edge: 'solid' },
    { id: 'n2', x: 540, y: 178, ab: 'AB', parent: 'n0', edge: 'solid' },
    { id: 'n4', x: 150, y: 322, ab: 'VAL',parent: 'n1', edge: 'solid' },
    { id: 'n5', x: 320, y: 322, ab: 'IM', parent: 'n1', edge: 'solid' },
    { id: 'n3', x: 300, y: 436, ab: 'DBG',parent: 'n5', edge: 'dashed' },
    { id: 'n6', x: 580, y: 322, ab: 'VAL',parent: 'n2', edge: 'solid' }
  ];
  var POS = {}; NODES.forEach(function (n) { POS[n.id] = n; });

  // per-state node props: { st, sc(score), ring, retire, best }; absent = hidden
  var STEPS = [
    { n0: { st: 'running' } },                                                            // S0
    { n0: { st: 'success', sc: '0.55' } },                                                // S1
    { n0: { st: 'success', sc: '0.55', ring: 1 } },                                       // S2
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68', ring: 1 } },    // S3
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68' },               // S4
      n2: { st: 'running' }, n4: { st: 'running' }, n5: { st: 'running' }, n6: { st: 'running' } },
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68' },               // S5
      n2: { st: 'success', sc: '0.61' }, n4: { st: 'success', sc: '0.22' },
      n5: { st: 'failed' }, n3: { st: 'success', sc: '0.49' }, n6: { st: 'success', sc: '0.58' } },
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68' },               // S6
      n2: { st: 'success', sc: '0.61' }, n4: { st: 'success', sc: '0.22' },
      n5: { st: 'failed' }, n3: { st: 'success', sc: '0.49' }, n6: { st: 'success', sc: '0.58' } },
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68' },               // S7
      n2: { st: 'success', sc: '0.61' }, n4: { st: 'success', sc: '0.22', retire: 1 },
      n5: { st: 'failed' }, n3: { st: 'success', sc: '0.49' }, n6: { st: 'success', sc: '0.58' } },
    { n0: { st: 'success', sc: '0.55' }, n1: { st: 'success', sc: '0.68', best: 1 },      // S8
      n2: { st: 'success', sc: '0.61' }, n4: { st: 'success', sc: '0.22', retire: 1 },
      n5: { st: 'failed' }, n3: { st: 'success', sc: '0.49' }, n6: { st: 'success', sc: '0.58' } }
  ];

  // ---- build DOM ------------------------------------------------------------
  var title = document.createElement('h4'); title.className = 'anim-title'; title.id = 'anim-bfts-title';
  var desc = document.createElement('p'); desc.className = 'anim-desc'; desc.id = 'anim-bfts-desc';

  var svg = el('svg', {
    viewBox: '0 0 ' + VB_W + ' ' + VB_H, class: 'anim-svg',
    preserveAspectRatio: 'xMidYMid meet', role: 'img',
    'aria-labelledby': 'anim-bfts-title anim-bfts-desc'
  });
  var gEdges = el('g', { class: 'anim-edges' });
  var gNodes = el('g', { class: 'anim-nodes' });
  svg.appendChild(gEdges); svg.appendChild(gNodes);

  var edgeEls = {}, nodeEls = {};
  NODES.forEach(function (n) {
    if (n.parent) {
      var p = POS[n.parent];
      var ln = el('line', {
        x1: p.x, y1: p.y, x2: n.x, y2: n.y,
        class: 'anim-edge' + (n.edge === 'dashed' ? ' is-dashed' : '')
      });
      edgeEls[n.id] = ln; gEdges.appendChild(ln);
    }
    var g = el('g', { class: 'anim-node' });
    var ring = el('circle', { cx: n.x, cy: n.y, r: R + 7, class: 'anim-ring' });
    var c = el('circle', { cx: n.x, cy: n.y, r: R, class: 'anim-dot' });
    var lbl = el('text', { x: n.x, y: n.y + 4, class: 'anim-node-label' }); lbl.textContent = n.ab;
    var sc = el('text', { x: n.x, y: n.y + R + 16, class: 'anim-score' });
    g.appendChild(ring); g.appendChild(c); g.appendChild(lbl); g.appendChild(sc);
    nodeEls[n.id] = { g: g, ring: ring, dot: c, score: sc };
    gNodes.appendChild(g);
  });

  var status = document.createElement('p');
  status.className = 'anim-status'; status.id = 'anim-bfts-status';
  status.setAttribute('aria-live', 'polite');

  var controls = document.createElement('div'); controls.className = 'anim-controls';
  controls.innerHTML =
    '<button type="button" class="anim-ctl" data-act="play" data-key-play="anim-ctl-play" data-key-pause="anim-ctl-pause" aria-pressed="false">▶</button>' +
    '<button type="button" class="anim-ctl" data-act="step" data-key="anim-ctl-step">⏭</button>' +
    '<button type="button" class="anim-ctl" data-act="restart" data-key="anim-ctl-restart">↺</button>';

  // legend (HTML, stacks on mobile)
  var legend = document.createElement('ul'); legend.className = 'anim-legend';
  var LG = [
    ['is-success', 'anim-bfts-lg-success'], ['is-failed', 'anim-bfts-lg-failed'],
    ['is-running', 'anim-bfts-lg-running'], ['is-pending', 'anim-bfts-lg-pending']
  ];
  var TY = ['anim-bfts-lg-draft', 'anim-bfts-lg-improve', 'anim-bfts-lg-debug', 'anim-bfts-lg-ablation', 'anim-bfts-lg-validation'];
  var legendItems = [];
  function legendItem(swatchCls, key) {
    var li = document.createElement('li');
    if (!swatchCls) li.className = 'anim-lg-type';
    if (swatchCls) {
      var sw = document.createElement('span'); sw.className = 'anim-swatch ' + swatchCls;
      li.appendChild(sw);
    }
    var lab = document.createElement('span'); li.appendChild(lab);
    legend.appendChild(li); legendItems.push({ lab: lab, key: key });
  }
  LG.forEach(function (p) { legendItem(p[0], p[1]); });
  TY.forEach(function (k) { legendItem(null, k); });

  var caption = document.createElement('p'); caption.className = 'anim-caption'; caption.id = 'anim-bfts-caption';

  root.appendChild(title); root.appendChild(desc); root.appendChild(svg);
  root.appendChild(controls); root.appendChild(status); root.appendChild(legend); root.appendChild(caption);

  // svg title/desc for screen readers
  var svgTitle = el('title', { id: 'anim-bfts-svgt' }); var svgDesc = el('desc', { id: 'anim-bfts-svgd' });
  svg.insertBefore(svgDesc, svg.firstChild); svg.insertBefore(svgTitle, svg.firstChild);

  // ---- render ---------------------------------------------------------------
  function render(i) {
    var step = STEPS[i];
    NODES.forEach(function (n) {
      var p = step[n.id];
      var refs = nodeEls[n.id];
      var edge = edgeEls[n.id];
      if (!p) {
        refs.g.setAttribute('class', 'anim-node is-hidden');
        if (edge) edge.setAttribute('class', 'anim-edge is-hidden' + (n.edge === 'dashed' ? ' is-dashed' : ''));
        return;
      }
      var cls = 'anim-node is-' + p.st;
      if (p.ring) cls += ' has-ring';
      if (p.retire) cls += ' is-retired';
      if (p.best) cls += ' is-best';
      refs.g.setAttribute('class', cls);
      refs.score.textContent = p.sc != null ? p.sc : '';
      var parentVisible = !n.parent || step[n.parent];
      if (edge) edge.setAttribute('class', 'anim-edge' + (n.edge === 'dashed' ? ' is-dashed' : '') + (parentVisible ? '' : ' is-hidden'));
    });
  }

  function refreshText() {
    title.textContent = A.t('anim-bfts-title');
    desc.textContent = A.t('anim-bfts-desc');
    caption.textContent = A.t('anim-bfts-caption');
    svgTitle.textContent = A.t('anim-bfts-title');
    svgDesc.textContent = A.t('anim-bfts-desc');
    legendItems.forEach(function (it) { it.lab.textContent = A.t(it.key); });
  }
  refreshText();

  var p = A.player({
    root: root, steps: STEPS.length, render: render,
    statusEl: status, statusKey: function (i) { return 'anim-bfts-s' + i; },
    controls: controls, autoplay: true, interval: 1700
  });
  A.bindLang(function () { refreshText(); p.refresh(); });
})();
