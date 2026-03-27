
// ─────────────── i18n ───────────────
window.I18N = {
  en: {
    // Nav
    nav_home: 'Home', nav_experiments: 'Experiments', nav_monitor: 'Monitor',
    nav_tree: 'Tree', nav_results: 'Results', nav_new: 'New Experiment', nav_settings: 'Settings',
    nav_idea: 'Idea', nav_workflow: 'Workflow',
    // Home
    home_title: 'Welcome to ARI',
    home_subtitle: 'Autonomous Research Intelligence — write a research goal, get a paper.',
    home_total_runs: 'Total Projects', home_best_score: 'Best Review Score', home_total_nodes: 'Total Nodes Explored',
    home_quick_actions: 'Quick Actions', home_latest: 'Latest Experiment',
    active_project: 'ACTIVE PROJECT (RUN)',
    // Experiments
    experiments_title: 'Experiments', experiments_subtitle: 'All ARI experiment projects',
    // Monitor
    monitor_title: 'Pipeline Monitor', monitor_subtitle: 'Real-time experiment progress',
    mon_nodes: 'Nodes Explored', mon_best: 'Best Metric',
    phase_idea: 'Idea', phase_exp: 'Experiment', phase_paper: 'Paper', phase_verify: 'Verify',
    btn_run_paper: 'Run Paper Generation', btn_run_review: 'Run Review / Verify',
    manual_exec: 'MANUAL STAGE EXECUTION',
    // Tree
    tree_title: 'Experiment Tree', tree_subtitle: 'Explore the BFTS node graph',
    // Results
    results_title: 'Results Viewer', results_subtitle: 'Paper quality, figures, and reproducibility',
    paper_title: '📄 Paper', review_scores: '📝 Review Scores',
    // New Experiment wizard
    new_title: 'New Experiment', new_subtitle: 'Set up and launch an ARI experiment',
    wiz_step1: '1. Goal', wiz_step2: '2. Scope', wiz_step3: '3. Resources', wiz_step4: '4. Launch',
    // Settings
    settings_title: 'Settings',
    settings_llm: 'LLM Backend', settings_paper: 'Paper Retrieval', settings_slurm: 'SLURM / HPC Defaults',
    settings_ssh: 'SSH Remote Host', settings_skills: 'Available Skills',
    btn_save: '💾 Save Settings', btn_test_llm: '🔌 Test LLM Connection',
    // Dynamic JS strings (used via t())
    loading: 'Loading…', no_data: 'No data available', select_exp: 'Select an experiment above',
    error_prefix: 'Error: ',
    nodes_explored: 'Nodes Explored', best_metric: 'Best Metric',
    node_tree: 'Node Tree', review_score: 'Review Score', status: 'Status',
    project_id: 'Project ID', date: 'Date', actions: 'Actions',
    abstract: 'Abstract', body: 'Body', overall: 'Overall',
    citations: 'Citations', ok_label: 'OK', issues_label: 'Issues',
    verify_title: '🔬 Verify / Reproducibility',
    exp_context: '⚗️ Experiment Context',
    no_repro: 'No reproducibility report found. Run Review / Verify from Monitor to generate.',
  },
  ja: {
    // Nav
    nav_home: 'ホーム', nav_experiments: '実験一覧', nav_monitor: 'モニター',
    nav_tree: 'ツリー', nav_results: '結果', nav_new: '新規実験', nav_settings: '設定',
    nav_idea: 'アイデア', nav_workflow: 'ワークフロー',
    // Home
    home_title: 'ARI へようこそ',
    home_subtitle: '自律研究知能 — 研究目標を入力するだけで論文が生成されます。',
    home_total_runs: 'プロジェクト数', home_best_score: '最高レビュースコア', home_total_nodes: '探索ノード総数',
    home_quick_actions: 'クイックアクション', home_latest: '最新の実験',
    active_project: 'アクティブプロジェクト',
    // Experiments
    experiments_title: '実験一覧', experiments_subtitle: '全 ARI 実験プロジェクト',
    // Monitor
    monitor_title: 'パイプラインモニター', monitor_subtitle: 'リアルタイム実験進捗',
    mon_nodes: '探索ノード数', mon_best: 'ベストスコア',
    phase_idea: 'アイデア', phase_exp: '実験', phase_paper: '論文', phase_verify: '検証',
    btn_run_paper: '論文生成を実行', btn_run_review: 'レビュー / 検証を実行',
    manual_exec: '手動ステージ実行',
    // Tree
    tree_title: '実験ツリー', tree_subtitle: 'BFTS ノードグラフを探索',
    // Results
    results_title: '結果ビューワー', results_subtitle: '論文品質・図・再現性',
    paper_title: '📄 論文', review_scores: '📝 レビュースコア',
    // New Experiment wizard
    new_title: '新規実験', new_subtitle: 'ARI 実験のセットアップと起動',
    wiz_step1: '1. 目標', wiz_step2: '2. スコープ', wiz_step3: '3. リソース', wiz_step4: '4. 起動',
    // Settings
    settings_title: '設定',
    settings_llm: 'LLM バックエンド', settings_paper: '論文検索', settings_slurm: 'SLURM / HPC デフォルト',
    settings_ssh: 'SSH リモートホスト', settings_skills: '利用可能スキル',
    btn_save: '💾 設定を保存', btn_test_llm: '🔌 LLM 接続テスト',
    // Dynamic JS strings
    loading: '読み込み中…', no_data: 'データなし', select_exp: '上から実験を選択してください',
    error_prefix: 'エラー: ',
    nodes_explored: '探索ノード数', best_metric: 'ベストスコア',
    node_tree: 'ノードツリー', review_score: 'レビュースコア', status: 'ステータス',
    project_id: 'プロジェクト ID', date: '日付', actions: '操作',
    abstract: '要旨', body: '本文', overall: '総合',
    citations: '引用', ok_label: 'OK', issues_label: '問題あり',
    verify_title: '🔬 検証 / 再現性',
    exp_context: '⚗️ 実験コンテキスト',
    no_repro: '再現性レポートがありません。モニターから「レビュー / 検証を実行」で生成できます。',
    // Additional
    monitor_title: 'パイプラインモニター',
    monitor_subtitle: 'リアルタイム実験進捗',
    tree_title: '実験ツリー',
    tree_subtitle: 'BFTS ノードグラフを探索',
    results_title: '結果ビューワー',
    results_subtitle: '論文品質・図・再現性',
    new_title: '新規実験',
    new_subtitle: 'ARI 実験のセットアップと起動',
    experiments_title: '実験一覧',
    experiments_subtitle: '全 ARI 実験プロジェクト',
    manual_exec: '手動ステージ実行',
    node_detail: 'ノード詳細',
    node_description: '説明',
    settings_lang: 'ダッシュボード言語',
    wiz_goal_title: '研究目標を入力してください',
    wiz_scope_title: '実験スコープ',
    wiz_depth_label: '深さ / 予算',
    wiz_quick: 'クイック探索',
    wiz_deep: '詳細調査',
    wiz_env_title: '実行環境',
    wiz_mode_label: '実行モード',
    wiz_launch_title: 'レビューと起動',
    wiz_profile_label: 'プロファイル',
    wiz_save_label: 'ファイル保存先',
    upload_title: 'ファイルアップロード',
    live_logs: 'リアルタイムログ ',
    settings_skills: '利用可能スキル',
    skill_display_name: '表示名',
    skill_label: 'スキル',
    ssh_username: 'ユーザー名',
    s_temperature: 'Temperature',
    s_provider: 'プロバイダー',
    s_model: 'モデル',
    s_partition: 'パーティション',
    s_cpus: 'タスクあたり CPU 数',
    s_walltime: '実行時間上限',
  },
  zh: {
    // Nav
    nav_home: '首页', nav_experiments: '实验列表', nav_monitor: '监控',
    nav_tree: '树图', nav_results: '结果', nav_new: '新建实验', nav_settings: '设置',
    nav_idea: '想法', nav_workflow: '工作流',
    // Home
    home_title: '欢迎使用 ARI',
    home_subtitle: '自主研究智能 — 输入研究目标，自动生成论文。',
    home_total_runs: '项目数', home_best_score: '最高评审分', home_total_nodes: '已探索节点数',
    home_quick_actions: '快捷操作', home_latest: '最新实验',
    active_project: '当前项目',
    // Experiments
    experiments_title: '实验列表', experiments_subtitle: '所有 ARI 实验项目',
    // Monitor
    monitor_title: '流水线监控', monitor_subtitle: '实时实验进度',
    mon_nodes: '已探索节点', mon_best: '最佳指标',
    phase_idea: '想法', phase_exp: '实验', phase_paper: '论文', phase_verify: '验证',
    btn_run_paper: '运行论文生成', btn_run_review: '运行评审 / 验证',
    manual_exec: '手动执行阶段',
    // Tree
    tree_title: '实验树', tree_subtitle: '探索 BFTS 节点图',
    // Results
    results_title: '结果查看器', results_subtitle: '论文质量、图表与可重复性',
    paper_title: '📄 论文', review_scores: '📝 评审分数',
    // New Experiment wizard
    new_title: '新建实验', new_subtitle: '配置并启动 ARI 实验',
    wiz_step1: '1. 目标', wiz_step2: '2. 范围', wiz_step3: '3. 资源', wiz_step4: '4. 启动',
    // Settings
    settings_title: '设置',
    settings_llm: 'LLM 后端', settings_paper: '论文检索', settings_slurm: 'SLURM / HPC 默认',
    settings_ssh: 'SSH 远程主机', settings_skills: '可用技能',
    settings_lang: '界面语言',
    btn_save: '💾 保存设置', btn_test_llm: '🔌 测试 LLM 连接',
    // Dynamic
    loading: '加载中…', no_data: '暂无数据', select_exp: '请从上方选择实验',
    error_prefix: '错误：',
    nodes_explored: '已探索节点', best_metric: '最佳指标',
    node_tree: '节点树', review_score: '评审分数', status: '状态',
    project_id: '项目 ID', date: '日期', actions: '操作',
    abstract: '摘要', body: '正文', overall: '总分',
    citations: '引用', ok_label: 'OK', issues_label: '有问题',
    verify_title: '🔬 验证 / 可重复性',
    exp_context: '⚗️ 实验上下文',
    no_repro: '未找到可重复性报告。请在监控页面运行「评审 / 验证」以生成。',
    // Additional
    node_detail: '节点详情',
    node_description: '描述', wiz_goal_title: '描述您的研究目标',
    wiz_scope_title: '实验范围', wiz_depth_label: '深度 / 预算',
    wiz_quick: '快速探索', wiz_deep: '深度调研',
    wiz_env_title: '执行环境', wiz_mode_label: '执行模式',
    wiz_launch_title: '审查并启动', wiz_profile_label: '配置文件',
    wiz_save_label: '保存实验文件至', upload_title: '上传文件',
    live_logs: '实时日志 ',
    skill_display_name: '显示名称', skill_label: '技能',
    ssh_username: '用户名', s_temperature: '温度',
    s_provider: '提供商', s_model: '模型',
    s_partition: '分区', s_cpus: '每任务 CPU 数', s_walltime: '最长运行时间',
  }
};

window.currentLang = localStorage.getItem('ari_lang') || 'ja';

function t(key) {
  if(!window.I18N) return key;
  var lang = window.currentLang || localStorage.getItem("ari_lang") || "en";
  var d = window.I18N[lang] || window.I18N.en || {};
  return d[key] || (window.I18N.en||{})[key] || key;
}

function applyLanguage(lang) {
  currentLang = lang || localStorage.getItem('ari_lang') || 'en';
  localStorage.setItem('ari_lang', currentLang);
  var d = I18N[currentLang] || I18N.en;
  // Nav items
  var navMap = {home:'nav_home',experiments:'nav_experiments',monitor:'nav_monitor',
    tree:'nav_tree',results:'nav_results',new:'nav_new',settings:'nav_settings'};
  document.querySelectorAll('.nav-item[data-page]').forEach(function(el){
    var k = navMap[el.dataset.page];
    if(k && d[k]) el.childNodes[el.childNodes.length-1].textContent = ' ' + d[k];
  });
  // Static text elements by ID
  var elemMap = {
    'home-stat-label-runs': 'home_total_runs',
    'home-stat-label-score': 'home_best_score',
    'home-stat-label-nodes': 'home_total_nodes',
  };
  Object.keys(elemMap).forEach(function(id){
    var el = document.getElementById(id);
    if(el) el.textContent = d[elemMap[id]] || el.textContent;
  });
  // All data-i18n elements
  document.querySelectorAll('[data-i18n]').forEach(function(el){
    var k = el.getAttribute('data-i18n');
    if(d[k]) el.textContent = d[k];
  });
  // Active project label
  var apLabel = document.querySelector('.active-project-label');
  if(apLabel) apLabel.textContent = d['active_project'] || 'ACTIVE PROJECT (RUN)';
  // Update select to match saved
  var sel = document.getElementById('s-lang');
  if(sel) sel.value = currentLang;
  var note = document.getElementById('lang-note');
  if(note) note.textContent = currentLang==='ja' ? '言語を切り替えました' : currentLang==='zh' ? '语言已切换' : 'Language switched';
}

// Apply on load
document.addEventListener('DOMContentLoaded', function(){ applyLanguage(currentLang); });

(function initTreeDrag(){
  var wrap = document.getElementById('tree-pan-wrapper');
  if(!wrap) return;
  var startX=0, startY=0, scrollL=0, scrollT=0, active=false, moved=false;
  function onDown(cx,cy){ active=true; moved=false; startX=cx; startY=cy; scrollL=wrap.scrollLeft; scrollT=wrap.scrollTop; wrap.style.cursor='grabbing'; }
  function onMove(cx,cy){ if(!active) return; var dx=cx-startX,dy=cy-startY; if(Math.abs(dx)+Math.abs(dy)>3) moved=true; wrap.scrollLeft=scrollL-dx; wrap.scrollTop=scrollT-dy; }
  function onUp(){ active=false; wrap.style.cursor='grab'; }
  wrap.addEventListener('mousedown',function(e){ if(e.button!==0) return; onDown(e.clientX,e.clientY); e.preventDefault(); });
  document.addEventListener('mousemove',function(e){ if(active) onMove(e.clientX,e.clientY); });
  document.addEventListener('mouseup',onUp);
  wrap.addEventListener('click',function(e){ if(moved){e.stopPropagation();moved=false;} },true);
  wrap.addEventListener('touchstart',function(e){ if(e.touches.length!==1) return; onDown(e.touches[0].clientX,e.touches[0].clientY); },{passive:true});
  wrap.addEventListener('touchmove',function(e){ if(e.touches.length!==1) return; e.preventDefault(); onMove(e.touches[0].clientX,e.touches[0].clientY); },{passive:false});
  wrap.addEventListener('touchend',onUp);
  var canvas=document.getElementById('tree-canvas');
  if(canvas){ canvas.style.minWidth='0'; canvas.style.width='max-content'; }
})();

// ─────────────── State ───────────────
var WS_PORT = location.port ? parseInt(location.port)+1 : 8766;
var ws = null, nodesData = [], selectedNode = null;
var wizState = {step:1, mode:'laptop', llm:'openai', scopeVal:2};
var _collapsed = {};

// ─────────────── Router ───────────────
function goto(page) {
  // Hide ALL pages explicitly (handles inline styles too)
  document.querySelectorAll('.page').forEach(p=>{
    p.classList.remove('active');
    p.style.display = 'none';
  });
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  var el = document.getElementById('page-'+page);
  if(el){
    el.classList.add('active');
    el.style.display = (page==='tree') ? 'flex' : 'block';
  }
  var nav = document.querySelector('[data-page="'+page+'"]');
  if(nav) nav.classList.add('active');
  location.hash = '/'+page;
  if(page==='experiments') loadExperiments();
  if(page==='home') loadHome();
  if(page==='results') { populateResultsDropdown().then(loadResults); }
  if(page==='settings') { loadSettings(); loadSettingsProjects(); }
  if(page==='monitor') { connectWS(); initGpuMonitorVisibility(); }
  if(page==='tree') { connectWS(); setTimeout(renderTreeD3, 150); }
  if(page==='new' && wizState.step===3) detectScheduler();
  if(page==='workflow') loadWorkflow();
  if(page==='idea') loadIdeaPage();
}

document.querySelectorAll('.nav-item').forEach(item=>{
  item.addEventListener('click', ()=>goto(item.dataset.page));
});

// Init route
window.addEventListener('load', ()=>{
  var h = location.hash.replace('#/','') || 'home';
  goto(h);
  setTimeout(loadProjectList, 300);
});
window.addEventListener('hashchange', ()=>{
  var h = location.hash.replace('#/','') || 'home';
  goto(h);
});

// ─────────────── WebSocket ───────────────
function initGpuMonitorVisibility(){
  // GPU monitor card is hidden by default.
  // Only show it when user clicks "Show GPU Monitor" button in the Experiment Control card.
  // We just detect SLURM availability to show/hide the "Show GPU Monitor" button.
  fetch('/api/scheduler/detect').then(r=>r.json()).then(function(d){
    var hasSlurm = d && d.scheduler && d.scheduler !== 'none';
    var btn = document.getElementById('btn-show-gpu-monitor');
    if(btn) btn.style.display = hasSlurm ? '' : 'none';
  }).catch(function(){
    var btn = document.getElementById('btn-show-gpu-monitor');
    if(btn) btn.style.display = 'none';
  });
}
function toggleGpuMonitorCard(){
  var card = document.getElementById('gpu-monitor-card');
  if(!card) return;
  var visible = card.style.display !== 'none';
  card.style.display = visible ? 'none' : '';
  var btn = document.getElementById('btn-show-gpu-monitor');
  if(btn) btn.textContent = visible ? '🖥 GPU Monitor' : '✕ GPU Monitor を非表示';
  if(!visible) gpuMonitorRefresh();
}
function connectWS() {
  if(ws && ws.readyState < 2) return;
  ws = new WebSocket('ws://'+location.hostname+':'+WS_PORT+'/ws');
  ws.onmessage = e => {
    try {
      var msg = JSON.parse(e.data);
      if(msg.type==='update' && msg.data) {
        nodesData = msg.data.nodes || [];
        renderTree();
        renderMonitorTree();
        updateMonitorStats();
      }
    } catch(ex){}
  };
  ws.onopen = ()=>{ document.getElementById('log-status').className='badge badge-green'; document.getElementById('log-status').textContent='connected'; };
  ws.onclose = ()=>{
    var el=document.getElementById('log-status');
    if(el){el.className='badge badge-muted'; el.textContent='disconnected';}
    // Auto-reconnect after 5s
    setTimeout(function(){ connectWS(); }, 5000);
  };
}

