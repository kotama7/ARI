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

msg_setup_env_title_en="Configuring .env (API keys + defaults)..."
msg_setup_env_title_ja=".env を設定中（APIキー + デフォルト値）..."
msg_setup_env_title_zh="正在配置 .env（API 密钥 + 默认值）..."

msg_setv_creating_en="Creating new .env at"
msg_setv_creating_ja=".env を新規作成:"
msg_setv_creating_zh="正在创建新的 .env:"

msg_setv_found_en="Existing .env found —"
msg_setv_found_ja="既存の .env を検出 —"
msg_setv_found_zh="检测到已有 .env —"

msg_setv_already_set_en="already set in .env — skipped"
msg_setv_already_set_ja="既に .env に設定済み — スキップ"
msg_setv_already_set_zh="已在 .env 中 — 已跳过"

msg_setv_enter_skip_en="Enter to skip"
msg_setv_enter_skip_ja="Enter でスキップ"
msg_setv_enter_skip_zh="按 Enter 跳过"

msg_setv_saved_en="saved"
msg_setv_saved_ja="保存しました"
msg_setv_saved_zh="已保存"

msg_setv_skipped_en="skipped (left commented)"
msg_setv_skipped_ja="スキップ（コメントアウト）"
msg_setv_skipped_zh="已跳过（保留注释）"

msg_setv_skip_noninteractive_en="non-interactive — left commented"
msg_setv_skip_noninteractive_ja="非対話モード — コメントのみ追加"
msg_setv_skip_noninteractive_zh="非交互模式 — 仅添加注释"

msg_setv_done_en=".env ready"
msg_setv_done_ja=".env の準備完了"
msg_setv_done_zh=".env 准备就绪"

msg_setv_current_en="current"
msg_setv_current_ja="現在値"
msg_setv_current_zh="当前值"

msg_setv_default_en="default"
msg_setv_default_ja="デフォルト"
msg_setv_default_zh="默认值"

msg_setv_enter_keep_en="Enter to keep"
msg_setv_enter_keep_ja="Enter で維持"
msg_setv_enter_keep_zh="按 Enter 保持"

msg_setv_or_replace_en="or type a new value"
msg_setv_or_replace_ja="または新しい値を入力"
msg_setv_or_replace_zh="或输入新值"

msg_setv_pick_or_custom_en="Pick a number or type a custom value (Enter for default)"
msg_setv_pick_or_custom_ja="番号を選択するか任意の値を入力（Enterでデフォルト）"
msg_setv_pick_or_custom_zh="选择编号或输入自定义值（按 Enter 使用默认）"

msg_setv_letta_emb_label_en="Letta embedding handle for archival memory"
msg_setv_letta_emb_label_ja="Letta archival メモリの埋め込みハンドル"
msg_setv_letta_emb_label_zh="Letta archival 内存的嵌入句柄"

msg_setv_letta_emb_hint_en="The historical 'letta-default' (= letta/letta-free) endpoint has been retired upstream and now returns 404 for every embedding request. Pick an OpenAI handle (BYO key) or type a self-hosted handle you have registered with this Letta server."
msg_setv_letta_emb_hint_ja="従来の 'letta-default'（= letta/letta-free）は上流で廃止され、すべての埋め込みリクエストが 404 を返します。OpenAI ハンドル（自前の OPENAI_API_KEY が必要）を選ぶか、Letta サーバに登録済みの自前ハンドルを入力してください。"
msg_setv_letta_emb_hint_zh="旧的 'letta-default'（= letta/letta-free）已被上游停用，所有嵌入请求都会返回 404。请选择 OpenAI 句柄（需自备 OPENAI_API_KEY），或输入已在此 Letta 服务器注册的自托管句柄。"

msg_setv_letta_emb_dead_en="this handle is no longer reachable upstream — strongly recommend changing"
msg_setv_letta_emb_dead_ja="このハンドルは上流で到達不能です — 変更を強く推奨"
msg_setv_letta_emb_dead_zh="该句柄上游已不可达 — 强烈建议更换"

msg_setv_letta_sif_label_en="Letta SIF image (Apptainer/Singularity)"
msg_setv_letta_sif_label_ja="Letta SIF イメージ（Apptainer/Singularity）"
msg_setv_letta_sif_label_zh="Letta SIF 镜像（Apptainer/Singularity）"

msg_setv_letta_sif_hint_en="Path used by scripts/letta/start_singularity.sh. Pulled from docker://letta/letta:latest if missing on first start. Pin a custom path here for shared/cached images."
msg_setv_letta_sif_hint_ja="scripts/letta/start_singularity.sh が参照するパスです。初回起動時に docker://letta/letta:latest から pull されます。共有/キャッシュ済みのイメージを使う場合はここで指定。"
msg_setv_letta_sif_hint_zh="scripts/letta/start_singularity.sh 使用的路径。如果缺失，首次启动时会从 docker://letta/letta:latest 拉取。若需使用共享/缓存的镜像请在此指定。"

msg_import_fail_en="import failed"
msg_import_fail_ja="インポート失敗"
msg_import_fail_zh="导入失败"

msg_cli_not_in_path_en="'ari' not on PATH — add this repo's venv:"
msg_cli_not_in_path_ja="'ari' が PATH にありません — リポジトリの .venv を PATH に:"
msg_cli_not_in_path_zh="'ari' 不在 PATH 中 — 请将仓库的 .venv 加入 PATH:"

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

msg_next_paper_en="Generate a paper from results:"
msg_next_paper_ja="結果から論文を生成:"
msg_next_paper_zh="从结果生成论文:"

msg_next_projects_en="List all projects:"
msg_next_projects_ja="全プロジェクトを一覧表示:"
msg_next_projects_zh="列出所有项目:"

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
