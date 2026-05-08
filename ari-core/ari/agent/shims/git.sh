#!/usr/bin/env bash
# ari git shim — only intercepts ``git clone`` whose URL matches the paper's
# code_availability_ref. Every other git subcommand is passed through to the
# real git binary unchanged.
#
# Wired into the reproducibility sandbox by ari.agent.react_driver:
#   PATH=<sandbox>/.shims:<orig_path>
#   ARI_REAL_GIT=$(command -v git)
#   ARI_REPRO_CODE_AVAIL_REF=...    (the paper's curated bundle ref)
#   ARI_REPRO_CODE_AVAIL_SHA256=... (64-hex bundle digest)
#   ARI_REPRO_CLONE_POLICY=passthrough|deny|warn  (default: passthrough)
#   ARI_REPRO_CLONE_LOG=<sandbox>/repro_clone_log.jsonl
#
# Logs every clone attempt to ARI_REPRO_CLONE_LOG as JSONL so downstream
# tooling can surface the count + breakdown if needed.

set -e

REAL_GIT="${ARI_REAL_GIT:-/usr/bin/git}"
PAPER_REF="${ARI_REPRO_CODE_AVAIL_REF:-}"
PAPER_SHA="${ARI_REPRO_CODE_AVAIL_SHA256:-}"
POLICY="${ARI_REPRO_CLONE_POLICY:-passthrough}"
LOG="${ARI_REPRO_CLONE_LOG:-/dev/null}"

_log_event() {
  # $1=action ("rewrite"|"passthrough"|"deny"|"warn"|"noop")
  # $2=requested_url   $3=resolved_ref (optional)
  local ts action url resolved
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  action="$1"; url="$2"; resolved="${3:-}"
  if [ -n "$LOG" ] && [ "$LOG" != "/dev/null" ]; then
    mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
    printf '{"ts":"%s","action":"%s","url":%s,"resolved":%s,"policy":"%s"}\n' \
      "$ts" "$action" \
      "$(printf '%s' "$url" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
      "$(printf '%s' "$resolved" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
      "$POLICY" >> "$LOG" 2>/dev/null || true
  fi
}

# Pass through anything that's not "clone" untouched.
if [ "${1:-}" != "clone" ]; then
  exec "$REAL_GIT" "$@"
fi

# Find the URL argument (first positional after `clone`, skipping flags).
shift
URL=""
ARGS=()
SAW_URL=0
for arg in "$@"; do
  if [ $SAW_URL -eq 0 ] && [ "${arg#-}" = "$arg" ]; then
    URL="$arg"
    SAW_URL=1
  else
    ARGS+=("$arg")
  fi
done

# If we didn't see a URL, just pass through (covers `git clone --help`, etc.)
if [ -z "$URL" ]; then
  _log_event "noop" "" ""
  exec "$REAL_GIT" clone "$@"
fi

_url_matches_paper_ref() {
  local u="$1" r="$2"
  [ -z "$r" ] && return 1
  # Direct match (covers ari://, gh:, doi:, https:// of curated bundle).
  [ "$u" = "$r" ] && return 0
  # gh: → equivalent https://github.com/<user>/<repo> form.
  case "$r" in
    gh:*)
      local repo="${r#gh:}"
      [ "$u" = "https://github.com/$repo" ] && return 0
      [ "$u" = "https://github.com/$repo.git" ] && return 0
      [ "$u" = "git@github.com:$repo.git" ] && return 0
      ;;
  esac
  return 1
}

if _url_matches_paper_ref "$URL" "$PAPER_REF"; then
  # Rewrite to ari clone with strict digest verification.
  DEST="${ARGS[0]:-}"
  if [ -z "$DEST" ]; then
    DEST="$(basename "$URL" .git)"
  fi
  _log_event "rewrite" "$URL" "$PAPER_REF"
  if [ -z "$PAPER_SHA" ]; then
    echo "ari git shim: refusing to rewrite — ARI_REPRO_CODE_AVAIL_SHA256 unset" >&2
    exit 13
  fi
  exec ari clone "$PAPER_REF" "$DEST" --expect-sha256 "$PAPER_SHA"
fi

# URL doesn't match the paper's curated ref. Apply policy.
case "$POLICY" in
  deny)
    _log_event "deny" "$URL" ""
    echo "ari git shim: external git clone denied by clone_policy: $URL" >&2
    exit 13
    ;;
  warn)
    _log_event "warn" "$URL" ""
    echo "ari git shim: clone outside curated bundle: $URL (warn)" >&2
    exec "$REAL_GIT" clone "$URL" "${ARGS[@]}"
    ;;
  passthrough|*)
    _log_event "passthrough" "$URL" ""
    exec "$REAL_GIT" clone "$URL" "${ARGS[@]}"
    ;;
esac