// Also poll /state on load
fetch('/state').then(r=>r.json()).then(d=>{
  if(d){ window._stateCache = d;
        // Update running indicator
        var ri=document.getElementById('run-indicator');
        var ii=document.getElementById('idle-indicator');
        if(ri&&ii){
          var isRun=!!d.running_pid;
          ri.style.display=isRun?'':'none';
          ii.style.display=isRun?'none':'';
        }
        updatePhaseStepper(d);
  var mb=document.getElementById('mon-model-badge');
  if(mb){var m=d.llm_model_actual||(Object.values(d.actual_models||{}).filter((v,i,a)=>a.indexOf(v)===i).join(', '))||'—'; mb.textContent='model: '+m;}
  var sb=document.getElementById('run-status-badge');
  if(sb){var isR=!!d.running_pid; sb.textContent=d.status_label||(isR?'🟢 Running':'⬛ Stopped'); sb.className='badge '+(isR?'badge-green':'');}
        // Update running indicator
        var ri=document.getElementById('run-indicator');
        var ii=document.getElementById('idle-indicator');
        if(ri&&ii){
          var isRun=!!d.running_pid;
          ri.style.display=isRun?'':'none';
          ii.style.display=isRun?'none':'';
        } updateIdeaCard(d); }
  if(d && d.nodes){ nodesData=d.nodes; renderTree(); renderMonitorTree(); updateMonitorStats(); }
}).catch(()=>{});

// ─────────────── HOME ───────────────
async function loadHome() {
  var r = await fetch('/api/checkpoints').then(function(res){return res.json();}).catch(function(){return [];});
  document.getElementById('home-total-runs').textContent = r.length || 0;
  var totalNodes = 0;
  var bestScore = null;
  for(var i=0;i<r.length;i++){
    totalNodes += r[i].node_count || 0;
    var sc = r[i].review_score;
    if(sc!=null && (bestScore===null || sc>bestScore)) bestScore=sc;
  }
  document.getElementById('home-total-nodes').textContent = totalNodes;
  document.getElementById('home-best-score').textContent = bestScore!==null ? bestScore.toFixed(1) : '—';
  var latestEl = document.getElementById('home-latest');
  var latest = r[0];
  if(latest) {
    latestEl.innerHTML = '<div style="font-size:.85rem;line-height:1.8">'
      +'<div>ID: <strong>'+latest.id+'</strong></div>'
      +'<div>Nodes: <strong>'+latest.node_count+'</strong></div>'
      +'<div>Score: <strong>'+(latest.review_score!=null?latest.review_score:'—')+'</strong></div>'
      +'<div>Status: '+statusBadge(latest.status)+'</div>'
      +'<div style="margin-top:10px;display:flex;gap:8px">'
        +'<button class="btn btn-outline btn-sm" onclick="goto(\'results\')">View Results →</button>'
        +'<button class="btn btn-outline btn-sm" onclick="goto(\'tree\')">View Tree →</button>'
      +'</div>'
      +'</div>';
  } else {
    latestEl.innerHTML='<div class="empty-state" style="padding:20px"><p>No experiments yet</p></div>';
  }
}

// ─/ ─────────────── EXPERIMENTS ───────────────
async function loadExperiments() {
  var r = await fetch('/api/checkpoints').then(r=>r.json()).catch(()=>[]);
  var wrap = document.getElementById('exp-table-wrap');
  if(!r.length){ wrap.innerHTML='<div class="empty-state"><div class="empty-icon">🗂️</div><p>No experiments found</p></div>'; return; }
  var rows = r.map(c=>{
    var d = new Date(c.mtime*1000).toLocaleString();
    return '<tr>'
      +'<td><code style="font-size:.8rem">'+c.id.slice(0,14)+'</code></td>'
      +'<td>'+statusBadge(c.status)+'</td>'
      +'<td>'+c.node_count+'</td>'
      +'<td>'+(c.review_score!=null?'<strong>'+c.review_score+'</strong>':'—')+'</td>'
      +'<td style="color:var(--muted);font-size:.8rem">'+d+'</td>'
      +'<td><div style="display:flex;gap:6px">'
        +'<button class="btn btn-outline btn-sm" onclick="viewResults(\''+c.id+'\')">Results</button>'
        +'<button class="btn btn-outline btn-sm" onclick="viewTree(\''+c.id+'\')">Tree</button>'
        +'</div></td>'
      +'</tr>';
  }).join('');
  wrap.innerHTML='<table><thead><tr><th>Project ID</th><th>Status</th><th>BFTS Nodes</th><th>Review Score</th><th>Date</th><th>Actions</th></tr></thead><tbody>'+rows+'</tbody></table>';
}

function viewResults(id){
  document.getElementById('results-ckpt-select').value=id;
  goto('results');
  loadResults();
}
function viewTree(id){
  // Load specific checkpoint tree
  fetch('/api/checkpoint/'+id+'/summary').then(r=>r.json()).then(d=>{
    if(d.nodes_tree && d.nodes_tree.nodes) nodesData=d.nodes_tree.nodes;
    goto('tree');
    setTimeout(renderTree,100);
  });
}

function statusBadge(s){
  if(s==='running') return '<span class="badge badge-yellow">⏳ Running</span>';
  if(s==='completed') return '<span class="badge badge-green">✓ Done</span>';
  if(s==='failed') return '<span class="badge badge-red">✗ Failed</span>';
  return '<span class="badge badge-muted">'+s+'</span>';
}

// ─────────────── MONITOR ───────────────
function updateMonitorStats(){
  gpuMonitorRefresh();
  document.getElementById('mon-node-count').textContent = nodesData.length;
  // Collect all numeric metrics across nodes
  var metricMap = {};
  nodesData.forEach(function(n){
    var m = n.metrics || {};
    Object.keys(m).forEach(function(k){
      if(typeof m[k]==='number' && !k.startsWith('_')) {
        if(!metricMap[k]) metricMap[k] = [];
        metricMap[k].push(m[k]);
      }
    });
  });
  var metricKeys = Object.keys(metricMap);
  var bestEl = document.getElementById('mon-best-metric');
  if(metricKeys.length===0){
    // fallback: scientific_score
    var scores = nodesData.map(function(n){return n.scientific_score||n.metrics&&n.metrics._scientific_score||0;});
    var best = scores.length ? Math.max.apply(null,scores) : 0;
    bestEl.textContent = best>0 ? best.toFixed(3) : '—';
    bestEl.title = 'scientific_score';
  } else {
    // Find key with highest max value (prefer GFlops, GB/s, accuracy etc.)
    var preferred = ['GFlops/s','GB/s','GFLOP/s','accuracy','f1','score'];
    var bestKey = metricKeys[0];
    preferred.forEach(function(p){ if(metricMap[p]) bestKey=p; });
    var bestVal = Math.max.apply(null, metricMap[bestKey]);
    // Show ALL non-score metrics as mini list
    var displayKeys = metricKeys.filter(function(k){return !['_scientific_score'].includes(k);}).slice(0,4);
    if(displayKeys.length > 1){
      bestEl.innerHTML = displayKeys.map(function(k){
        var v = Math.max.apply(null,metricMap[k]);
        var vs = v > 100 ? v.toFixed(0) : v.toFixed(2);
        return '<div style="line-height:1.3"><span style="font-size:.65rem;color:var(--muted)">'+k+'</span><br><strong style="font-size:.85rem">'+vs+'</strong></div>';
      }).join('');
      bestEl.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:.8rem';
    } else {
      bestEl.textContent = bestVal.toFixed(1);
      bestEl.title = bestKey;
    }
  }

  // Phase detection
  var statuses = nodesData.map(n=>n.status||'');
  // Phase status from checkpoint files (injected by server into /state)
  var hasPaper = window._stateCache && window._stateCache.has_paper;
  var hasPDF = window._stateCache && window._stateCache.has_pdf;
  var hasReview = window._stateCache && window._stateCache.has_review;
  var hasRepro = window._stateCache && window._stateCache.has_repro;
  var hasExp = nodesData.length > 1;
  var anyRunning = nodesData.some(function(n){return n.status==='running';});
  // phase classes
  var phaseMap = {
    idea: 'done',
    experiment: 'done',
    paper: (hasPaper||hasReview||hasRepro) ? 'done' : '',
    verify: hasRepro ? 'done' : hasReview ? 'active' : ''
  };
  ['idea','experiment','paper','verify'].forEach(function(p){
    var el = document.getElementById('phase-'+p);
    if(el) el.className = 'phase' + (phaseMap[p] ? ' '+phaseMap[p] : '');
  });
  // Update cost display
  var costEl = document.getElementById('mon-cost');
  if(costEl && window._stateCache && window._stateCache.cost){
    var c = window._stateCache.cost;
    var usd = c.total_cost_usd;
    var tokens = c.total_tokens;
    costEl.textContent = usd != null ? '$'+usd.toFixed(2) : '—';
    costEl.title = tokens != null ? (tokens/1000).toFixed(0)+'K tokens | '+c.call_count+' calls' : '';
  }
}

function renderMonitorTree(){
  var canvas = document.getElementById('tree-canvas-monitor');
  if(!canvas) return;
  canvas.innerHTML = buildTreeHTML(nodesData, true);
}

// ─────────────── TREE ───────────────
function renderTree(){
  var canvas = document.getElementById('tree-canvas');
  if(!canvas) return;
  var filterStatus = document.getElementById('tree-filter-status')?.value||'';
  var filterDepth = document.getElementById('tree-filter-depth')?.value||'';
  var nodes = nodesData;
  if(filterStatus) nodes=nodes.filter(n=>(n.status||'')==filterStatus);
  if(filterDepth!==''){
    var fd=parseInt(filterDepth);
    if(fd===3) nodes=nodes.filter(n=>(n.depth||0)>=3);
    else nodes=nodes.filter(n=>(n.depth||0)===fd);
  }
  canvas.innerHTML = buildTreeHTML(nodes, false);

  // Attach drag + click listeners via addEventListener (more reliable than onXxx=)
  canvas.querySelectorAll('.tree-node[data-node-id]').forEach(function(nodeEl){
    var nodeId = nodeEl.getAttribute('data-node-id');
    nodeEl.setAttribute('draggable','false');
    nodeEl.addEventListener('mousedown', function(e){
      if(e.button!==0) return;
      startNodeDrag(e, nodeId, nodeEl);
    });
    nodeEl.addEventListener('click', function(e){
      if(!window._nodeDragged) selectNode(nodeId);
    });
    // Prevent browser HTML5 drag from stealing events
    nodeEl.addEventListener('dragstart', function(e){ e.preventDefault(); });
  });

  // Auto-scroll to center root node
  setTimeout(function(){
    var wrapper = document.getElementById('tree-pan-wrapper');
    var pm = window._treePosMap||{};
    var rootNode = nodes.find(function(n){return !n.parent_id;});
    if(wrapper && rootNode && pm[rootNode.id]){
      var rootX = pm[rootNode.id].x;
      var nw = window._treeNW||150;
      var target = rootX + nw/2 - wrapper.clientWidth/2;
      wrapper.scrollLeft = Math.max(0, target);
    }
  }, 60);
}

function buildTreeHTML(nodes, compact) {
  if (!nodes || !nodes.length) return '<div style="color:var(--muted);padding:20px;text-align:center">No nodes yet</div>';
  var childMap = {};
  nodes.forEach(function(n) {
    var pid = n.parent_id || null;
    if (!childMap[pid]) childMap[pid] = [];
    childMap[pid].push(n);
  });
  var SC = {success:'#22c55e',failed:'#ef4444',running:'#3b82f6',pending:'#f59e0b'};
  var LC = {draft:'#8b5cf6',debug:'#06b6d4',ablation:'#f59e0b',validation:'#10b981',improve:'#ec4899'};
  var unit = compact ? 14 : 20;

  // render(node, prefix, isLast) - prefix is array of "connector" strings for parent levels
  function render(n, prefix, isLast) {
    var sc = SC[n.status] || '#888';
    var lc = LC[n.label] || '#888';
    var sid = (n.id || '').slice(-8);
    var lbl = n.label || '?';
    var nm = escHtml((n.name || sid).slice(0, compact ? 48 : 80));
    var score = (n.score !== undefined && n.score !== null) ? ' <span style="color:#22c55e;font-size:.68rem">'+n.score+'</span>' : '';

    // Build the connector prefix string from parent levels
    var prefixHtml = prefix.map(function(p) {
      return '<span style="display:inline-block;width:'+unit+'px;color:#444;font-family:monospace;font-size:.75rem;flex-shrink:0">'+p+'</span>';
    }).join('');
    // Current node connector
    var connector = isLast ? '└─ ' : '├─ ';
    var connHtml = prefix.length > 0
      ? '<span style="display:inline-block;width:'+unit+'px;color:#444;font-family:monospace;font-size:.75rem;flex-shrink:0">'+connector+'</span>'
      : '';

    var div = '<div class="tree-node-row" data-nid="' + escHtml(n.id) + '" '
      + 'onclick="selectNode(this.dataset.nid)" '
      + 'style="display:flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;cursor:pointer;min-height:24px">'
      + prefixHtml + connHtml
      + '<span style="width:7px;height:7px;border-radius:50%;background:'+sc+';flex-shrink:0;display:inline-block"></span>'
      + '<span style="background:'+lc+'22;color:'+lc+';border:1px solid '+lc+'44;border-radius:3px;font-size:.64rem;padding:0 4px;flex-shrink:0;white-space:nowrap">'+escHtml(lbl)+'</span>'
      + '<span style="font-family:monospace;color:var(--muted);font-size:.68rem;flex-shrink:0">'+escHtml(sid)+'</span>'
      + '<span style="font-size:.75rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+nm+'</span>'
      + score
      + '</div>';

    var children = childMap[n.id] || [];
    children.forEach(function(c, i) {
      var childIsLast = (i === children.length - 1);
      // Child prefix: extend current prefix with '│ ' if not last, or '  ' if last
      var childPrefix = prefix.concat([isLast ? '  ' : '│ ']);
      div += render(c, childPrefix, childIsLast);
    });
    return div;
  }

  var roots = childMap[null] || nodes.filter(function(n) { return !n.parent_id; });
  var html = '<div style="font-family:monospace">';
  roots.forEach(function(r, i) {
    var isLast = (i === roots.length - 1);
    html += render(r, [], isLast);
  });
  html += '</div>';
  return html;
}
function _updateEdge(nodeId){
  // Update all edges connected to this node (as child or parent)
  var posMap = window._treePosMap||{};
  var NW = window._treeNW||180, NH = window._treeNH||72;
  var EDGE_COL={draft:'#3b82f6',improve:'#8b5cf6',ablation:'#f59e0b',debug:'#ef4444',validation:'#10b981'};

  function getPos(id){
    return _nodePosOverrides[id] || posMap[id] || null;
  }
  function drawEdge(n, edgeEl){
    if(!n.parent_id) return;
    var p=getPos(n.parent_id), c=getPos(n.id);
    if(!p||!c||!edgeEl) return;
    var px=p.x+NW/2, py=p.y+NH;
    var cx=c.x+NW/2, cy=c.y;
    var midY=(py+cy)/2;
    edgeEl.setAttribute('d','M'+px+','+py+' C'+px+','+midY+' '+cx+','+midY+' '+cx+','+cy);
  }
  // Find nodes where this node is child or parent
  if(!nodesData) return;
  nodesData.forEach(function(n){
    if(n.id===nodeId||n.parent_id===nodeId){
      var edgeEl = document.getElementById('edge-'+n.id);
      drawEdge(n, edgeEl);
    }
  });
}

