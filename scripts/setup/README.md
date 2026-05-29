# scripts/setup

Installer step scripts and shared shell helpers sourced by the top-level setup flow.

## Contents

- `README.md` — this file.
- `banner.sh` — ASCII banner printer.
- `colors.sh` — shared ANSI color definitions.
- `detect_env.sh` — detect OS, shell, Python, pip, git.
- `install_core.sh` — install core Python dependencies.
- `install_deps.sh` — install/orchestrate component dependencies.
- `install_frontend.sh` — install the viz frontend (npm).
- `install_latex.sh` — install the LaTeX toolchain.
- `install_letta.sh` — install/deploy the Letta memory backend.
- `install_paperbench.sh` — install the PaperBench vendor stack.
- `install_pdf.sh` — install PDF tooling.
- `lang_select.sh` — interactive setup-language selection.
- `messages.sh` — localized setup message strings.
- `setup_env.sh` — bootstrap `ARI/.env` with the env vars the program reads.
- `spinner.sh` — terminal spinner/progress helper.
- `verify.sh` — post-install verification checks.
