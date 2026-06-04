/* react.js — ReAct loop inside ONE BFTS node (Pa2).
 * Fidelity (§8.6): the loop ends when a JSON {"status":"success"} appears, NOT
 * after a fixed number of steps; failed steps do not draw a retry arrow; an
 * async HPC poll runs on a separate lane and does NOT consume the step budget
 * (the step counter is held during polling).
 */
(function () {
  if (!window.ARIAnim) return;
  var A = window.ARIAnim, el = A.el;
  var root = document.getElementById('anim-react');
  if (!root) return;

  // state -> { phase: reason|act|observe|poll|done, step, tool, result }
  var STEPS = [
    { phase: '', step: 0 },
    { phase: 'reason', step: 1 },
    { phase: 'act', step: 1, tool: 'survey' },
    { phase: 'observe', step: 1 },
    { phase: 'reason', step: 2 },
    { phase: 'act', step: 2, tool: 'slurm_submit' },
    { phase: 'poll', step: 2 },
    { phase: 'observe', step: 2 },
    { phase: 'until', step: 2 },
    { phase: 'done', step: 2, result: 1 }
  ];

  var title = document.createElement('h4'); title.className = 'anim-title'; title.id = 'anim-react-title';
  var desc = document.createElement('p'); desc.className = 'anim-desc'; desc.id = 'anim-react-desc';

  var svg = el('svg', {
    viewBox: '0 0 480 360', class: 'anim-svg', preserveAspectRatio: 'xMidYMid meet',
    role: 'img', 'aria-labelledby': 'anim-react-title anim-react-desc'
  });
  var svgTitle = el('title', {}); var svgDesc = el('desc', {});
  svg.appendChild(svgTitle); svg.appendChild(svgDesc);

  function box(x, y, w, h, key) {
    var g = el('g', { class: 'rk-box', 'data-phase': key });
    var r = el('rect', { x: x, y: y, width: w, height: h, rx: 10, class: 'rk-rect' });
    var tx = el('text', { x: x + w / 2, y: y + h / 2 + 5, class: 'rk-label' });
    g.appendChild(r); g.appendChild(tx);
    return { g: g, label: tx };
  }
  function arrow(x1, y1, x2, y2, cls) {
    return el('line', { x1: x1, y1: y1, x2: x2, y2: y2, class: 'rk-arrow ' + (cls || '') });
  }

  // node frame
  var nodeRect = el('rect', { x: 20, y: 20, width: 320, height: 320, rx: 14, class: 'rk-node' });
  var nodeLabel = el('text', { x: 30, y: 44, class: 'rk-node-label' });
  var stepLabel = el('text', { x: 330, y: 44, class: 'rk-step', 'text-anchor': 'end' });
  svg.appendChild(nodeRect); svg.appendChild(nodeLabel); svg.appendChild(stepLabel);

  var reason = box(90, 70, 180, 50, 'reason');
  var act = box(90, 160, 180, 50, 'act');
  var toolLabel = el('text', { x: 180, y: 226, class: 'rk-tool', 'text-anchor': 'middle' });
  var observe = box(90, 250, 180, 50, 'observe');
  svg.appendChild(arrow(180, 120, 180, 160));      // reason->act
  svg.appendChild(arrow(180, 210, 180, 250));      // act->observe
  var feedback = el('path', { d: 'M90 275 C 30 250, 30 120, 90 95', class: 'rk-arrow rk-feedback' });
  svg.appendChild(feedback);
  svg.appendChild(reason.g); svg.appendChild(act.g); svg.appendChild(toolLabel); svg.appendChild(observe.g);

  // async poll lane (right, dashed) + result
  var poll = box(360, 160, 100, 50, 'poll');
  poll.g.classList.add('rk-poll');
  svg.appendChild(arrow(270, 185, 360, 185, 'rk-async'));
  svg.appendChild(poll.g);
  var result = box(90, 250, 180, 50, 'done');   // reuses observe slot visually for the JSON
  var resultJson = el('text', { x: 180, y: 332, class: 'rk-json', 'text-anchor': 'middle' });
  svg.appendChild(resultJson);

  var controls = document.createElement('div'); controls.className = 'anim-controls';
  controls.innerHTML =
    '<button type="button" class="anim-ctl" data-act="play" data-key-play="anim-ctl-play" data-key-pause="anim-ctl-pause" aria-pressed="false">▶</button>' +
    '<button type="button" class="anim-ctl" data-act="step" data-key="anim-ctl-step">⏭</button>' +
    '<button type="button" class="anim-ctl" data-act="restart" data-key="anim-ctl-restart">↺</button>';
  var status = document.createElement('p'); status.className = 'anim-status'; status.id = 'anim-react-status';
  status.setAttribute('aria-live', 'polite');

  root.appendChild(title); root.appendChild(desc); root.appendChild(svg);
  root.appendChild(controls); root.appendChild(status);

  var boxes = { reason: reason, act: act, observe: observe, poll: poll };
  function render(i) {
    var s = STEPS[i];
    ['reason', 'act', 'observe', 'poll'].forEach(function (k) {
      boxes[k].g.classList.toggle('is-active', s.phase === k);
    });
    feedback.classList.toggle('is-active', s.phase === 'observe' || s.phase === 'until');
    toolLabel.textContent = s.tool ? (A.t('anim-react-toolcall') + ': ' + s.tool) : '';
    stepLabel.textContent = A.t('anim-react-step') + ' ' + s.step + (s.phase === 'poll' ? ' ⏸' : '');
    resultJson.textContent = s.result ? A.t('anim-react-json') : '';
  }
  function refreshText() {
    title.textContent = A.t('anim-react-title'); desc.textContent = A.t('anim-react-desc');
    svgTitle.textContent = A.t('anim-react-title'); svgDesc.textContent = A.t('anim-react-desc');
    nodeLabel.textContent = A.t('anim-react-node');
    reason.label.textContent = A.t('anim-react-reason');
    act.label.textContent = A.t('anim-react-act');
    observe.label.textContent = A.t('anim-react-observe');
    poll.label.textContent = A.t('anim-react-poll-short');
  }
  refreshText();
  var KMAP = ['anim-react-node', 'anim-react-reason', 'anim-react-act', 'anim-react-feedback',
    'anim-react-reason', 'anim-react-act', 'anim-react-poll', 'anim-react-observe',
    'anim-react-until', 'anim-react-result'];
  var p = A.player({
    root: root, steps: STEPS.length, render: render, statusEl: status,
    statusKey: function (i) { return KMAP[i]; },
    controls: controls, autoplay: true, interval: 1600
  });
  A.bindLang(function () { refreshText(); p.refresh(); render(0); });
})();