function startNodeDrag(e, nodeId, thisEl){
  if(e.button!==0) return;
  var posMap = window._treePosMap||{};
  var cur = _nodePosOverrides[nodeId]||posMap[nodeId]||{x:0,y:0};
  // nodeEl is passed directly from addEventListener
  var nodeEl = thisEl;
  if(!nodeEl) return;

  // Capture scroll offset at drag start (clientX is viewport; node.left is canvas-relative)
  var wrapper = document.getElementById('tree-pan-wrapper');
  var startScrollX = wrapper ? wrapper.scrollLeft : 0;
  var startScrollY = wrapper ? wrapper.scrollTop  : 0;
  var startMouseX = e.clientX + startScrollX;
  var startMouseY = e.clientY + startScrollY;
  var startX = cur.x, startY = cur.y;

  window._nodeDragged = false;
  nodeEl.style.zIndex='100';
  nodeEl.style.cursor='grabbing';

  function onMove(ev){
    // Account for current scroll (user may scroll while dragging)
    var scrollX = wrapper ? wrapper.scrollLeft : 0;
    var scrollY = wrapper ? wrapper.scrollTop  : 0;
    var mouseCanvasX = ev.clientX + scrollX;
    var mouseCanvasY = ev.clientY + scrollY;
    var dx = mouseCanvasX - startMouseX;
    var dy = mouseCanvasY - startMouseY;
    if(Math.abs(dx)+Math.abs(dy)>3) window._nodeDragged=true;
    var nx = startX + dx, ny = startY + dy;
    nodeEl.style.left = nx+'px';
    nodeEl.style.top  = ny+'px';
    _nodePosOverrides[nodeId] = {x:nx, y:ny};
    _updateEdge(nodeId);
  }
  function onUp(){
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup',   onUp);
    nodeEl.style.zIndex='1';
    nodeEl.style.cursor='pointer';
    setTimeout(function(){ window._nodeDragged=false; },100);
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup',   onUp);
  e.preventDefault();
  e.stopPropagation();
}



function selectNode(nodeId){
  if(!nodesData) return;
  var n = nodesData.find(function(x){ return x.id === nodeId; });
  if(!n) return;

  // Highlight selected node
  document.querySelectorAll('.tree-node.selected').forEach(function(el){ el.classList.remove('selected'); });
  var el = document.querySelector('.tree-node[data-node-id="'+nodeId+'"]');
  if(el) el.classList.add('selected');

  // Open detail panel
  var panel = document.getElementById('detail-panel');
  var content = document.getElementById('detail-content');
  if(!panel || !content) return;
  panel.classList.add('open');

  var EDGE_COL={draft:'#3b82f6',improve:'#8b5cf6',ablation:'#f59e0b',debug:'#ef4444',validation:'#10b981'};
  var lbl = (n.label||n.node_type||'').toLowerCase();
  var col = EDGE_COL[lbl]||'var(--muted)';
  var m = n.metrics || {};
  var mKeys = Object.keys(m).filter(function(k){ return !k.startsWith('_'); });
  var score = n.scientific_score || m._scientific_score || null;

  var html = '<div style="padding:2px 0 10px">';
  // Status + score badges
  html += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">';
  if(n.status) html += '<span class="badge badge-'+(n.status==='success'?'green':n.status==='running'?'blue':n.status==='failed'?'red':'muted')+'">'+n.status+'</span>';
  if(n.depth!=null) html += '<span class="badge badge-muted">depth: '+n.depth+'</span>';
  if(score!=null) html += '<span class="badge badge-blue">score: '+score.toFixed(3)+'</span>';
  if(n.has_real_data) html += '<span class="badge badge-green">real data</span>';
  html += '</div>';

  // ID + Label
  html += '<div class="detail-field"><div class="detail-key">ID</div><div class="detail-val" style="font-family:monospace;font-size:.75rem">'+escHtml(n.id)+'</div></div>';
  html += '<div class="detail-field"><div class="detail-key">LABEL</div><div class="detail-val"><strong style="color:'+col+'">'+escHtml(lbl||'—')+'</strong></div></div>';

  // Eval / hypothesis
  var evalText = n.eval_summary || n.hypothesis || n.description || n.name || '';
  if(evalText){
    html += '<div class="detail-field"><div class="detail-key">📝 EVAL / HYPOTHESIS</div>';
    html += '<div class="detail-val" style="white-space:pre-wrap;max-height:180px;overflow:auto;font-size:.78rem">'+escHtml(String(evalText))+'</div></div>';
  }

  // Metrics table
  if(mKeys.length){
    html += '<div class="detail-field"><div class="detail-key">📊 METRICS</div><div class="detail-val">';
    html += '<table style="width:100%;border-collapse:collapse;font-size:.8rem">';
    mKeys.forEach(function(k){
      var v = m[k]; var vs = typeof v==='number'?v.toFixed(4):JSON.stringify(v);
      html += '<tr><td style="color:var(--muted);padding:2px 8px 2px 0">'+escHtml(k)+'</td><td><strong>'+escHtml(vs)+'</strong></td></tr>';
    });
    html += '</table></div></div>';
  }

  // Error
  if(n.error_log){
    html += '<div class="detail-field"><div class="detail-key" style="color:var(--red)">❌ ERROR</div>';
    html += '<div class="detail-val"><pre class="code" style="max-height:100px;overflow:auto;color:var(--red);font-size:.72rem">'+escHtml(String(n.error_log).slice(0,800))+'</pre></div></div>';
  }

  // Timestamps
  if(n.created_at||n.completed_at){
    html += '<div style="font-size:.72rem;color:var(--muted);margin-top:6px">';
    if(n.created_at) html += 'Created: '+new Date(n.created_at*1000).toLocaleString()+'  ';
    if(n.completed_at) html += 'Done: '+new Date(n.completed_at*1000).toLocaleString();
    html += '</div>';
  }

  // Tabs (MCP Trace / Raw)
  var tabId = 'dt-'+nodeId.slice(-8);
  html += '</div>';
  html += '<div id="'+tabId+'" style="margin-top:6px">';
  html += '<div style="display:flex;gap:4px;margin-bottom:6px;flex-wrap:wrap">';
  html += '<button onclick="switchNodeTab(\''+tabId+'\',\'overview\')" id="'+tabId+'-btn-overview" style="background:rgba(255,255,255,.12);border:1px solid var(--border);color:var(--text);padding:3px 10px;border-radius:5px;cursor:pointer;font-size:.75rem">📋 Overview</button>';
  if(n.trace_log&&n.trace_log.length) html += '<button onclick="switchNodeTab(\''+tabId+'\',\'trace\')" id="'+tabId+'-btn-trace" style="background:none;border:1px solid var(--border);color:var(--muted);padding:3px 10px;border-radius:5px;cursor:pointer;font-size:.75rem">🔧 MCP Trace ('+n.trace_log.length+')</button>';
  html += '<button onclick="switchNodeTab(\''+tabId+'\',\'raw\')" id="'+tabId+'-btn-raw" style="background:none;border:1px solid var(--border);color:var(--muted);padding:3px 10px;border-radius:5px;cursor:pointer;font-size:.75rem">{ } Raw</button>';
  html += '</div>';
  html += '<div id="'+tabId+'-overview" style="display:block"></div>';
  if(n.trace_log&&n.trace_log.length){
    var ECOL={draft:'#3b82f6',improve:'#8b5cf6',ablation:'#f59e0b',debug:'#ef4444',validation:'#10b981'};
    var toolNames=[];
    (n.trace_log||[]).forEach(function(t){var s=typeof t==='string'?t:JSON.stringify(t);var mm=s.match(/^[→>]\s*(\w+)\(/);if(mm&&toolNames.indexOf(mm[1])<0)toolNames.push(mm[1]);});
    var trHtml='<div style="margin-bottom:6px;display:flex;flex-wrap:wrap;gap:4px">';
    toolNames.forEach(function(tn){trHtml+='<span style="font-size:.7rem;padding:1px 7px;border-radius:6px;background:rgba(59,130,246,.15);color:#60a5fa">'+tn+'</span>';});
    trHtml+='</div>';
    trHtml+='<pre class="code" style="max-height:300px;overflow:auto;font-size:.7rem;line-height:1.4">';
    (n.trace_log||[]).forEach(function(t){var s=typeof t==='string'?t:JSON.stringify(t,null,2);var col=s.startsWith('→')||s.startsWith('->')?'#60a5fa':s.startsWith('  ←')||s.startsWith('  <-')?'#86efac':'inherit';trHtml+='<span style="color:'+col+'">'+escHtml(s)+'</span>\n';});
    trHtml+='</pre>';
    html += '<div id="'+tabId+'-trace" style="display:none">'+trHtml+'</div>';
  }
  // Code tab: extract run_code snippets from trace_log
  var codeSnippets=[];
  (n.trace_log||[]).forEach(function(t){
    var s=typeof t==='string'?t:JSON.stringify(t);
    // Match run_code calls with code argument
    var m=s.match(/→\s*run_code\((.+)/);
    if(m){
      try{
        var arg=JSON.parse(m[1].replace(/\)$/,'').trim());
        if(arg.code) codeSnippets.push(arg.code);
      }catch(e){
        var cm=s.match(/"code":\s*"((?:[^"\\]|\\[\s\S])*?)"/);
        if(cm){ try{ codeSnippets.push(JSON.parse('"'+cm[1]+'"')); }catch(e2){ codeSnippets.push(cm[1].replace(/\\n/g,'\n')); } }
      }
    }
  });
  if(codeSnippets.length){
    html += '<button onclick="switchNodeTab(\''+tabId+'\',\'code\')" id="'+tabId+'-btn-code" style="background:none;border:1px solid var(--border);border-radius:6px;padding:2px 10px;font-size:.75rem;cursor:pointer;color:var(--muted)">💻 Code ('+codeSnippets.length+')</button>';
    var cHtml='';
    codeSnippets.forEach(function(c,i){
      cHtml+='<div style="font-size:.72rem;color:var(--muted);margin:6px 0 2px">--- Snippet '+(i+1)+' / '+codeSnippets.length+' ---</div>';
      cHtml+='<pre class="code" style="max-height:400px;overflow:auto;font-size:.72rem;line-height:1.5;margin-bottom:8px">'+escHtml(c)+'</pre>';
    });
    html += '<div id="'+tabId+'-code" style="display:none">'+cHtml+'</div>';
  }
  html += '<div id="'+tabId+'-raw" style="display:none"><pre class="code" style="max-height:350px;overflow:auto;font-size:.68rem">'+escHtml(JSON.stringify(n,null,2).slice(0,6000))+'</pre></div>';
  html += '</div>';

  content.innerHTML = html;
  switchNodeTab(tabId, 'overview');
}


function switchNodeTab(tabId, tab){
  var wrapper = document.getElementById(tabId);
  if(!wrapper) return;
  wrapper.querySelectorAll('[id]').forEach(function(el){
    if(el.id.startsWith(tabId+'-') && el.id.indexOf('-btn-')<0) el.style.display='none';
  });
  var panel = document.getElementById(tabId+'-'+tab);
  if(panel) panel.style.display='block';
  wrapper.querySelectorAll('button[id]').forEach(function(btn){
    if(btn.id.startsWith(tabId+'-btn-')){
      var active = btn.id === tabId+'-btn-'+tab;
      btn.style.background = active ? 'rgba(255,255,255,.12)' : 'none';
      btn.style.color = active ? 'var(--text)' : 'var(--muted)';
    }
  });
}

function closeDetail(){ document.getElementById('detail-panel').classList.remove('open'); }
function expandAllNodes(){ _collapsed={}; renderTree(); }
function collapseAllNodes(){ nodesData.forEach(n=>{ if(n.depth>0)_collapsed[n.id]=true; }); renderTree(); }

// ─────────────── RESULTS ───────────────
function togglePaperView(mode) {
  var iframe = document.getElementById('paper-iframe');
  var pre = document.getElementById('paper-tex-pre');
  var btnPdf = document.getElementById('btn-view-pdf');
  var btnTex = document.getElementById('btn-view-tex');
  if(mode === 'pdf') {
    if(iframe) iframe.style.display = 'block';
    if(pre) pre.style.display = 'none';
    if(btnPdf) btnPdf.className = 'btn btn-primary btn-sm';
    if(btnTex) btnTex.className = 'btn btn-outline btn-sm';
  } else {
    if(iframe) iframe.style.display = 'none';
    if(pre) pre.style.display = 'block';
    if(btnPdf) btnPdf.className = 'btn btn-outline btn-sm';
    if(btnTex) btnTex.className = 'btn btn-primary btn-sm';
  }
}

async function populateResultsDropdown(){
  var sel = document.getElementById('results-ckpt-select');
  var r = await fetch('/api/checkpoints').then(function(res){return res.json();}).catch(function(){return [];});
  var active = await fetch('/state').then(function(res){return res.json();}).catch(function(){return {};});
  var activeId = (active.checkpoint_id||String(active.checkpoint_path||'').split('/').pop()||'');
  var opts = '<option value="">— Select experiment —</option>';
  for(var i=0;i<r.length;i++){
    var c=r[i];
    var selAttr = (c.id===activeId)?' selected':'';
    var scoreStr = c.review_score!=null ? ' ✦'+c.review_score : '';
    // Show: timestamp + title (truncated) + optional score
    var parts = c.id.split('_');
    var ts = parts[0] || '';
    var title = parts.slice(1).join(' ').replace(/_/g,' ').slice(0,30);
    var label = (ts.slice(2,8)+' '+title+(title?'':c.id.slice(8,24))+scoreStr).trim();
    opts += '<option value="'+c.id+'"'+selAttr+' title="'+c.id+'">'+label+'</option>';
  }
  sel.innerHTML = opts;
  // If active project is selected and no manual selection, load it
  if(activeId && sel.value==='') {
    sel.value = activeId;
  }
}

async function loadResults(){
  var sel = document.getElementById('results-ckpt-select');
  var id = sel ? sel.value : '';
  // Auto-load active project if nothing selected
  if(!id) {
    var active = await fetch('/api/active-checkpoint').then(function(r){return r.json();}).catch(function(){return {id:null};});
    id = String(active.id||active.path||'').split('/').pop();
    if(id && sel) sel.value = id;
  }
  var wrap = document.getElementById('results-content');
  if(!id){ wrap.innerHTML='<div class="empty-state"><div class="empty-icon">📊</div><p>'+t('select_exp')+'</p></div>'; return; }
  wrap.innerHTML='<div style="color:var(--muted)"><span class="spinner"></span> '+t('loading')+'</div>';
  var d = await fetch('/api/checkpoint/'+id+'/summary').then(r=>r.json()).catch(e=>({error:e.toString()}));
  if(d.error){ wrap.innerHTML='<div style="color:var(--red)">Error: '+d.error+'</div>'; return; }

  var html = '';

  // Paper TeX / PDF viewer
  if(d.paper_tex || d.has_pdf){
    var _cid = document.getElementById('results-ckpt-select').value;
    html += '<div class="card" style="margin-bottom:16px">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">';
    html += '<div class="card-title" style="margin:0" data-i18n="paper_title">📄 Paper</div>';
    html += '<div style="display:flex;gap:6px;flex-wrap:wrap">';
    if(d.has_pdf) html += '<button class="btn btn-primary btn-sm" id="btn-view-pdf" onclick="togglePaperView(\'pdf\')">📑 View PDF</button>';
    if(d.paper_tex) html += '<button class="btn btn-outline btn-sm" id="btn-view-tex" onclick="togglePaperView(\'tex\')">📝 View TeX</button>';
    if(d.has_pdf) html += '<a class="btn btn-outline btn-sm" href="/api/checkpoint/'+_cid+'/paper.pdf" download="paper.pdf">⬇ PDF</a>';
    if(d.paper_tex) html += '<a class="btn btn-outline btn-sm" href="/api/checkpoint/'+_cid+'/paper.tex" download="paper.tex">⬇ TeX</a>';
    html += '</div></div>';
    if(d.has_pdf){
      html += '<iframe id="paper-iframe" src="/api/checkpoint/'+_cid+'/paper.pdf" style="width:100%;height:640px;border:none;border-radius:6px;display:block"></iframe>';
    }
    if(d.paper_tex){
      html += '<pre id="paper-tex-pre" class="code" style="max-height:640px;overflow:auto;display:none">'+escHtml(d.paper_tex.slice(0,30000))+'</pre>';
    }
    html += '</div>';
  }

    // Review scores
  var rr = d.review_report;
  if(rr){
    var scores = [
      [t('abstract'), rr.abstract_score||rr.scores?.abstract||null],
      [t('body'), rr.body_score||rr.scores?.body||null],
      [t('overall'), rr.overall_score||rr.score||null],
    ];
    html += '<div class="card" style="margin-bottom:16px"><div class="card-title" data-i18n="review_scores">📝 Review Scores</div>'
      +'<div class="grid-3">'+scores.map(([l,v])=>'<div>'
        +'<div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">'+l+'</div>'
        +'<div style="font-size:1.4rem;font-weight:800">'+(v!=null?v:'—')+' <span style="font-size:.9rem;color:var(--muted)">/10</span></div>'
        +(v!=null?'<div class="score-bar"><div class="score-fill" style="width:'+(v*10)+'%"></div></div>':'')
        +'</div>').join('')+'</div>'
      +(rr.citation_ok!=null?'<div style="margin-top:12px">Citations: '+(rr.citation_ok?'<span class="badge badge-green">✓ '+t('ok_label')+'</span>':'<span class="badge badge-red">✗ '+t('issues_label')+'</span>')+'</div>':'')
      +'</div>';
  }

  // Verify / Reproducibility
  var repro = d.reproducibility_report;
  // Also check nested keys
  if(!repro && d.repro) repro = d.repro;
  html += '<div class="card" style="margin-bottom:16px"><div class="card-title">🔬 Verify / Reproducibility</div>';
  if(repro){
    // Handle skill-not-found error gracefully
    if(repro.error && (repro.error.indexOf('not found')>=0 || repro.error.indexOf('Tool')>=0 || repro.error.indexOf('Available: []')>=0)){
      html += '<div style="color:var(--yellow);font-size:.85rem;padding:8px">⚠️ 再現性検証スキルが利用不可 (ari-skill-paper-re 未起動の可能性)</div>';
      html += '<details><summary style="font-size:.75rem;color:var(--muted);cursor:pointer">詳細</summary><pre style="font-size:.72rem;color:var(--muted);margin-top:4px">'+repro.error+'</pre></details>';
      html += '</div>'; return html;
    }
    var verdict = repro.verdict||repro.status||repro.result||'unknown';
    var cls = (verdict==='REPRODUCED'||verdict==='PASS'||verdict==='pass')?'badge-green':(verdict==='FAILED'||verdict==='FAIL'||verdict==='fail')?'badge-red':'badge-yellow';
    html += '<div style="font-size:1.1rem;margin-bottom:8px"><span class="badge '+cls+'">'+verdict+'</span></div>';
    if(repro.summary) html += '<div style="font-size:.85rem;color:var(--muted);margin-bottom:8px">'+repro.summary+'</div>';
    // Show all top-level keys
    var skip = new Set(['verdict','status','result','summary']);
    Object.keys(repro).filter(k=>!skip.has(k)).slice(0,8).forEach(function(k){
      var v = repro[k];
      html += '<div style="font-size:.8rem;margin-top:4px"><span style="color:var(--muted)">'+k+':</span> '+JSON.stringify(v)+'</div>';
    });
  } else {
    // Show raw repro log if available
    html += '<div style="color:var(--muted);font-size:.85rem">No reproducibility report found. Run 🔍 Review / Verify from Monitor to generate.</div>';
  }
  html += '</div>';

  // Experiment context
  var sd = d.science_data;
  if(sd && sd.experiment_context){
    var ctx = sd.experiment_context;
    var rows = Object.entries(ctx).map(([k,v])=>'<tr><td style="color:var(--muted);font-size:.8rem;vertical-align:top;padding-right:8px">'+k+'</td><td style="word-break:break-word;white-space:pre-wrap;font-size:.8rem">'+String(typeof v=="object"?JSON.stringify(v,null,2):v).slice(0,500)+'</td></tr>').join('');
    html += '<div class="card" style="margin-bottom:16px"><div class="card-title">⚙️ Experiment Context</div><div style="overflow:auto"><table style="width:100%;table-layout:fixed"><colgroup><col style="width:140px"><col></colgroup>'+rows+'</table></div></div>';
  }

  // Figures
  var fm = d.figures_manifest;
  if(fm && fm.figures && fm.figures.length){
    html += '<div class="card" style="margin-bottom:16px"><div class="card-title">📈 Figures</div>';
    html += '<div class="grid-2">';
    fm.figures.forEach(fig=>{
      var path = fig.path||fig;
      var caption = fig.caption||'';
      html += '<div>'
        +(caption?'<div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">'+caption+'</div>':'')
        +'<img class="figure-img" src="/codefile?path='+encodeURIComponent(path)+'" alt="figure" onerror="this.style.display=\'none\'">'
        +'</div>';
    });
    html += '</div></div>';
  }

  wrap.innerHTML = html || '<div class="empty-state"><div class="empty-icon">📊</div><p>No results data found in this checkpoint</p></div>';
}

function escHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ─────────────── WIZARD ───────────────
function wizNext(step){
  if(step===3) {
    setTimeout(autoReadApiKey, 200);
    // Pre-fill LLM from Settings
    fetch('/api/settings').then(function(r){return r.json();}).then(function(s){
      var prov = s.llm_provider||'openai';
      var model = s.llm_model||'';
      setLLM(prov);
      var me=document.getElementById('wiz-llm-model');
      if(me){
        me.value=model;
        var ci=document.getElementById('wiz-llm-model-custom');
        if(ci&&prov==='ollama'){ci.style.display='';ci.placeholder='例: '+model;}
      }
      var hid=document.getElementById('wiz-model');
      if(hid) hid.value=model;
    }).catch(function(){});
  }
  // Hide all wizard pages
  document.querySelectorAll('.wizard-page').forEach(function(p){
    p.classList.remove('active');
    p.style.display = 'none';
  });
  // Show target page
  var target = document.getElementById('wiz-step-'+step);
  if(target) {
    target.classList.add('active');
    target.style.display = 'block';
  }
  for(var i=1;i<=4;i++){
    var pill = document.getElementById('step-pill-'+i);
    pill.className = 'step-pill'+(i===step?' active':i<step?' done':'');
  }
  wizState.step=step;
  if(step===3){
    detectScheduler();
    // Pre-populate LLM model from settings
    fetch('/api/settings').then(r=>r.json()).then(function(s){
      var prov = s.llm_provider || 'ollama';
      var mdl  = s.llm_model   || 'qwen3:8b';
      setLLM(prov);
      var sel = document.getElementById('wiz-llm-model');
      if(sel){
        // Try to select existing option
        var found = false;
        for(var i=0;i<sel.options.length;i++){
          if(sel.options[i].value===mdl){ sel.selectedIndex=i; found=true; break; }
        }
        if(!found){
          // Add as custom option
          var opt=document.createElement('option');
          opt.value=mdl; opt.textContent=mdl; sel.appendChild(opt);
          sel.value=mdl;
        }
      }
      var hid=document.getElementById('wiz-model');
      if(hid) hid.value=mdl;
      // Also pre-populate base URL
      var bu=document.querySelector('input[id*="ollama-base"],#wiz-ollama-base');
      if(bu && s.ollama_host) bu.value=s.ollama_host;
    }).catch(function(){});
  }
  if(step===4){
    // Get MD content from whichever mode is active
    var expContent = '';
    if(typeof _wizMode !== 'undefined' && _wizMode === 'chat'){
      expContent = (document.getElementById('wiz-chat-generated-md') || {}).value || '';
    }
    if(!expContent) expContent = (document.getElementById('wiz-generated-md') || {}).value || '';
    if(!expContent) expContent = (document.getElementById('wiz-goal') || {}).value || '';
    document.getElementById('wiz-final-md').value = expContent;
    var summaryEl = document.getElementById('wiz-goal-summary');
    if(summaryEl) summaryEl.textContent = expContent.slice(0,400) + (expContent.length>400?'…':'');
    document.getElementById('wiz-profile').value = wizState.mode==='hpc'?'hpc':'laptop';
  }
}

function stopStage(){
  var el = document.getElementById("stage-status");
  if(el) el.textContent = "Stop requested (may need manual kill on server)";
}
function toggleIdeaDetails(){
  var d = document.getElementById("mon-idea-details");
  var btn = document.querySelector("[onclick=\"toggleIdeaDetails()\"]");
  if(!d) return;
  d.style.display = d.style.display==="none" ? "block" : "none";
  if(btn) btn.textContent = d.style.display==="none" ? "▼ Details" : "▲ Hide";
}
function updateIdeaCard(state){
  var summaryEl = document.getElementById('mon-idea-summary');
  var detailEl  = document.getElementById('mon-idea-text');
  if(!summaryEl) return;
  if(!state || !state.checkpoint_id){
    // If experiment_md_content is available (e.g. just launched), show it
    var _md0 = state.experiment_md_content || state.experiment_text || '';
    if(_md0){
      summaryEl.textContent = _md0;
      if(summaryEl.parentElement) summaryEl.parentElement.style.display='';
    } else {
      summaryEl.textContent='— アクティブなプロジェクトを選択してください —';
    }
    return;
  }
  var mdContent = state.experiment_md_content || state.experiment_text || '';
  var ctx   = state.experiment_context || {};
  var ckptId = '';
  if(state.nodes && state.nodes.length){
    var rootId = (state.nodes[0] && state.nodes[0].id) || '';
    var mm = rootId.match(/^node_([a-f0-9]{8,})/);
    ckptId = mm ? mm[1] : rootId.split('_').slice(1).join('_').replace('_root','');
  }
  var nodeCount = state.node_count || (state.nodes||[]).length || 0;

  var html = '';

  // Header
  if(ckptId){
    html += '<div style="margin-bottom:8px">';
    html += '<code style="color:var(--blue-light);font-size:.82rem">'+escHtml(ckptId)+'</code>';
    if(nodeCount) html += ' <span class="badge badge-muted">'+nodeCount+' nodes</span>';
    html += '</div>';
  }

  if(mdContent){
    // Render experiment.md sections properly
    var sections = mdContent.split(/\n(?=##? )/);
    var hasSections = sections.length > 1;
    if(hasSections){
      sections.forEach(function(sec){
        sec = sec.trim();
        if(!sec) return;
        var lines = sec.split('\n');
        var heading = lines[0].replace(/^#+\s*/, '');
        var body = lines.slice(1).join('\n').trim();
        if(!body && lines.length === 1){ body = heading; heading = ''; }
        html += '<div style="margin-bottom:10px">';
        if(heading) html += '<div style="font-size:.72rem;font-weight:700;color:var(--blue-light);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">'+escHtml(heading)+'</div>';
        html += '<div style="font-size:.83rem;line-height:1.65;color:var(--text);white-space:pre-wrap">'+escHtml((body||sec).slice(0,500))+'</div>';
        html += '</div>';
      });
    } else {
      html += '<div style="font-size:.83rem;line-height:1.65;white-space:pre-wrap">'+escHtml(mdContent.slice(0,600))+'</div>';
    }
  } else {
    // Reconstruct from science_data experiment_context
    var overview = (typeof ctx.study_overview === 'object') ? ctx.study_overview : {};
    var hw       = (typeof ctx.hardware_software_context === 'object') ? ctx.hardware_software_context : {};
    var topic = overview.topic || overview.goal || ctx.goal || ctx.research_goal || '(not recorded)';

    html += '<div style="margin-bottom:8px"><div style="font-size:.72rem;font-weight:700;color:var(--blue-light);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Research Goal</div>';
    html += '<div style="font-size:.83rem;line-height:1.65">'+escHtml(String(topic))+'</div></div>';

    if(hw.cpu_model || hw.parallel_model){
      var hwStr = [hw.cpu_model, hw.parallel_model].filter(Boolean).join(', ');
      html += '<div style="margin-bottom:8px"><div style="font-size:.72rem;font-weight:700;color:var(--blue-light);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Platform</div>';
      html += '<div style="font-size:.83rem;line-height:1.65">'+escHtml(hwStr)+'</div></div>';
      if(hw.compilation_flags_reported && hw.compilation_flags_reported.length){
        html += '<div style="font-size:.72rem;color:var(--muted);font-family:monospace">'+escHtml(hw.compilation_flags_reported.join(' '))+'</div>';
      }
    }
    if(overview.validated_parameter_sweep){
      var ps = JSON.stringify(overview.validated_parameter_sweep).slice(0,150);
      html += '<div style="margin-top:6px;font-size:.75rem;color:var(--muted)">📊 Sweep: '+escHtml(ps)+'</div>';
    }
  }

  if(!html) html = '<span style="color:var(--muted);font-size:.8rem">No configuration available</span>';

  // Append config rows (LLM, BFTS settings)
  var _cfg2 = (state && state.experiment_config) ? state.experiment_config : {};
  if(Object.keys(_cfg2).length > 0) {
    var _cfgRows = [
      ['🤖 LLM',          (_cfg2.llm_backend||'?')+' / '+(_cfg2.llm_model||'?')],
      ['🔗 接続先',         _cfg2.ollama_host && _cfg2.llm_backend==='ollama' ? _cfg2.ollama_host : '(n/a)'],
      ['🌿 最大ノード',     (_cfg2.max_nodes||'?')+' / 深さ '+(_cfg2.max_depth||'?')+' / 並列 '+(_cfg2.parallel||'?')],
      ['⏱ タイムアウト',   _cfg2.timeout_node_s ? Math.round(_cfg2.timeout_node_s/60)+'min/node' : '—'],
      ['🔁 リトライ',       (_cfg2.retries||'?')+' / 閾値 '+(_cfg2.score_threshold||'?')],
      ['🖥 スケジューラ',   (_cfg2.scheduler||'local')+' / '+(_cfg2.partition||'—')+' / '+(_cfg2.cpus||'?')+'CPU / '+(_cfg2.walltime||'—')],
    ];
    html += '<div style="border-top:1px solid var(--border);margin-top:10px;padding-top:8px">';
    html += '<div style="font-size:.68rem;font-weight:700;color:var(--blue-light);text-transform:uppercase;margin-bottom:6px">CONFIG</div>';
    _cfgRows.forEach(function(r) {
      html += '<div style="display:flex;gap:8px;margin-bottom:3px">'
        + '<span style="font-size:.72rem;color:var(--muted);min-width:100px;flex-shrink:0">'+r[0]+'</span>'
        + '<span style="font-size:.75rem">'+escHtml(String(r[1]))+'</span></div>';
    });
    html += '</div>';
  }

  summaryEl.innerHTML = html;

  if(detailEl){
    detailEl.textContent = (state && state.experiment_detail_config) || mdContent || JSON.stringify(ctx, null, 2) || '(no detail)';
  }
}

function syncScopeToDepth(){
  var s = parseInt(document.getElementById('wiz-scope').value||2);
  var depthMap = {1:3, 2:5, 3:9, 4:15};
  var nodesMap = {1:10, 2:30, 3:60, 4:120};
  var d = document.getElementById('wiz-max-depth');
  var n = document.getElementById('wiz-max-nodes');
  if(d && !d._userEdited) d.value = depthMap[s]||5;
  if(n && !n._userEdited) n.value = nodesMap[s]||30;
}
function syncDepthToScope(){
  var d = parseInt(document.getElementById('wiz-max-depth').value||5);
  var el = document.getElementById('wiz-scope');
  if(!el) return;
  // Mark as user-edited to prevent overwrite
  document.getElementById('wiz-max-depth')._userEdited = true;
  if(d<=3) el.value=1;
  else if(d<=6) el.value=2;
  else if(d<=10) el.value=3;
  else el.value=4;
  updateScopeLabel();
}
function updateScopeLabel(){
  var v = parseInt(document.getElementById('wiz-scope').value);
  wizState.scopeVal=v;
  var configs = [
    {depth:2,nodes:6,est:'~30 min'},
    {depth:3,nodes:10,est:'~1 h'},
    {depth:4,nodes:16,est:'~2–3 h'},
    {depth:6,nodes:24,est:'~4–6 h'},
  ];
  var c = configs[v-1]||configs[0];
  document.getElementById('scope-summary').innerHTML =
    '🔬 Depth: <strong>'+c.depth+'</strong>&nbsp;&nbsp; '
    +'📦 Max nodes: <strong>'+c.nodes+'</strong>&nbsp;&nbsp; '
    +'⏱ Estimated: <strong>'+c.est+'</strong>';
}
// Init scope label
setTimeout(updateScopeLabel, 100);

function setMode(m){
  wizState.mode=m;
  ['laptop','hpc'].forEach(x=>{ document.getElementById('mode-'+x).className='toggle-btn'+(x===m?' active':''); });
  document.getElementById('hpc-options').style.display=m==='hpc'?'':'none';
  if(m==='hpc') detectScheduler();
}

function setLLM(l){
  wizState.llm=l;
  var hp=document.getElementById('wiz-llm-provider'); if(hp) hp.value=l;
  ['openai','anthropic','ollama','custom'].forEach(function(x){
    var el=document.getElementById('llm-'+x);
    if(el) el.className='toggle-btn'+(x===l?' active':'');
  });
  // Sync provider dropdown if exists
  var pe=document.getElementById('wiz-llm-provider');
  if(pe){ pe.value=l; }
  // Show/hide API key, base URL, GPU rows
  var keyRow=document.getElementById('llm-key-row');
  var baseRow=document.getElementById('wiz-baseurl-row');
  var gpuRow=document.getElementById('wiz-ollama-gpu-row');
  if(keyRow) keyRow.style.display=(l==='ollama')?'none':'';
  if(baseRow) baseRow.style.display=(l==='ollama'||l==='custom')?'':'none';
  if(gpuRow) gpuRow.style.display=(l==='ollama')?'':'none';
  // Update model list for selected provider
  // Temporarily set wiz-llm-provider value for wizUpdateModelList
  if(!pe){
    // wizUpdateModelList reads wiz-llm-provider, so create a shim
    var shimSel=document.getElementById('wiz-llm-model');
    var models={
      openai:['gpt-5.2','gpt-5.4','gpt-5.4-mini','gpt-4o','gpt-4o-mini','o3','o1-mini'],
      anthropic:['claude-opus-4-5','claude-sonnet-4-5','claude-haiku-3-5'],
      ollama:['qwen3:8b','qwen3:32b','llama3.3','gemma3:27b','mistral'],
      custom:[]
    };
    var list=models[l]||[];
    if(shimSel){
      shimSel.innerHTML=list.map(function(m){return '<option value="'+m+'">'+m+'</option>';}).join('');
    }
    // Show custom text input for ollama/custom
    var ci=document.getElementById('wiz-llm-model-custom');
    if(ci) ci.style.display=(l==='ollama'||l==='custom')?'':'none';
    // Update per-phase dropdowns
    var blank='<option value="">default</option>';
    ['idea','bfts','coding','eval','paper','review'].forEach(function(phase){
      var ps=document.getElementById('adv-model-'+phase);
      if(ps) ps.innerHTML=blank+list.map(function(m){return '<option value="'+m+'">'+m+'</option>';}).join('');
    });
    // Update wiz-model
    var hid=document.getElementById('wiz-model');
    if(hid&&list[0]) hid.value=list[0];
    if(shimSel&&list[0]) shimSel.value=list[0];
  } else {
    pe.value=l; wizUpdateModelList();
  }
}

async function loadOllamaResources(){
  var sel = document.getElementById('wiz-ollama-gpu');
  var info = document.getElementById('wiz-ollama-gpu-info');
  if(!sel) return;
  if(info) info.textContent = 'Detecting…';
  var r = await fetch('/api/ollama-resources').then(function(res){return res.json();}).catch(function(){return {gpus:[],models:[]};});
  // populate GPU options (server includes Auto + CPU + detected CUDA/AMD GPUs)
  sel.innerHTML = (r.gpus||[]).map(function(g){
    var lbl = (g.index==='auto') ? 'Auto (let Ollama decide)' :
              (g.index==='cpu')  ? 'CPU only' :
              'GPU '+g.index+': '+g.name+(g.memory?' ('+g.memory+')':'');
    var val = (g.index==='auto') ? '' :
              (g.index==='cpu')  ? 'cpu' :
              'CUDA_VISIBLE_DEVICES='+g.index;
    return '<option value="'+val+'">'+lbl+'</option>';
  }).join('');
  if(!sel.innerHTML) sel.innerHTML = '<option value="">Auto</option><option value="cpu">CPU only</option>';
  var nGpu = (r.gpus||[]).filter(function(g){return g.index!=='auto'&&g.index!=='cpu';}).length;
  if(info) info.textContent = nGpu>0 ? nGpu+' GPU(s) detected' : 'No CUDA GPU — CPU/Auto available';
  // populate model suggestions
  if(r.models && r.models.length){
    var modelEl = document.getElementById('wiz-model');
    if(modelEl && !modelEl.value.includes('qwen')) modelEl.value = r.models[0];
  }
}
async function autoReadApiKey(){
  var llm = wizState && wizState.llm ? wizState.llm : 'openai';
  var r = await fetch('/api/env-keys').then(function(res){return res.json();}).catch(function(){return {keys:{}};});
  var keyMap = {openai:'OPENAI_API_KEY', anthropic:'ANTHROPIC_API_KEY', google:'GOOGLE_API_KEY'};
  var envKey = keyMap[llm];
  var val = envKey ? (r.keys[envKey]||'') : '';
  var el = document.getElementById('wiz-apikey');
  var status = document.getElementById('wiz-apikey-status');
  if(el && val){
    el.value = val;
    if(status) status.textContent = '✓ Loaded from ~/.env (' + (envKey||'') + ')';
    if(status) status.style.color = 'var(--green)';
  } else {
    if(status && !val) status.textContent = llm==='ollama' ? '' : 'Not found in ~/.env — enter manually';
    if(status) status.style.color = 'var(--muted)';
  }
}

async function detectScheduler(){
  var el = document.getElementById('detected-scheduler');
  if(!el) return;
  el.textContent='detecting…'; el.className='badge badge-blue';
  var r = await fetch('/api/scheduler/detect').then(r=>r.json()).catch(()=>({scheduler:'none',partitions:[]}));
  el.textContent = r.scheduler;
  el.className = r.scheduler!=='none'?'badge badge-green':'badge badge-muted';
  var sel = document.getElementById('wiz-partition');
  if(sel && r.partitions && r.partitions.length){
    sel.innerHTML='<option value="">auto</option>'+r.partitions.map(p=>'<option>'+p.name+'</option>').join('');
  }
}

function toggleAdvanced(){
  var bl = document.getElementById('advanced-block');
  bl.style.display = bl.style.display==='none'?'':'none';
  if(bl.style.display!=='none' && !document.getElementById('wiz-workflow').value){
    fetch('/state').then(r=>r.text()).then(t=>{ document.getElementById('wiz-workflow').value='# workflow.yaml\n# (live state shown below)\n'+JSON.stringify(JSON.parse(t||'{}'),null,2); }).catch(()=>{});
  }
}

async function wizUpdateModelList(){
  var prov = (document.getElementById('wiz-llm-provider')||{}).value || 'openai';
  var sel = document.getElementById('wiz-llm-model');
  var customInput = document.getElementById('wiz-llm-model-custom');
  if(!sel) return;
  var models = {
    openai: ['gpt-5.2','gpt-5.4','gpt-5.4-mini','gpt-4o','gpt-4o-mini','o3','o1-mini'],
    anthropic: ['claude-opus-4-5','claude-sonnet-4-5','claude-haiku-3-5'],
    ollama: ['qwen3:8b','qwen3:32b','llama3.3','gemma3:27b','mistral'],
    custom: []
  };
  var list = models[prov] || [];
  // Add free-text option for ollama/custom
  var freeEntry = (prov==='ollama'||prov==='custom');
  sel.innerHTML = list.map(function(m){return '<option value="'+m+'">'+m+'</option>';}).join('');
  if(freeEntry) sel.innerHTML += '<option value="__custom__">— 自由入力 —</option>';
  // Show custom text input for ollama always (so any model can be entered)
  if(customInput){
    customInput.style.display = freeEntry ? '' : 'none';
  }
  // Keep wiz-model hidden input in sync
  sel.onchange = function(){
    var v = sel.value === '__custom__' ? (customInput && customInput.value || '') : sel.value;
    var hid = document.getElementById('wiz-model');
    if(hid) hid.value = v;
  };
  if(customInput) customInput.oninput = function(){
    if(sel.value==='__custom__'||(prov==='ollama')){
      var hid = document.getElementById('wiz-model');
      if(hid) hid.value = customInput.value;
    }
  };
  // Populate advanced per-phase dropdowns
  var blank = '<option value="">default</option>';
  ['idea','bfts','coding','eval','paper','review'].forEach(function(phase){
    var ps = document.getElementById('adv-model-'+phase);
    if(ps) ps.innerHTML = blank + list.map(function(m){return '<option value="'+m+'">'+m+'</option>';}).join('');
  });
}

async function launchExperiment(){
  var statusEl = document.getElementById('launch-status');
  var md = document.getElementById('wiz-final-md').value;

  var savePath = document.getElementById('wiz-save-path').value || 'experiment.md';
  var profile = document.getElementById('wiz-profile').value;
  var paperFormat = (document.getElementById('wiz-paper-format')||{}).value||'';
  statusEl.innerHTML='<span class="spinner"></span> Launching…';
  // Save experiment file via API (not available directly — show instructions)
  // POST /api/launch
  var r = await fetch('/api/launch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      config_path:savePath, profile, experiment_md:md,
      llm_model:(function(){
        var sel=document.getElementById('wiz-llm-model');
        var custom=document.getElementById('wiz-llm-model-custom');
        var v=(sel||{}).value||'';
        if(v==='__custom__'||(custom&&custom.style.display!=='none'&&custom.value)){
          return (custom&&custom.value)||v;
        }
        return v;
      })(),
      llm_provider:(document.getElementById('wiz-llm-provider')||{}).value||'',
      phase_models:(function(){
        var pm={};
        ['idea','bfts','coding','eval','paper','review'].forEach(function(p){
          var v=(document.getElementById('adv-model-'+p)||{}).value||'';
          if(v) pm[p]=v;
        });
        return pm;
      })()
    })
  }).then(r=>r.json()).catch(e=>({ok:false,error:e.toString()}));
  if(r.ok){
    statusEl.innerHTML='<span class="badge badge-green">✓ Launched (PID '+r.pid+')</span>';
    // Navigate to monitor immediately, then poll for checkpoint in background
    setTimeout(function(){ goto('monitor'); startLogStream(); loadProjectList(); }, 800);
    (function pollNewCkpt(attempts){
      setTimeout(function(){
        fetch('/api/checkpoints').then(rv=>rv.json()).then(function(ck){
          var all = ck.checkpoints||ck||[];
          var newest = all.sort(function(a,b){return (b.mtime||0)-(a.mtime||0)})[0];
          if(newest && newest.id){
            fetch('/api/switch-checkpoint',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({checkpoint_id:newest.id, path:newest.path})
            }).then(function(){ populateCheckpointDropdown&&populateCheckpointDropdown(); });
            return;
          }
          if(attempts>0) pollNewCkpt(attempts-1);
        }).catch(function(){});
      }, 3000);
    })(20);
  } else {
    statusEl.innerHTML='<span style="color:var(--red)">'+r.error+'</span>';
  }
}

