#!/usr/bin/env bash
# ============================================================================
# messages.sh — i18n message catalog (en / ja / zh)
# ============================================================================

# shellcheck disable=SC2034

msg_detecting_env_en="Sniffing out your environment..."
msg_detecting_env_ja="環境をチェック中..."
msg_detecting_env_zh="正在检测您的环境..."

msg_os_en="Operating system"
msg_os_ja="OS"
msg_os_zh="操作系统"

msg_shell_en="Shell"
msg_shell_ja="シェル"
msg_shell_zh="Shell"

msg_win_warn_en="Native Windows detected. ARI works best under WSL2."
msg_win_warn_ja="Windows が検出されました。ARI は WSL2 上での利用を推奨します。"
msg_win_warn_zh="检测到 Windows。ARI 在 WSL2 上运行效果最佳。"

msg_python_not_found_en="Python 3.10+ not found. Please install it first!"
msg_python_not_found_ja="Python 3.10+ が見つかりません。先にインストールしてください！"
msg_python_not_found_zh="未找到 Python 3.10+，请先安装！"

msg_python_old_en="found but version too old"
msg_python_old_ja="バージョンが古いのでスキップ"
msg_python_old_zh="版本过旧，跳过"

msg_pip_missing_en="pip not found — installing..."
msg_pip_missing_ja="pip が見つかりません — インストール中..."
msg_pip_missing_zh="未找到 pip — 正在安装..."

msg_pip_fail_en="Cannot install pip. Please install it manually."
msg_pip_fail_ja="pip をインストールできません。手動でインストールしてください。"
msg_pip_fail_zh="无法安装 pip，请手动安装。"

msg_git_missing_en="git not found. Not needed now, but you'll need it later."
msg_git_missing_ja="git が見つかりません。今は不要ですが後で必要になります。"
msg_git_missing_zh="未找到 git。现在不需要，但之后会用到。"

msg_step1_en="Installing ARI core + skill plugins..."
msg_step1_ja="ARI コアとスキルプラグインをインストール中..."
msg_step1_zh="正在安装 ARI 核心和技能插件..."

msg_core_ok_en="ari-core installed — brain ready!"
msg_core_ok_ja="ari-core インストール完了 — 頭脳準備OK！"
msg_core_ok_zh="ari-core 安装完成 — 大脑就绪！"

msg_core_fail_en="ari-core not found"
msg_core_fail_ja="ari-core が見つかりません"
msg_core_fail_zh="未找到 ari-core"

msg_skills_ok_en="skill(s) installed — arms & legs ready!"
msg_skills_ok_ja="個のスキルをインストール — 手足も準備OK！"
msg_skills_ok_zh="个技能已安装 — 四肢就绪！"

msg_step2_en="Installing Python dependencies..."
msg_step2_ja="Python 依存パッケージをインストール中..."
msg_step2_zh="正在安装 Python 依赖..."

msg_deps_ok_en="Dependencies all good!"
msg_deps_ok_ja="依存パッケージOK！"
msg_deps_ok_zh="依赖安装完成！"

msg_step3_en="Setting up PDF tools (optional)..."
msg_step3_ja="PDFツールをセットアップ中（オプション）..."
msg_step3_zh="正在设置 PDF 工具（可选）..."

msg_conda_trying_en="conda found — trying poppler + chktex..."
msg_conda_trying_ja="conda を発見 — poppler + chktex をインストール中..."
msg_conda_trying_zh="发现 conda — 正在安装 poppler + chktex..."

msg_conda_none_en="conda not available — no worries, pymupdf handles it"
msg_conda_none_ja="conda なし — 大丈夫、pymupdf で代替します"
msg_conda_none_zh="没有 conda — 没关系，pymupdf 可以处理"

msg_step4_en="Checking LaTeX (optional — for paper generation)..."
msg_step4_ja="LaTeX をチェック中（オプション — 論文生成用）..."
msg_step4_zh="正在检查 LaTeX（可选 — 用于论文生成）..."

msg_latex_missing_en="pdflatex not found — no worries, papers will still be generated as .tex"
msg_latex_missing_ja="pdflatex が見つかりません — 大丈夫、.tex として論文は生成されます"
msg_latex_missing_zh="未找到 pdflatex — 没关系，论文仍会以 .tex 格式生成"

msg_step5_en="Building dashboard frontend..."
msg_step5_ja="ダッシュボードフロントエンドをビルド中..."
msg_step5_zh="正在构建仪表盘前端..."

msg_frontend_ok_en="Dashboard frontend built!"
msg_frontend_ok_ja="ダッシュボードフロントエンドのビルド完了！"
msg_frontend_ok_zh="仪表盘前端构建完成！"

msg_frontend_skip_en="Node.js not found — skipping frontend build (dashboard will use fallback)"
msg_frontend_skip_ja="Node.js が見つかりません — フロントエンドビルドをスキップ（フォールバック使用）"
msg_frontend_skip_zh="未找到 Node.js — 跳过前端构建（将使用备用方案）"

msg_step6_en="Final checks..."
msg_step6_ja="最終チェック..."
msg_step6_zh="最终检查..."

msg_import_fail_en="import failed"
msg_import_fail_ja="インポート失敗"
msg_import_fail_zh="导入失败"

msg_cli_not_in_path_en="'ari' not in PATH — add ~/.local/bin:"
msg_cli_not_in_path_ja="'ari' が PATH にありません — ~/.local/bin を追加:"
msg_cli_not_in_path_zh="'ari' 不在 PATH 中 — 请添加 ~/.local/bin:"

msg_cli_fail_en="ari CLI not found"
msg_cli_fail_ja="ari CLI が見つかりません"
msg_cli_fail_zh="未找到 ari CLI"

msg_done_en="All good! The ants are ready to work!"
msg_done_ja="準備完了！蟻たちが研究を始めます！"
msg_done_zh="一切就绪！蚂蚁们准备开工！"

msg_done_errors_en="component(s) had issues — check messages above"
msg_done_errors_ja="個のコンポーネントに問題あり — 上のメッセージを確認"
msg_done_errors_zh="个组件有问题 — 请查看上方消息"

msg_next_en="What's next?"
msg_next_ja="次のステップ"
msg_next_zh="下一步"

msg_next_model_en="Pick your AI model:"
msg_next_model_ja="AIモデルを選ぼう:"
msg_next_model_zh="选择你的 AI 模型:"

msg_next_run_en="Run your first experiment:"
msg_next_run_ja="最初の実験を実行:"
msg_next_run_zh="运行第一个实验:"

msg_next_dash_en="Open the dashboard (the fun part!):"
msg_next_dash_ja="ダッシュボードを開く（ここからが楽しい！）:"
msg_next_dash_zh="打开仪表盘（好玩的部分！）:"

msg_tip_rc_en="Tip: Add exports to %s to make them permanent."
msg_tip_rc_ja="ヒント: %s に export を追加すると永続化できます。"
msg_tip_rc_zh="提示: 将 export 添加到 %s 可永久生效。"

# Helper: get localized message
m() {
  local key="msg_${1}_${SETUP_LANG}"
  echo "${!key}"
}