// ─────────────── LOGS ───────────────
var _logReader = null;
async function startLogStream(){
  if(_logReader) { _logReader.cancel(); _logReader=null; }
  var logEl = document.getElementById('log-output');
  logEl.innerHTML='';
  document.getElementById('log-status').className='badge badge-yellow';
  document.getElementById('log-status').textContent='streaming';
  var res = await fetch('/api/logs').catch(()=>null);
  if(!res){ document.getElementById('log-status').className='badge badge-red'; document.getElementById('log-status').textContent='error'; return; }
  _logReader = res.body.getReader();
  var dec = new TextDecoder();
  var buf='';
  while(true){
    var {done, value} = await _logReader.read();
    if(done) break;
    buf += dec.decode(value);
    var lines = buf.split('\n\n');
    buf = lines.pop();
    lines.forEach(line=>{
      var m = line.match(/^data: (.+)$/m);
      if(m){ try{ var msg=JSON.parse(m[1]); appendLog(msg.msg||''); }catch(e){} }
    });
  }
  document.getElementById('log-status').className='badge badge-muted';
  document.getElementById('log-status').textContent='done';
}
function appendLog(txt){
  var el = document.getElementById('log-output');
  var line = document.createElement('div');
  line.className='log-line';
  line.textContent=txt;
  el.appendChild(line);
  el.scrollTop=el.scrollHeight;
}
function clearLogs(){ document.getElementById('log-output').innerHTML=''; }

// ─────────────── SETTINGS ───────────────
async function loadSettings(){
  var r = await fetch('/api/settings').then(r=>r.json()).catch(()=>({}));
  var savedLang = localStorage.getItem('ari_lang') || r.language || 'en';
  document.getElementById('s-lang').value = savedLang;
  applyLanguage(savedLang);
  var prov = r.llm_backend || r.llm_provider || 'openai';
  var provSel = document.getElementById('s-provider');
  if(provSel){ provSel.value = prov; onProviderChange(); }
  document.getElementById('s-model').value=r.llm_model||'';
  var mSel = document.getElementById('s-model-select');
  if(mSel && r.llm_model) mSel.value = r.llm_model;
  document.getElementById('s-temp').value=r.temperature||1.0;
  document.getElementById('s-apikey').value=r.llm_api_key||'';
  document.getElementById('s-ss-key').value=r.semantic_scholar_key||'';
  document.getElementById('s-ssh-host').value=r.ssh_host||'';
  document.getElementById('s-ssh-port').value=r.ssh_port||22;
  document.getElementById('s-ssh-user').value=r.ssh_user||'';
  document.getElementById('s-ssh-path').value=r.ssh_path||'';
  document.getElementById('s-ssh-key').value=r.ssh_key||'';
  document.getElementById('s-partition').value=r.slurm_partition||'';
  document.getElementById('s-cpus').value=r.slurm_cpus||8;
  document.getElementById('s-mem').value=r.slurm_memory_gb||32;
  document.getElementById('s-walltime').value=r.slurm_walltime||'04:00:00';

  // Load skills
  var skills = await fetch('/api/skills').then(r=>r.json()).catch(()=>[]);
  var el = document.getElementById('skills-list');
  if(!skills.length){ el.innerHTML='<div style="color:var(--muted);font-size:.85rem">No skill.yaml found</div>'; return; }
  el.innerHTML='<table><thead><tr><th data-i18n="skill_label">Skill</th><th data-i18n="skill_display_name">Display Name</th><th data-i18n="node_description">Description</th><th>Env</th></tr></thead><tbody>'
    +skills.map(s=>'<tr>'
      +'<td><code style="font-size:.78rem">'+s.name+'</code></td>'
      +'<td style="font-size:.85rem">'+s.display_name+'</td>'
      +'<td style="font-size:.8rem;color:var(--muted)">'+s.description+'</td>'
      +'<td>'+(s.requires_env&&s.requires_env.length?s.requires_env.join(', '):'<span class="badge badge-green" style="font-size:.7rem">any</span>')+'</td>'
      +'</tr>').join('')+'</tbody></table>';
  // Restore per-skill models
  ['idea','bfts','coding','eval','paper','review'].forEach(function(k){
    var el=document.getElementById('s-model-'+k);
    if(el) el.value=r['model_'+k]||'';
  });
}

async function saveSettings(){
  var data = {
    llm_model:document.getElementById('s-model').value,
    llm_provider:document.getElementById('s-provider').value,
    api_key:document.getElementById('s-apikey').value,
    temperature:parseFloat(document.getElementById('s-temp').value)||1.0,
    llm_api_key:document.getElementById('s-apikey').value,
    semantic_scholar_key:document.getElementById('s-ss-key').value,
    model_idea:(document.getElementById('s-model-idea')||{}).value||'',
    model_bfts:(document.getElementById('s-model-bfts')||{}).value||'',
    model_coding:(document.getElementById('s-model-coding')||{}).value||'',
    model_eval:(document.getElementById('s-model-eval')||{}).value||'',
    model_paper:(document.getElementById('s-model-paper')||{}).value||'',
    model_review:(document.getElementById('s-model-review')||{}).value||'',
    slurm_partition:document.getElementById('s-partition').value,
    slurm_cpus:parseInt(document.getElementById('s-cpus').value)||8,
    slurm_memory_gb:parseInt(document.getElementById('s-mem').value)||32,
    slurm_walltime:document.getElementById('s-walltime').value,
  };
  var r = await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(r=>r.json()).catch(e=>({ok:false,error:e.toString()}));
  var el = document.getElementById('settings-status');
  el.innerHTML = r.ok?'<span class="badge badge-green">✓ Saved</span>':'<span style="color:var(--red)">'+r.error+'</span>';
  setTimeout(()=>el.innerHTML='',3000);
}

async function testLLM(){
  var el=document.getElementById('settings-status');
  el.innerHTML='<span class="spinner"></span> Testing…';
  var r = await fetch('/api/config/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({goal:'ping'})}).then(r=>r.json()).catch(e=>({error:e.toString()}));
  el.innerHTML=r.error?'<span style="color:var(--red)">✗ '+r.error+'</span>':'<span class="badge badge-green">✓ LLM reachable</span>';
  setTimeout(()=>el.innerHTML='',5000);
}

// ─────────────── Project Switcher ───────────────
async function loadProjectList() {
  var r = await fetch('/api/checkpoints').then(function(res){return res.json();}).catch(function(){return [];});
  var active = await fetch('/api/active-checkpoint').then(function(res){return res.json();}).catch(function(){return {id:null};});
  var activeId = String(active.id||active.path||'').split('/').pop();
  var sel = document.getElementById('project-select');
  var statusEl = document.getElementById('project-status');
  if(!r || r.length===0) {
    sel.innerHTML = '<option value="">— no projects —</option>';
    statusEl.textContent = 'None';
    return;
  }
  var opts = '<option value="">— select project —</option>';
  for(var i=0;i<r.length;i++){
    var c = r[i];
    var cid = String(c.id||c.path||'').split('/').pop();
    var label = cid + (c.node_count ? ' (' + c.node_count + ' nodes)' : '');
    var sel_attr = (cid === activeId) ? ' selected' : '';
    opts += '<option value="' + c.path + '"' + sel_attr + '>' + label + '</option>';
  }
  sel.innerHTML = opts;
  if(activeId) {
    statusEl.textContent = activeId.length > 22 ? activeId.slice(0, 20) + '...' : activeId;
  } else {
    statusEl.textContent = 'None';
  }
}

async function switchProject(path) {
  if(!path) return;
  var statusEl = document.getElementById('project-status');
  statusEl.textContent = 'Switching…';
  var r = await fetch('/api/switch-checkpoint', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({path})
  }).then(r=>r.json()).catch(e=>({ok:false,error:e.toString()}));
  if(r.ok) {
    var id = path.split('/').pop();
    statusEl.textContent = id.length>22 ? id.slice(0,20)+'...' : id;
    // Reload tree from new checkpoint
    var state = await fetch('/state').then(function(res){return res.json();}).catch(function(){return null;});
    if(state && state.nodes) {
      nodesData = state.nodes;
      renderTree();
      renderMonitorTree();
      updateMonitorStats();
    }
    // Always reload all pages that show project-specific data
    await populateResultsDropdown();
    // Auto-select newly active project in results dropdown
    var resSel = document.getElementById('results-ckpt-select');
    if(resSel) {
      for(var i=0;i<resSel.options.length;i++){
        if(resSel.options[i].value===id){ resSel.selectedIndex=i; break; }
      }
    }
    // Reload current page content
    var activePage = document.querySelector('.page.active');
    if(activePage) {
      var pg = activePage.id.replace('page-','');
      if(pg==='results') loadResults();
      else if(pg==='experiments') loadExperiments();
      else if(pg==='home') loadHome();
      else if(pg==='tree') { renderTree(); }
      else if(pg==='monitor') { renderMonitorTree(); updateMonitorStats(); }
    }
    statusEl.style.color='var(--green)';
    setTimeout(function(){ statusEl.style.color=''; }, 1500);
  } else {
    statusEl.textContent = 'Error: '+(r.error||'unknown');
    statusEl.style.color='var(--red)';
    setTimeout(()=>statusEl.style.color='',3000);
  }
}

// ─────────────── File Upload ───────────────
var uploadedFiles = [];
async function uploadExperimentFile(input, fileType) {
  if(!fileType) fileType = 'extra';
  var files = Array.from(input.files);
  if(!files.length) return;
  var statusEl = document.getElementById('upload-status');
  var listEl = document.getElementById('upload-list');
  // fileType passed as argument
  statusEl.textContent = 'Uploading ' + files.length + ' file(s)...';
  statusEl.style.color = 'var(--muted)';
  for(var i=0;i<files.length;i++){
    var file = files[i];
    var body = await file.arrayBuffer();
    var r = await fetch('/api/upload', {
      method: 'POST',
      headers: {'Content-Type': 'application/octet-stream', 'X-Filename': file.name, 'X-File-Type': fileType},
      body: body
    }).then(function(res){return res.json();}).catch(function(e){return {ok:false,error:e.toString()};});
    if(r.ok) {
      uploadedFiles.push({name: file.name, path: r.path, type: fileType});
      if(listEl) listEl.innerHTML += '<div style="color:var(--green)">✓ '+ file.name + ' → ' + r.path + '</div>';
      // If it's an experiment file, populate the wizard
      if(fileType==='experiment' && file.name.match(/\.md$/i)){
        var text = await file.text();
        var card = document.getElementById('wiz-generated-card');
        var mdEl = document.getElementById('wiz-generated-md');
        var pathEl = document.getElementById('wiz-save-path');
        if(card) card.style.display = '';
        if(mdEl) mdEl.value = text;
        if(pathEl) pathEl.value = r.filename || file.name;
      }
    } else {
      if(listEl) listEl.innerHTML += '<div style="color:var(--red)">✗ '+file.name+': '+(r.error||'error')+'</div>';
    }
  }
  statusEl.textContent = 'Done (' + files.length + ' files)';
  statusEl.style.color = 'var(--green)';
}

// ─────────────── Partition Loader ───────────────
async function loadPartitions() {
  var sel = document.getElementById('s-partition');
  sel.innerHTML = '<option disabled>Detecting…</option>';
  var r = await fetch('/api/slurm/partitions').then(r=>r.json()).catch(()=>[]);
  if(!r.length) {
    sel.innerHTML = '<option value="">none detected</option>';
    return;
  }
  // Get current saved values
  var settings = await fetch('/api/settings').then(r=>r.json()).catch(()=>({}));
  var saved = (settings.slurm_partitions || []);
  sel.innerHTML = r.map(p=>'<option value="'+p.name+'"'+(saved.includes(p.name)?' selected':'')+'>'+p.name+' ('+p.nodes+' nodes, '+p.cpus+' cpus)</option>').join('');
}

// ─────────────── Override saveSettings to handle multi-select ───────────────
var _origSaveSettings = saveSettings;
saveSettings = async function() {
  var sel = document.getElementById('s-partition');
  var selectedPartitions = Array.from(sel.selectedOptions).map(o=>o.value).filter(v=>v);
  var data = {
    llm_model: document.getElementById('s-model').value,
    llm_backend: document.getElementById('s-provider').value,
    llm_base_url: document.getElementById('s-baseurl') ? document.getElementById('s-baseurl').value : '',
    temperature: parseFloat(document.getElementById('s-temp').value)||1.0,
    llm_api_key: document.getElementById('s-apikey').value,
    semantic_scholar_key: document.getElementById('s-ss-key').value,
    ssh_host: document.getElementById('s-ssh-host').value,
    ssh_port: parseInt(document.getElementById('s-ssh-port').value)||22,
    ssh_user: document.getElementById('s-ssh-user').value,
    ssh_path: document.getElementById('s-ssh-path').value,
    ssh_key: document.getElementById('s-ssh-key').value,
    slurm_partitions: selectedPartitions,
    slurm_partition: selectedPartitions[0] || '',
    slurm_cpus: parseInt(document.getElementById('s-cpus').value)||8,
    slurm_memory_gb: parseInt(document.getElementById('s-mem').value)||32,
    slurm_walltime: document.getElementById('s-walltime').value,
  };
  var r = await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(r=>r.json()).catch(e=>({ok:false,error:e.toString()}));
  var el = document.getElementById('settings-status');
  el.innerHTML = r.ok?'<span class="badge badge-green">✓ Saved</span>':'<span style="color:var(--red)">'+r.error+'</span>';
  setTimeout(()=>el.innerHTML='',3000);
};

// ─────────────── SSH Test ───────────────
async function testSSH() {
  var statusEl = document.getElementById('ssh-test-status');
  statusEl.innerHTML = '<span class="spinner"></span> Connecting…';
  var data = {
    ssh_host: document.getElementById('s-ssh-host').value,
    ssh_port: parseInt(document.getElementById('s-ssh-port').value)||22,
    ssh_user: document.getElementById('s-ssh-user').value,
    ssh_path: document.getElementById('s-ssh-path').value,
    ssh_key: document.getElementById('s-ssh-key').value,
  };
  var r = await fetch('/api/ssh/test', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(r=>r.json()).catch(e=>({ok:false,error:e.toString()}));
  if(r.ok) {
    statusEl.innerHTML = '<span class="badge badge-green">✓ Connected — '+r.info+'</span>';
  } else {
    statusEl.innerHTML = '<span style="color:var(--red)">✗ '+r.error+'</span>';
  }
}

// ─────────────── LLM Provider ───────────────
var PROVIDER_MODELS = {
  openai:    ['gpt-5.2','gpt-4o','gpt-4o-mini','o3','o1-mini'],
  anthropic: ['claude-opus-4-5','claude-sonnet-4-5','claude-3-5-haiku-latest'],
  gemini:    ['gemini/gemini-2.5-pro','gemini/gemini-2.0-flash','gemini/gemini-1.5-pro'],
  ollama:    ['ollama_chat/llama3.3','ollama_chat/qwen3:8b','ollama_chat/gemma3:9b','ollama_chat/mistral'],
};
var PROVIDER_KEY_PLACEHOLDER = {
  openai: 'sk-...', anthropic: 'sk-ant-...', gemini: 'AIza...', ollama: '(not required)',
};
function onProviderChange() {
  var prov = document.getElementById('s-provider').value;
  var models = PROVIDER_MODELS[prov] || [];
  var sel = document.getElementById('s-model-select');
  sel.innerHTML = models.map(function(m){return '<option value="'+m+'">'+m+'</option>';}).join('');
  if(models.length) document.getElementById('s-model').value = models[0];
  // Show/hide fields
  var keyRow = document.getElementById('s-apikey-row');
  var urlRow = document.getElementById('s-baseurl-row');
  if(keyRow) keyRow.style.display = prov==='ollama' ? 'none' : '';
  if(urlRow) urlRow.style.display = prov==='ollama' ? '' : 'none';
  var keyInput = document.getElementById('s-apikey');
  if(keyInput) keyInput.placeholder = PROVIDER_KEY_PLACEHOLDER[prov] || 'api key';
}


// ─────────────── Tree Pan/Drag ───────────────
(function(){
  var wrapper, isDragging=false, startX=0, startY=0, scrollLeft=0, scrollTop=0;
  function initTreeDrag(){
    wrapper = document.getElementById('tree-pan-wrapper');
    if(!wrapper) { setTimeout(initTreeDrag, 500); return; }
    wrapper.addEventListener('mousedown', function(e){
      if(e.target.closest('.tree-node')) return;
      isDragging=true; startX=e.clientX; startY=e.clientY;
      scrollLeft=wrapper.scrollLeft; scrollTop=wrapper.scrollTop;
      wrapper.style.cursor='grabbing'; e.preventDefault();
    });
    document.addEventListener('mousemove', function(e){
      if(!isDragging) return;
      wrapper.scrollLeft = scrollLeft - (e.clientX - startX);
      wrapper.scrollTop  = scrollTop  - (e.clientY - startY);
    });
    document.addEventListener('mouseup', function(){
      isDragging=false;
      if(wrapper) wrapper.style.cursor='grab';
    });
    wrapper.addEventListener('touchstart',function(e){var t=e.touches[0];startX=t.clientX;startY=t.clientY;scrollLeft=wrapper.scrollLeft;scrollTop=wrapper.scrollTop;},{passive:true});
    wrapper.addEventListener('touchmove',function(e){var t=e.touches[0];wrapper.scrollLeft=scrollLeft-(t.clientX-startX);wrapper.scrollTop=scrollTop-(t.clientY-startY);},{passive:true});
  }
  document.addEventListener('DOMContentLoaded', initTreeDrag);
})();


// ─────────────── Detail Panel Resize ───────────────
(function(){
  var handle, panel, startX, startW;
  function initResize(){
    handle = document.getElementById('detail-resize-handle');
    panel  = document.getElementById('detail-panel');
    if(!handle || !panel) return;
    handle.addEventListener('mousedown', function(e){
      startX = e.clientX;
      startW = panel.offsetWidth;
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
      e.preventDefault();
    });
  }
  function onDrag(e){
    var dx = startX - e.clientX;  // dragging left = wider
    var newW = Math.max(180, Math.min(startW + dx, window.innerWidth * 0.6));
    panel.style.width = newW + 'px';
    panel.style.minWidth = newW + 'px';
  }
  function stopDrag(){
    document.removeEventListener('mousemove', onDrag);
    document.removeEventListener('mouseup', stopDrag);
  }
  document.addEventListener('DOMContentLoaded', initResize);
})();



// ═══════════════════════════ WORKFLOW ═══════════════════════════
var _wfData = null;
var _wfSelectedStage = null;

var SKILL_COLORS = {
  'web-skill':              '#3b82f6',
  'plot-skill':             '#f59e0b',
  'paper-skill':            '#8b5cf6',
  'paper-re-skill':         '#06b6d4',
  'paper-writing-skill':    '#8b5cf6',
  'transform-skill':        '#10b981',
  'evaluator-skill':        '#ef4444',
  'idea-skill':             '#f97316',
  'idea-generation-skill':  '#f97316',
  'hpc-skill':              '#64748b',
  'memory-skill':           '#a78bfa',
  'benchmark-skill':        '#ec4899',
  'coding-skill':           '#84cc16',
  'review-response-skill':  '#f43f5e',
  'vlm-review-skill':       '#d946ef',
};
function skillColor(name){ return SKILL_COLORS[name]||'#475569'; }


function switchWfView(mode){
  if(!_wfData) return;
  ['full','bfts','paper'].forEach(function(m){
    var btn = document.getElementById('wf-tab-'+m);
    if(btn) btn.style.background = m===mode ? 'rgba(255,255,255,.15)' : '';
  });
  var pipe = mode==='bfts' ? (_wfData.bfts_pipeline||[])
           : mode==='paper' ? (_wfData.paper_pipeline||_wfData.workflow.pipeline||[])
           : (_wfData.full_pipeline||_wfData.workflow.pipeline||[]);
  renderWorkflowDag(pipe);
  // Stage list always shows paper pipeline (editable)
  renderWorkflowList(_wfData.paper_pipeline||_wfData.workflow.pipeline||[], _wfData.skill_mcp||{});
}

function loadWorkflow(){
  fetch('/api/workflow').then(r=>r.json()).then(function(d){
    if(!d.ok){ var el=document.getElementById('wf-list'); if(el) el.innerHTML='<p style="color:var(--danger)">'+d.error+'</p>'; return; }
    _wfData=d;
    var pipe=d.workflow.pipeline||[];
    renderWorkflowDag(d.full_pipeline||pipe);
    renderWorkflowList(d.paper_pipeline||pipe, d.skill_mcp||{});
    renderWorkflowSkills(d.workflow.skills||[], d.skill_mcp||{});
    // Default to full view
    switchWfView('full');
  });
}

function renderWorkflowDag(pipeline){
  var el=document.getElementById('wf-dag');
  if(!el) return;
  var depMap={};
  pipeline.forEach(function(s){ depMap[s.stage]=s.depends_on||[]; });
  var levels={};
  function getLevel(s){
    if(levels[s]!==undefined) return levels[s];
    var deps=depMap[s]||[];
    levels[s]=deps.length===0?0:Math.max.apply(null,deps.map(function(d){return getLevel(d)+1;}));
    return levels[s];
  }
  pipeline.forEach(function(s){getLevel(s.stage);});
  var colW=155,nodeH=50,padX=12,padY=12,colGap=32;
  var maxLevel=Math.max.apply(null,Object.values(levels));
  var colRow={};
  var posMap={};
  pipeline.forEach(function(s){
    var lv=levels[s.stage];
    if(colRow[lv]===undefined) colRow[lv]=0;
    posMap[s.stage]={x:padX+lv*(colW+colGap),y:padY+colRow[lv]*(nodeH+10)};
    colRow[lv]++;
  });
  var maxRows=Math.max.apply(null,Object.values(colRow));
  var svgW=padX*2+(maxLevel+1)*(colW+colGap);
  var svgH=padY*2+maxRows*(nodeH+10);
  var svg='<svg width="'+svgW+'" height="'+svgH+'" style="font-family:var(--font);display:block">'
    +'<defs><marker id="warr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">'
    +'<path d="M0,0 L7,3.5 L0,7 Z" fill="rgba(255,255,255,.3)"/></marker></defs>';
  pipeline.forEach(function(s){
    (s.depends_on||[]).forEach(function(dep){
      if(!posMap[dep]||!posMap[s.stage]) return;
      var x1=posMap[dep].x+colW,y1=posMap[dep].y+nodeH/2;
      var x2=posMap[s.stage].x,y2=posMap[s.stage].y+nodeH/2;
      var mx=(x1+x2)/2;
      svg+='<path d="M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2+'"'
         +' fill="none" stroke="rgba(255,255,255,.2)" stroke-width="1.5" marker-end="url(#warr)"/>';
    });
  });
  pipeline.forEach(function(s){
    var pos=posMap[s.stage];
    var col=skillColor(s.skill); if(s.phase==='bfts') col = col || '#10b981';
    var enabled=s.enabled!==false;
    var sname=s.stage.replace(/_/g,' ');
    svg+='<g opacity="'+(enabled?1:0.4)+'" style="cursor:pointer" onclick="selectWfStage('+s.stage+')">'
      +'<rect x="'+pos.x+'" y="'+pos.y+'" width="'+colW+'" height="'+nodeH+'" rx="7" fill="'+col+'" fill-opacity=".12" stroke="'+col+'" stroke-width="1.5"/>'
      +'<text x="'+(pos.x+8)+'" y="'+(pos.y+16)+'" fill="'+col+'" font-size="10" font-weight="700">'+sname+'</text>'
      +'<text x="'+(pos.x+8)+'" y="'+(pos.y+28)+'" fill="rgba(255,255,255,.45)" font-size="9">'+(s.skill||'')+'</text>'
      +'<text x="'+(pos.x+8)+'" y="'+(pos.y+40)+'" fill="rgba(255,255,255,.3)" font-size="8">'+(s.tool||'')+'</text>'
      +'</g>';
    if(s.skip_if_exists||s.run_if||s.skip_if_score){
      var label=s.skip_if_exists?'skip_if':s.run_if?'run_if':'cond';
      svg+='<rect x="'+(pos.x+colW-44)+'" y="'+(pos.y+2)+'" width="42" height="13" rx="4" fill="#f59e0b" fill-opacity=".3"/>'
         +'<text x="'+(pos.x+colW-42)+'" y="'+(pos.y+11)+'" fill="#f59e0b" font-size="8">'+label+'</text>';
    }
  });
  // Draw loop-back arrows for BFTS cycle
  pipeline.forEach(function(s){
    if(s.loop_back_to && posMap[s.stage] && posMap[s.loop_back_to]){
      var from=posMap[s.stage], to=posMap[s.loop_back_to];
      var x1=from.x+colW/2, y1=from.y+nodeH;
      var x2=to.x+colW/2, y2=to.y+nodeH;
      svg+='<path d="M'+x1+','+y1+' C'+x1+','+(y1+30)+' '+x2+','+(y2+30)+' '+x2+','+y2+'"'
          +' fill="none" stroke="rgba(251,191,36,.4)" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#warr)"/>';
      svg+='<text x="'+((x1+x2)/2)+'" y="'+(y1+22)+'" fill="rgba(251,191,36,.7)" font-size="8" text-anchor="middle">loop</text>';
    }
  });
  svg+='</svg>';
  el.innerHTML=svg;
}

function selectWfStage(stageId){
  _wfSelectedStage=stageId;
  document.querySelectorAll('#wf-list .wf-stage-card').forEach(function(c){
    c.style.outline=c.dataset.stage===stageId?'2px solid var(--blue)':'none';
  });
}

function renderWorkflowList(pipeline, skillMcp){
  var el=document.getElementById('wf-list');
  if(!el||!pipeline) return;
  var showMcp=(document.getElementById('wf-show-mcp')||{}).checked!==false;
  el.innerHTML='';
  pipeline.forEach(function(s,idx){
    var col=skillColor(s.skill);
    var enabled=s.enabled!==false;
    var mcpTools=(skillMcp[s.skill]||{}).tools||[];
    var div=document.createElement('div');
    div.className='card wf-stage-card';
    div.dataset.stage=s.stage; div.dataset.idx=idx;
    div.draggable=true;
    div.style.cssText='border-left:3px solid '+col+';opacity:'+(enabled?1:0.55)+';cursor:grab;padding:8px 10px';
    var condTags='';
    if(s.skip_if_exists) condTags+='<span style="background:#f59e0b22;color:#f59e0b;font-size:.7rem;padding:1px 5px;border-radius:6px">skip_if_exists</span> ';
    if(s.run_if) condTags+='<span style="background:#3b82f622;color:#3b82f6;font-size:.7rem;padding:1px 5px;border-radius:6px">run_if</span> ';
    if(s.skip_if_score) condTags+='<span style="background:#ef444422;color:#ef4444;font-size:.7rem;padding:1px 5px;border-radius:6px">skip_if_score</span> ';
    var toolPills='';
    if(showMcp&&mcpTools.length){
      toolPills='<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:5px">'
               +mcpTools.map(function(t){
                  var act=t===s.tool;
                  return '<span style="font-size:.68rem;padding:1px 6px;border-radius:6px;background:'+(act?col+'33':'rgba(255,255,255,.05)')+';color:'+(act?col:'var(--muted)')+';border:1px solid '+(act?col:'transparent')+'">'+t+(act?' ✓':'')+'</span>';
               }).join('')+'</div>';
    }
    var depPills='';
    if((s.depends_on||[]).length){
      depPills='<div style="margin-top:3px">'+(s.depends_on||[]).map(function(d){return '<span style="font-size:.68rem;color:var(--muted);background:rgba(255,255,255,.05);padding:1px 5px;border-radius:5px">←'+d+'</span>';}).join(' ')+'</div>';
    }
    div.innerHTML='<div style="display:flex;gap:8px;align-items:flex-start">'
      +'<span style="font-size:.9rem">⠿</span>'
      +'<div style="flex:1;min-width:0;overflow:hidden">'
        +'<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-bottom:2px">'
          +'<strong style="color:'+col+';font-size:.82rem">'+s.stage+'</strong>'
          +(s.phase?'<span style="font-size:.65rem;padding:1px 5px;border-radius:5px;background:'+(s.phase==="bfts"?"#10b98122":"#8b5cf622")+';color:'+(s.phase==="bfts"?"#10b981":"#8b5cf6")+'">'+s.phase+'</span>':'')
          +'<span style="font-size:.7rem;background:'+col+'22;color:'+col+';padding:1px 6px;border-radius:6px">'+s.skill+'</span>'
          +condTags
        +'</div>'
        +'<div style="font-size:.72rem;color:var(--muted)">🔧 '+s.tool+'</div>'
        +depPills+toolPills
      +'</div>'
      +'<div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end">'
        +'<label style="cursor:pointer;font-size:.72rem;white-space:nowrap">'
          +'<input type="checkbox" '+(enabled?'checked':'')+' onchange="toggleWfStage('+idx+',this.checked)"> On'
        +'</label>'
        +'<button onclick="removeStageAt('+idx+')" style="font-size:.68rem;background:none;border:1px solid var(--border);color:var(--muted);border-radius:4px;padding:1px 5px;cursor:pointer">✕</button>'
      +'</div>'
      +'</div>';
    el.appendChild(div);
  });
  var dragged=null;
  el.querySelectorAll('[draggable]').forEach(function(item){
    item.addEventListener('dragstart',function(){dragged=item;item.style.opacity='.3';});
    item.addEventListener('dragend',function(){item.style.opacity=_wfData.workflow.pipeline[item.dataset.idx].enabled!==false?'1':'0.55';dragged=null;});
    item.addEventListener('dragover',function(e){e.preventDefault();});
    item.addEventListener('drop',function(e){
      e.preventDefault(); if(dragged===item) return;
      var from=parseInt(dragged.dataset.idx),to=parseInt(item.dataset.idx);
      var pipe=_wfData.workflow.pipeline;
      pipe.splice(to,0,pipe.splice(from,1)[0]);
      renderWorkflowDag(pipe); renderWorkflowList(pipe,_wfData.skill_mcp||{});
    });
    item.addEventListener('click',function(){selectWfStage(item.dataset.stage);});
  });
}

function renderWorkflowSkills(skills, skillMcp){
  var el=document.getElementById('wf-skills-list');
  if(!el) return;
  var all={};
  (skills||[]).forEach(function(s){all[s.name]=s;});
  Object.values(skillMcp||{}).forEach(function(m){ if(!all[m.name]) all[m.name]={name:m.name,description:m.description}; all[m.name]._mcp=m; });
  el.innerHTML=Object.values(all).map(function(s){
    var col=skillColor(s.name); var mcp=s._mcp||{}; var tools=mcp.tools||[];
    return '<div class="card" style="border-left:3px solid '+col+';padding:7px 9px;cursor:pointer" onclick="openSkillDetail(\''+s.name+'\')">'
      +'<div style="font-weight:700;color:'+col+';font-size:.78rem;margin-bottom:2px">'+s.name+'</div>'
      +'<div style="font-size:.7rem;color:var(--muted);margin-bottom:4px">'+s.description+'</div>'
      +(tools.length?'<div style="display:flex;flex-wrap:wrap;gap:2px">'+tools.map(function(t){return '<span style="font-size:.65rem;padding:1px 5px;border-radius:5px;background:'+col+'22;color:'+col+'">'+t+'</span>';}).join('')+'</div>':'<span style="font-size:.68rem;color:var(--muted)">no tools</span>')
      +'</div>';
  }).join('');
}

function toggleWfStage(idx,enabled){
  if(!_wfData) return;
  _wfData.workflow.pipeline[idx].enabled=enabled;
  renderWorkflowDag(_wfData.workflow.pipeline); renderWorkflowList(_wfData.workflow.pipeline,_wfData.skill_mcp||{});
}

function removeStageAt(idx){
  if(!_wfData) return;
  if(!confirm('Remove "'+_wfData.workflow.pipeline[idx].stage+'"?')) return;
  _wfData.workflow.pipeline.splice(idx,1);
  renderWorkflowDag(_wfData.workflow.pipeline); renderWorkflowList(_wfData.workflow.pipeline,_wfData.skill_mcp||{});
}

function addStage(){
  if(!_wfData) return;
  var name=prompt('Stage name (snake_case):'); if(!name) return;
  var skill=prompt('Skill name:')||''; var tool=prompt('MCP tool:')||'';
  _wfData.workflow.pipeline.push({stage:name,skill:skill,tool:tool,depends_on:[],enabled:true,description:'',inputs:{},outputs:{file:'{{ckpt}}/'+name+'.json'},load_inputs:[]});
  renderWorkflowDag(_wfData.workflow.pipeline); renderWorkflowList(_wfData.workflow.pipeline,_wfData.skill_mcp||{});
}

function applyCondition(){
  if(!_wfSelectedStage||!_wfData){alert('Click a stage in the DAG or list first');return;}
  var ctype=document.getElementById('wf-cond-type').value;
  var cval=document.getElementById('wf-cond-value').value;
  if(!ctype||!cval){alert('Select condition type and enter value');return;}
  var stage=_wfData.workflow.pipeline.find(function(s){return s.stage===_wfSelectedStage;});
  if(!stage) return;
  stage[ctype]=cval;
  renderWorkflowDag(_wfData.workflow.pipeline); renderWorkflowList(_wfData.workflow.pipeline,_wfData.skill_mcp||{});
  var msg=document.getElementById('wf-save-msg');
  msg.textContent='✅ Applied to '+_wfSelectedStage;
  setTimeout(function(){msg.textContent='';},2500);
}

function saveWorkflow(){
  if(!_wfData) return;
  var msg=document.getElementById('wf-save-msg');
  msg.textContent='保存中…';
  fetch('/api/workflow',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:_wfData.path,pipeline:_wfData.workflow.pipeline})
  }).then(r=>r.json()).then(function(d){
    msg.textContent=d.ok?'✅ 保存完了':'❌ '+d.error;
    setTimeout(function(){msg.textContent='';},3000);
  });
}
// END WORKFLOW


// ═══════════════════════════ SKILL MODAL ═══════════════════════════
var _skillModalData = null;

function openSkillDetail(skillName){
  var modal = document.getElementById('skill-modal');
  if(!modal) return;
  document.getElementById('skill-modal-title').textContent = skillName;
  document.getElementById('skill-modal-desc').textContent = 'Loading…';
  document.getElementById('skill-modal-content').textContent = '';
  document.getElementById('skill-modal-tabs').innerHTML = '';
  modal.style.display = 'block';
  fetch('/api/skill/' + encodeURIComponent(skillName))
    .then(function(r){return r.json();})
    .then(function(d){
      if(!d.ok){
        document.getElementById('skill-modal-desc').textContent = d.error;
        return;
      }
      _skillModalData = d;
      document.getElementById('skill-modal-desc').textContent = d.dir;
      // Build tabs
      var tabs = document.getElementById('skill-modal-tabs');
      var files = Object.keys(d.files);
      if(!files.length){
        document.getElementById('skill-modal-content').textContent = '(no files found)';
        return;
      }
      files.forEach(function(fname, i){
        var btn = document.createElement('button');
        btn.textContent = fname;
        btn.style.cssText = 'background:none;border:1px solid var(--border);color:var(--muted);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:.75rem';
        btn.onclick = function(){
          tabs.querySelectorAll('button').forEach(function(b){ b.style.color='var(--muted)'; b.style.background='none'; });
          btn.style.color='var(--text)'; btn.style.background='rgba(255,255,255,.07)';
          document.getElementById('skill-modal-content').textContent = d.files[fname];
        };
        if(i===0){ btn.style.color='var(--text)'; btn.style.background='rgba(255,255,255,.07)'; }
        tabs.appendChild(btn);
      });
      // Show first file
      document.getElementById('skill-modal-content').textContent = d.files[files[0]];
    })
    .catch(function(e){
      document.getElementById('skill-modal-desc').textContent = 'Error: '+e;
    });
}

function closeSkillModal(){
  var modal = document.getElementById('skill-modal');
  if(modal) modal.style.display = 'none';
}
// ── GPU Monitor ──────────────────────────────────────
function gpuMonitorRefresh(){
  fetch('/api/gpu-monitor').then(r=>r.json()).then(function(d){
    var st = document.getElementById('gpu-monitor-status');
    var lg = document.getElementById('gpu-monitor-log');
    if(!st) return;
    st.textContent = d.running ? '🟢 稼働中 (PID '+d.pid+')' : '⬛ 停止中';
    st.style.color = d.running ? 'var(--green,#4caf50)' : 'var(--muted)';
    if(lg && d.log) lg.textContent = d.log.slice(-800);
  }).catch(function(){});
}
function gpuMonitorStart(){
  if(!confirm('GPU Monitor はSLURMジョブを継続的に投入します。\nGPUを使う実験を実行中の場合のみ起動してください。\n\n続行しますか?')) return;
  fetch('/api/gpu-monitor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'start',confirmed:true})})
    .then(r=>r.json()).then(function(d){ setTimeout(gpuMonitorRefresh,1000); });
}
function gpuMonitorStop(){
  fetch('/api/gpu-monitor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'})})
    .then(r=>r.json()).then(function(d){ setTimeout(gpuMonitorRefresh,1000); });
}
// ─────────────────────────────────────────────────────

// END SKILL MODAL


function loadIdeaPage(){
  if(!window._stateCache) {
    fetch('/state').then(r=>r.json()).then(function(d){ window._stateCache=d; loadIdeaPage(); });
    return;
  }
  var s = window._stateCache;
  // Experiment Configuration: show key run parameters
  var _cfg = s.experiment_config || {};
  var _cfgEl = document.getElementById('idea-exp-md');
  if(Object.keys(_cfg).length > 0){
    var _rows = [
      ['🤖 LLM モデル',     _cfg.llm_model     || '—'],
      ['🔌 バックエンド',   _cfg.llm_backend   || '—'],
      ['🔗 接続先',         _cfg.ollama_host && _cfg.llm_backend==='ollama' ? _cfg.ollama_host : '(n/a)'],
      ['🌿 最大ノード数',   _cfg.max_nodes     || '—'],
      ['🌊 最大深さ',       _cfg.max_depth     || '—'],
      ['⚡ 並列数',         _cfg.parallel      || '—'],
      ['⏱ ノードタイムアウト', (_cfg.timeout_node_s ? Math.round(_cfg.timeout_node_s/60)+'min' : '—')],
      ['🔁 最大リトライ',   _cfg.retries       || '—'],
      ['🎯 スコア閾値',     _cfg.score_threshold != null ? _cfg.score_threshold : '—'],
      ['🖥 スケジューラ',   _cfg.scheduler     || 'local'],
      ['🖥 パーティション', _cfg.partition     || '—'],
      ['💻 CPU/ジョブ',     _cfg.cpus          || '—'],
      ['🧠 メモリ/ジョブ',  _cfg.memory_gb     ? _cfg.memory_gb+'GB' : '—'],
      ['⌛ 実行時間上限',   _cfg.walltime      || '—'],
    ];
    _cfgEl.innerHTML = _rows.map(function(r){
      return '<span style="display:inline-block;min-width:130px;color:var(--muted);font-size:.75rem">'+r[0]+'</span>'
           + '<span style="font-size:.78rem">'+r[1]+'</span>';
    }).join('<br>');
  } else {
    // Fallback: checkpoint ID
    var _ckptId = s.checkpoint_id || s.experiment_md_path || '(not recorded)';
    _cfgEl.textContent = _ckptId;
  }
  // Populate detail: experiment.md + full YAML config (preserve open state)
  var _detailPre = document.getElementById('idea-config-content');
  var _detailEl = _detailPre ? _detailPre.closest('details') : null;
  var _wasOpen = _detailEl ? _detailEl.open : false;
  if(_detailPre){
    var _parts = [];
    if(s.experiment_md_content){
      _parts.push('=== experiment.md ===\n' + s.experiment_md_content.trim());
    }
    if(s.experiment_detail_config){
      _parts.push('\n=== config (merged) ===\n' + s.experiment_detail_config.trim());
    }
    _detailPre.textContent = _parts.length ? _parts.join('\n') : '(not available)';
    if(_detailEl && _wasOpen) _detailEl.open = true;
  }

  // Goal
  var ctx = s.experiment_context || {};
  var goal = s.experiment_goal || ctx.goal || ctx.research_goal || '';
  document.getElementById('idea-goal').textContent = goal || '(not available)';
  // Root node hypothesis
  var nodes = s.nodes || [];
  var root = nodes.find(function(n){ return !n.parent_id || n.depth===0; });
  if(root) {
    // Show best hypothesis: prefer success nodes, then highest score, then any eval_summary
    var bestNode = null, bestScore = -Infinity;
    nodes.forEach(function(n) {
      if(n.eval_summary) {
        var sc = (typeof n.score === 'number') ? n.score : (n.status==='success' ? 1 : 0);
        if(sc > bestScore) { bestScore = sc; bestNode = n; }
      }
    });
    var rootIdea;
    if(bestNode) {
      var badge = '[' + (bestNode.label||'?').toUpperCase() + '] ';
      var scoreStr = typeof bestNode.score === 'number' ? ' (score: '+bestNode.score+')' : '';
      rootIdea = badge + bestNode.eval_summary + scoreStr;
    } else if(root.eval_summary) {
      rootIdea = root.eval_summary;
    } else {
      rootIdea = '(hypothesis not yet generated — BFTS root node failed before idea generation)';
    }
    document.getElementById('idea-hypothesis').textContent = rootIdea;

    // Show all node hypotheses as a list
    var listEl = document.getElementById('idea-hypotheses-list');
    if(listEl) {
      var hyps = nodes.filter(function(n){ return n.eval_summary && n.status !== 'pending'; });
      if(hyps.length > 1) {
        var LC = {draft:'#8b5cf6',debug:'#06b6d4',ablation:'#f59e0b',validation:'#10b981',improve:'#ec4899'};
        var SC = {success:'#22c55e',failed:'#ef4444',running:'#3b82f6'};
        var html = '<div style="font-size:.75rem;color:var(--muted);margin-bottom:6px">ALL HYPOTHESES ('+hyps.length+' nodes)</div>';
        hyps.forEach(function(n) {
          var lc = LC[n.label] || '#888';
          var sc = SC[n.status] || '#888';
          var score = typeof n.score==='number' ? '<span style="color:#22c55e;font-weight:600;margin-left:6px">'+n.score+'</span>' : '';
          html += '<div style="border-left:2px solid '+lc+';padding:6px 10px;margin-bottom:6px;background:var(--card)">'
            + '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">'
            + '<span style="color:'+lc+';font-size:.68rem;font-weight:600">'+escHtml(n.label||'?')+'</span>'
            + '<span style="color:var(--muted);font-size:.68rem;font-family:monospace">'+(n.id||'').slice(-8)+'</span>'
            + '<span style="color:'+sc+';font-size:.68rem">●</span>'+score+'</div>'
            + '<div style="font-size:.78rem;line-height:1.5;color:var(--text)">'+escHtml(n.eval_summary)+'</div>'
            + '</div>';
        });
        listEl.innerHTML = html;
      } else {
        listEl.innerHTML = '';
      }
    }
    // Strategy: what labels/approaches were tried
    var labelCount = {};
    nodes.forEach(function(n){ var l=n.label||'unknown'; labelCount[l]=(labelCount[l]||0)+1; });
    var strat = '<div style="margin-bottom:8px;font-size:.78rem;color:var(--muted)">'+nodes.length+' nodes explored</div>'
              + '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    Object.entries(labelCount).forEach(function([l,c]){
      var colors = {draft:'#3b82f6',improve:'#8b5cf6',ablation:'#f59e0b',debug:'#ef4444',validation:'#10b981'};
      var col = colors[l]||'#64748b';
      strat += '<div style="background:'+col+'22;border:1px solid '+col+';border-radius:8px;padding:4px 12px;font-size:.8rem">'
             + '<strong style="color:'+col+'">'+l+'</strong> <span style="color:var(--muted)">×'+c+'</span></div>';
    });
    strat += '</div>';
    // Best node
    var best = nodes.filter(function(n){return n.status==='success';})
                    .sort(function(a,b){ return ((b.metrics&&b.metrics._scientific_score)||0)-((a.metrics&&a.metrics._scientific_score)||0); })[0];
    if(best) {
      var m = best.metrics || {};
      var mKeys = Object.keys(m).filter(function(k){return !k.startsWith('_');});
      strat += '<div style="margin-top:12px"><div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Best node: <strong>'+best.id+'</strong> ('+best.label+')</div>';
      strat += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
      mKeys.forEach(function(k){
        var v = m[k]; var vs = typeof v==='number'?(v>100?v.toFixed(0):v.toFixed(3)):String(v).slice(0,20);
        strat += '<span class="badge badge-blue">'+k+': <strong>'+vs+'</strong></span>';
      });
      strat += '</div></div>';
    }
    document.getElementById('idea-strategy').innerHTML = strat;
  }
}


// ─── WIZARD CHAT MODE ───────────────────────────────────────────────────────
var _wizChatHistory = [];
var _wizMode = 'chat';

function wizSetMode(mode){
  _wizMode = mode;
  var chatDiv = document.getElementById('wiz-mode-chat');
  var mdDiv   = document.getElementById('wiz-mode-md');
  var tabChat = document.getElementById('wiz-tab-chat');
  var tabMd   = document.getElementById('wiz-tab-md');
  if(mode === 'chat'){
    chatDiv.style.display = 'block';
    mdDiv.style.display   = 'none';
    tabChat.style.background = 'rgba(59,130,246,.18)';
    tabChat.style.color      = 'var(--blue-light)';
    tabChat.style.fontWeight = '700';
    tabMd.style.background = 'none';
    tabMd.style.color      = 'var(--muted)';
    tabMd.style.fontWeight = '400';
  } else {
    chatDiv.style.display = 'none';
    mdDiv.style.display   = 'block';
    tabMd.style.background = 'rgba(59,130,246,.18)';
    tabMd.style.color      = 'var(--blue-light)';
    tabMd.style.fontWeight = '700';
    tabChat.style.background = 'none';
    tabChat.style.color      = 'var(--muted)';
    tabChat.style.fontWeight = '400';
  }
}

function wizChatAppend(role, text){
  var container = document.getElementById('wiz-chat-messages');
  if(!container) return;
  var div = document.createElement('div');
  div.style.cssText = 'align-self:'+(role==='user'?'flex-end':'flex-start')+';max-width:85%';
  var isUser = role === 'user';
  var bg = isUser ? 'rgba(139,92,246,.15)' : 'rgba(59,130,246,.12)';
  var border = isUser ? 'rgba(139,92,246,.3)' : 'rgba(59,130,246,.3)';
  var radius = isUser ? '12px 12px 2px 12px' : '12px 12px 12px 2px';
  div.innerHTML = '<div style="background:'+bg+';border:1px solid '+border+';border-radius:'+radius
                + ';padding:10px 14px;font-size:.84rem;line-height:1.6;white-space:pre-wrap">'
                + escHtml(text) + '</div>';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function wizChatSend(){
  var input = document.getElementById('wiz-chat-input');
  var text = input ? input.value.trim() : '';
  if(!text) return;
  input.value = '';
  input.disabled = true;
  _wizChatHistory.push({role: 'user', content: text});
  wizChatAppend('user', text);

  // Show typing indicator
  var container = document.getElementById('wiz-chat-messages');
  var typing = document.createElement('div');
  typing.id = 'chat-typing';
  typing.style.cssText = 'align-self:flex-start;color:var(--muted);font-size:.78rem;padding:4px 8px';
  typing.textContent = '…';
  container.appendChild(typing);
  container.scrollTop = container.scrollHeight;

  fetch('/api/chat-goal', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({messages: _wizChatHistory})
  })
  .then(function(r){ return r.json(); })
  .then(function(d){
    var t = document.getElementById('chat-typing');
    if(t) t.remove();
    if(d.error){
      wizChatAppend('assistant', '⚠️ Error: ' + d.error);
    } else {
      if(d.reply) {
        _wizChatHistory.push({role: 'assistant', content: d.reply});
        wizChatAppend('assistant', d.reply);
      }
      if(d.ready && d.md){
        // Show generated MD
        var preview = document.getElementById('wiz-chat-md-preview');
        var mdArea  = document.getElementById('wiz-chat-generated-md');
        if(preview) preview.style.display = 'block';
        if(mdArea)  mdArea.value = d.md;
        wizChatAppend('assistant', '✅ Research goal is ready! You can review and edit the generated experiment.md below, then click Next →');
      }
    }
    if(input) input.disabled = false;
    if(input) input.focus();
  })
  .catch(function(e){
    var t = document.getElementById('chat-typing');
    if(t) t.remove();
    wizChatAppend('assistant', '⚠️ Network error: ' + e.message);
    if(input) input.disabled = false;
  });
}


// ─────────────── PROJECT MANAGEMENT ───────────────
function loadSettingsProjects(){
  var el = document.getElementById('settings-projects-list');
  if(!el) return;
  el.innerHTML = '<span style="color:var(--muted)">Loading...</span>';
  var _activeId = (window._stateCache && window._stateCache.checkpoint_id) || '';
  fetch('/api/checkpoints').then(r=>r.json()).then(function(ckpts){
    if(!ckpts || !ckpts.length){ el.innerHTML='<span style="color:var(--muted)">No projects found.</span>'; return; }
    el.innerHTML = ckpts.map(function(c){
      var isActive = (c.id === _activeId);
      var isRunning = c.status === 'running';
      var borderColor = isActive ? 'var(--primary)' : 'var(--border)';
      var runBadge = isRunning ? '<span style="background:rgba(16,185,129,.2);color:#10b981;border-radius:12px;padding:2px 8px;font-size:.72rem;font-weight:700">● Running</span>' : '';
      var activeBadge = isActive ? '<span style="background:rgba(59,130,246,.2);color:#3b82f6;border-radius:12px;padding:2px 8px;font-size:.72rem;font-weight:700">Active</span>' : '';
      return '<div style="display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--card);border:1px solid '+borderColor+';border-radius:8px">'
        +'<div style="flex:1;min-width:0">'
        +'<div title="'+c.id+'" style="font-size:.85rem;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:360px">'+c.id+'</div>'
        +'<div style="font-size:.75rem;color:var(--muted);margin-top:2px">'+c.node_count+' nodes · '+new Date(c.mtime*1000).toLocaleString()+'</div>'
        +'<div style="margin-top:4px;display:flex;gap:6px">'+runBadge+activeBadge+'</div>'
        +'</div>'
        +'<button class="btn btn-sm" style="background:rgba(239,68,68,.15);color:#ef4444;border:1px solid rgba(239,68,68,.3);white-space:nowrap" '
        +'onclick="deleteProject(this.dataset.id, this.dataset.path)" data-id="'+c.id+'" data-path="'+c.path+'">🗑 Delete</button>'
        +'</div>';
    }).join('');
  }).catch(function(){ el.innerHTML='<span style="color:var(--red)">Failed to load projects.</span>'; });
}

function deleteProject(id, path){
  if(!confirm('Delete project "'+id+'"? This cannot be undone.')) return;
  fetch('/api/delete-checkpoint',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:id,path:path})
  }).then(r=>r.json()).then(function(d){
    if(d.ok){ loadSettingsProjects(); }
    else { alert('Delete failed: '+(d.error||'unknown error')); }
  });
}

// ─────────────── D3 TREE ───────────────
var _d3Simulation = null;

function renderTreeD3(){
  var svgEl = document.getElementById('tree-d3-svg');
  if(!svgEl || !nodesData || !nodesData.length) return;

  var filterStatus = (document.getElementById('tree-filter-status')||{}).value||'';
  var filterDepth  = (document.getElementById('tree-filter-depth')||{}).value||'';
  var nodes = nodesData.slice();
  if(filterStatus) nodes = nodes.filter(function(n){ return (n.status||'')===filterStatus; });
  if(filterDepth!==''){
    var fd=parseInt(filterDepth);
    if(fd===3) nodes=nodes.filter(function(n){ return (n.depth||0)>=3; });
    else nodes=nodes.filter(function(n){ return (n.depth||0)===fd; });
  }

  if(typeof d3 === 'undefined'){
    svgEl.innerHTML = '<text x="20" y="40" fill="red">D3.js not loaded — check network connection</text>';
    return;
  }

  var _rect = svgEl.getBoundingClientRect();
  var _rect = svgEl.getBoundingClientRect();
  var W = (_rect.width  > 100 ? _rect.width  : svgEl.clientWidth)  || 900;
  var H = (_rect.height > 100 ? _rect.height : svgEl.clientHeight) || 500;
  if(W < 100) W = 900;
  if(H < 100) H = 500;

  var LABEL_COLORS = {draft:'#3b82f6',improve:'#8b5cf6',ablation:'#f59e0b',debug:'#ef4444',validation:'#10b981'};
  var NW=160, NH=62;

  // Build tree hierarchy
  var idMap = {};
  nodes.forEach(function(n){ idMap[n.id]=n; });
  var root = nodes.find(function(n){ return !n.parent_id || !idMap[n.parent_id]; });
  if(!root) root = nodes[0];

  // Stratify
  var treeData;
  try {
    var strat = d3.stratify()
      .id(function(d){ return d.id; })
      .parentId(function(d){ return idMap[d.parent_id] ? d.parent_id : null; });
    treeData = strat(nodes);
  } catch(e) {
    // Fallback: just use the nodes without hierarchy
    treeData = null;
  }

  // Clear previous content
  d3.select(svgEl).selectAll('*').remove();
  var svg = d3.select(svgEl);

  // Zoomable container
  var g = svg.append('g').attr('class','tree-g');
  var _zoomBehavior = d3.zoom().scaleExtent([0.2,3]).on('zoom', function(event){
    g.attr('transform', event.transform);
  });
  svg.call(_zoomBehavior);

  // Compute initial positions with d3.tree
  var posMap = {};
  if(treeData){
    var treeLayout = d3.tree().nodeSize([NW+30, NH+60]);
    treeLayout(treeData);
    treeData.descendants().forEach(function(d){
      posMap[d.id] = {x: d.x + W/2, y: d.y + 40};
    });
  } else {
    // Grid fallback
    nodes.forEach(function(n,i){
      var depth = n.depth||0;
      var col = nodes.filter(function(x){ return (x.depth||0)===depth; });
      var idx = col.indexOf(n);
      posMap[n.id] = {x: 40 + depth*(NW+60), y: 40 + idx*(NH+50)};
    });
  }

  // ── Draw edges (lines) ──
  var links = nodes.filter(function(n){ return n.parent_id && posMap[n.parent_id]; });
  var edgeSel = g.selectAll('.tree-edge')
    .data(links)
    .enter()
    .append('path')
    .attr('class', 'tree-edge')
    .attr('id', function(d){ return 'edge-d3-'+d.id; })
    .attr('fill','none')
    .attr('stroke', function(d){ return LABEL_COLORS[d.label]||'rgba(59,130,246,.5)'; })
    .attr('stroke-width', 1.8)
    .attr('opacity', 0.7)
    .attr('d', function(d){ return _edgePath(posMap[d.parent_id], posMap[d.id], NW, NH); });

  // ── Draw node groups ──
  var nodeSel = g.selectAll('.tree-node-g')
    .data(nodes)
    .enter()
    .append('g')
    .attr('class','tree-node-g')
    .attr('cursor','pointer')
    .attr('transform', function(d){ var p=posMap[d.id]; return 'translate('+(p.x-NW/2)+','+(p.y)+')'; })
    .call(d3.drag()
      .on('start', function(event, d){ d3.select(this).raise(); })
      .on('drag',  function(event, d){
        posMap[d.id].x += event.dx;
        posMap[d.id].y += event.dy;
        d3.select(this).attr('transform','translate('+(posMap[d.id].x-NW/2)+','+(posMap[d.id].y)+')');
        // Update connected edges immediately
        g.selectAll('.tree-edge').filter(function(e){ return e.id===d.id || e.parent_id===d.id; })
          .attr('d', function(e){
            return _edgePath(posMap[e.parent_id]||posMap[e.id], posMap[e.id], NW, NH);
          });
        window._nodeDragged = true;
      })
      .on('end', function(){ setTimeout(function(){ window._nodeDragged=false; },100); })
    )
    .on('click', function(event, d){
      if(!window._nodeDragged) selectNode(d.id);
      event.stopPropagation();
    });

  // Node rect
  nodeSel.append('rect')
    .attr('width', NW).attr('height', NH)
    .attr('rx', 8).attr('ry', 8)
    .attr('fill', 'rgba(30,41,59,0.9)')
    .attr('stroke', function(d){ return LABEL_COLORS[d.label||'']||'rgba(71,85,105,0.8)'; })
    .attr('stroke-width', 1.5);

  // Label text (top-left)
  nodeSel.append('text')
    .attr('x', 8).attr('y', 18)
    .attr('fill', function(d){ return LABEL_COLORS[d.label||'']||'#94a3b8'; })
    .attr('font-size', '11px').attr('font-weight','700')
    .text(function(d){ return (d.label||d.node_type||'node').slice(0,12); });

  // Label badge
  nodeSel.append('rect')
    .attr('x', NW-60).attr('y', 6)
    .attr('width', 54).attr('height', 16)
    .attr('rx',8).attr('ry',8)
    .attr('fill', function(d){ var c=LABEL_COLORS[d.label||'']; return c?c+'33':'rgba(100,116,139,.2)'; });
  nodeSel.append('text')
    .attr('x', NW-33).attr('y', 18)
    .attr('fill', function(d){ return LABEL_COLORS[d.label||'']||'#94a3b8'; })
    .attr('font-size','9px').attr('text-anchor','middle')
    .text(function(d){ return (d.label||'').slice(0,8); });

  // Node ID (short)
  nodeSel.append('text')
    .attr('x',8).attr('y',34)
    .attr('fill','#64748b').attr('font-size','10px').attr('font-family','monospace')
    .text(function(d){ return d.id.slice(-8); });

  // Status badge
  nodeSel.append('rect')
    .attr('x',8).attr('y',40).attr('width',50).attr('height',15).attr('rx',6)
    .attr('fill',function(d){
      return d.status==='success'?'rgba(16,185,129,.2)':d.status==='failed'?'rgba(239,68,68,.2)':'rgba(59,130,246,.2)';
    });
  nodeSel.append('text')
    .attr('x',33).attr('y',51).attr('text-anchor','middle')
    .attr('fill',function(d){
      return d.status==='success'?'#10b981':d.status==='failed'?'#ef4444':'#3b82f6';
    })
    .attr('font-size','9px')
    .text(function(d){ return (d.status||'').slice(0,8); });

  // Score
  nodeSel.filter(function(d){ var s=d.scientific_score||(d.metrics&&d.metrics._scientific_score); return s!=null; })
    .append('text')
    .attr('x',NW-8).attr('y',54).attr('text-anchor','end')
    .attr('fill','#60a5fa').attr('font-size','10px').attr('font-weight','700')
    .text(function(d){
      var s=d.scientific_score||(d.metrics&&d.metrics._scientific_score)||0;
      return s.toFixed(2);
    });

  // Fit-to-viewport with padding
  window._d3PosMap = posMap;
  var allX = Object.values(posMap).map(function(p){ return p.x; });
  var allY = Object.values(posMap).map(function(p){ return p.y; });
  if(allX.length){
    var pad = 24;
    var minX = Math.min.apply(null, allX) - NW/2;
    var maxX = Math.max.apply(null, allX) + NW/2;
    var minY = Math.min.apply(null, allY);
    var maxY = Math.max.apply(null, allY) + NH;
    var treeW = maxX - minX;
    var treeH = maxY - minY;
    var scaleX = (W - pad*2) / treeW;
    var scaleY = (H - pad*2) / treeH;
    var scale = Math.min(scaleX, scaleY, 1.0);
    var tx = pad - minX * scale + ((W - pad*2) - treeW * scale) / 2;
    var ty = pad - minY * scale;
    _zoomBehavior.transform(svg, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  window._d3NodeSel = nodeSel;
  window._d3EdgeSel = edgeSel;
  window._d3G = g;
}

(function(){
  if(window._treeResizeObserver) return;
  if(typeof ResizeObserver === 'undefined') return;
  window._treeResizeObserver = new ResizeObserver(function(){
    var pg = document.getElementById('page-tree');
    if(pg && pg.classList.contains('active')) {
      clearTimeout(window._treeResizeTimer);
      window._treeResizeTimer = setTimeout(renderTreeD3, 100);
    }
  });
  setTimeout(function(){
    var el = document.getElementById('tree-pan-wrapper');
    if(el) window._treeResizeObserver.observe(el);
  }, 500);
})();

// Auto-re-render when SVG container resizes
(function(){
  if(window._treeResizeObserver) return;
  if(typeof ResizeObserver === 'undefined') return;
  window._treeResizeObserver = new ResizeObserver(function(){
    var pg = document.getElementById('page-tree');
    if(pg && pg.classList.contains('active')) renderTreeD3();
  });
  setTimeout(function(){
    var el = document.getElementById('tree-pan-wrapper');
    if(el) window._treeResizeObserver.observe(el);
  }, 500);
})();

function _edgePath(p, c, NW, NH){
  if(!p||!c) return '';
  var px=p.x, py=p.y+NH;
  var cx=c.x, cy=c.y;
  var midY=(py+cy)/2;
  return 'M'+px+','+py+' C'+px+','+midY+' '+cx+','+midY+' '+cx+','+cy;
}

function _d3ResetLayout(){
  renderTreeD3();
}

// Alias for backward compat
function renderTree(){ renderTreeD3(); }



// ─────────────── GPU Monitor ───────────────
async function startGpuMonitor() {
  document.getElementById('gpu-monitor-status').textContent = '起動中...';
  const r = await fetch('/api/gpu-monitor', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'start'})}).then(r=>r.json()).catch(e=>({ok:false,error:e.message}));
  refreshGpuStatus();
}
async function stopGpuMonitor() {
  document.getElementById('gpu-monitor-status').textContent = '停止中...';
  await fetch('/api/gpu-monitor', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'stop'})}).then(r=>r.json()).catch(()=>{});
  refreshGpuStatus();
}
async function refreshGpuStatus() {
  const r = await fetch('/api/gpu-monitor').then(r=>r.json()).catch(()=>({running:false,pid:null,log:''}));
  const s = document.getElementById('gpu-monitor-status');
  s.textContent = r.running ? ('🟢 Running (PID: '+r.pid+') | OLLAMA_HOST: '+(r.ollama_host||'—')) : '⬛ Stopped';
  s.style.color = r.running ? '#22c55e' : 'var(--muted)';
  const logEl = document.getElementById('gpu-monitor-log');
  if(logEl && r.log) logEl.textContent = r.log;
}

// ── Global state polling (every 5s) ──────────────────
var _pollInterval = null;
function startGlobalPolling(){
  if(_pollInterval) return;
  _pollInterval = setInterval(function(){
    fetch('/state').then(r=>r.json()).then(function(d){
      if(!d) return;
      window._stateCache = d;
      // Update run indicator
      var ri=document.getElementById('run-indicator');
      var ii=document.getElementById('idle-indicator');
      if(ri&&ii){ var isR=!!d.running_pid; ri.style.display=isR?'':'none'; ii.style.display=isR?'none':''; }
      // Update status badge
      var sb=document.getElementById('run-status-badge');
      if(sb){ var isR=!!d.running_pid; sb.textContent=d.status_label||(isR?'🟢 Running':'⬛ Stopped'); sb.className='badge '+(isR?'badge-green':''); }
      // Update phase stepper
      updatePhaseStepper(d);
      // Update monitor stats if on monitor page
      if(document.getElementById('page-monitor') && document.getElementById('page-monitor').style.display!=='none'){
        nodesData = d.nodes || nodesData;
        updateMonitorStats();
        renderMonitorTree();
        updateIdeaCard(d);
      }
      // Update idea page if visible
      if(document.getElementById('page-idea') && document.getElementById('page-idea').style.display!=='none'){
        window._stateCache = d;
        loadIdeaPage();
      }
      // Auto-update ACTIVE PROJECT dropdown
      var sel=document.getElementById('active-project-sel');
      if(sel && d.checkpoint_id){
        var found=false;
        for(var i=0;i<sel.options.length;i++){ if(sel.options[i].value===d.checkpoint_id){found=true;break;} }
        if(!found){
          // New checkpoint detected — refresh project list
          loadProjectList();
        } else if(sel.value!==d.checkpoint_id && d.running_pid){
          sel.value=d.checkpoint_id;
          if(typeof onProjectChange==='function') onProjectChange(d.checkpoint_id);
        }
      }
    }).catch(function(){});
  }, 5000);
}

// ── Phase stepper update ─────────────────────────────
function updatePhaseStepper(state){
  var phaseMap = {
    'starting': 'starting',
    'idea': 'idea',
    'bfts': 'bfts',
    'idle': 'bfts',
    'coding': 'bfts',      // coding is part of BFTS
    'evaluation': 'bfts',  // evaluation is part of BFTS
    'eval': 'bfts',
    'paper': 'paper',
    'review': 'review',
    'done': 'review'
  };
  var order = ['starting','idea','bfts','paper','review'];
  var rawPhase = (state && (state.current_phase || '')) || '';
  var activeId = phaseMap[rawPhase] || (state && state.running_pid ? 'bfts' : null);
  var activeIdx = activeId ? order.indexOf(activeId) : -1;

  order.forEach(function(p, i){
    var el = document.getElementById('pstep-'+p);
    if(!el) return;
    el.classList.remove('active','done');
    if(i < activeIdx) el.classList.add('done');
    else if(i === activeIdx) el.classList.add('active');
  });

  // Update model badge
  var mb = document.getElementById('mon-model-badge');
  if(mb && state){
    var m = state.llm_model_actual
      || (Object.values(state.actual_models||{}).filter((v,i,a)=>a.indexOf(v)===i).join(', '))
      || state.llm_model
      || (state.experiment_config && state.experiment_config.llm_model)
      || '—';
    mb.textContent = 'model: '+m;
  }
  // Disable Resume button when already running
  var btnR = document.getElementById('btn-resume');
  if(btnR) {
    var isRunning = !!(state && (state.is_running || state.running));
    btnR.disabled = isRunning;
    btnR.title = isRunning
      ? '⚠ Experiment already running (PID '+(state.running_pid||state.pid||'?')+') — stop it first'
      : 'Resume BFTS tree exploration from checkpoint';
    btnR.style.opacity = isRunning ? '0.5' : '';
  }
}
// ─────────────────────────────────────────────────────

startGlobalPolling();
// ─────────────────────────────────────────────────────
