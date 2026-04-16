#!/bin/bash
# gpu_ollama_monitor.sh
# GPU ノードで Ollama を起動 → ログインノードから autossh トンネルで localhost:11435 に転送
# 使い方: nohup bash ~/ARI/scripts/gpu_ollama_monitor.sh >> ~/ARI/logs/gpu_monitor.log 2>&1 &

SBATCH_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_ollama_gpu.sh"
# Settings live per-project under each checkpoint dir now.  We only push
# updates through the GUI API which rebinds them to whatever project is
# currently selected — there is no longer a global ~/.ari/settings.json.
NODE_FILE="${HOME}/ARI/logs/ollama_gpu_node.txt"
LOCK_FILE="${HOME}/ARI/logs/gpu_monitor.pid"
LOCAL_PORT=11435
CHECK_INTERVAL=60
MAX_WAIT=300

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }

# 多重起動防止
if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        log "Monitor already running (PID=$OLD_PID). Exiting."
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"; log "Monitor stopped."; kill_tunnel' EXIT

# トンネルプロセスを記録
TUNNEL_PID_FILE="${HOME}/ARI/logs/ssh_tunnel_gpu.pid"

kill_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        local pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
        rm -f "$TUNNEL_PID_FILE"
    fi
    fuser -k "${LOCAL_PORT}/tcp" 2>/dev/null || true
}

is_tunnel_alive() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        local pid=$(cat "$TUNNEL_PID_FILE")
        kill -0 "$pid" 2>/dev/null
    else
        return 1
    fi
}

start_tunnel() {
    local gpu_host="$1"
    local gpu_port="$2"
    kill_tunnel
    sleep 1
    log "Starting SSH tunnel: localhost:${LOCAL_PORT} → ${gpu_host}:${gpu_port}"
    # autossh が使えるか確認
    if command -v autossh >/dev/null 2>&1; then
        AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 -f -N \
            -o StrictHostKeyChecking=no \
            -o ServerAliveInterval=15 \
            -o ServerAliveCountMax=5 \
            -L "${LOCAL_PORT}:localhost:${gpu_port}" \
            "${gpu_host}" \
            > "${HOME}/ARI/logs/ssh_tunnel_gpu.log" 2>&1
    else
        ssh -f -N \
            -o StrictHostKeyChecking=no \
            -o ServerAliveInterval=15 \
            -o ServerAliveCountMax=5 \
            -L "${LOCAL_PORT}:localhost:${gpu_port}" \
            "${gpu_host}" \
            > "${HOME}/ARI/logs/ssh_tunnel_gpu.log" 2>&1
    fi
    sleep 2
    # PID を記録
    local pid
    pid=$(pgrep -f "ssh.*${LOCAL_PORT}:localhost:${gpu_port}.*${gpu_host}" | head -1)
    if [ -n "$pid" ]; then
        echo "$pid" > "$TUNNEL_PID_FILE"
        log "Tunnel PID: $pid"
        return 0
    else
        log "WARNING: Could not find tunnel PID"
        return 1
    fi
}

update_settings() {
    local host="$1"
    # Fetch current settings from the GUI (project-scoped), patch ollama_host,
    # and POST the merged document back.  No on-disk fallback — if the GUI is
    # not running or no project is selected the update is skipped.
    local payload
    payload=$(curl -s --max-time 5 http://localhost:9886/api/settings 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin) if sys.stdin else {}; d['ollama_host']='${host}'; print(json.dumps(d))" 2>/dev/null) || return 0
    [ -z "$payload" ] && return 0
    curl -s -X POST http://localhost:9886/api/save-settings \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null 2>&1 || true
    log "Pushed ollama_host=${host} to GUI"
}

submit_job() {
    log "Submitting SLURM job..."
    rm -f "$NODE_FILE"
    local jid
    jid=$(sbatch "$SBATCH_SCRIPT" 2>&1 | awk '/Submitted/{print $NF}')
    log "Job ID: $jid"
    echo "$jid"
}

wait_for_node() {
    local job_id="$1" waited=0
    log "Waiting for job $job_id to start..."
    while [ $waited -lt $MAX_WAIT ]; do
        local state
        state=$(squeue -j "$job_id" -h -o "%T" 2>/dev/null || echo "")
        if [ -z "$state" ]; then
            log "Job $job_id not in queue. Failed?"
            return 1
        fi
        if [ "$state" = "RUNNING" ] && [ -f "$NODE_FILE" ]; then
            cat "$NODE_FILE"
            return 0
        fi
        sleep 10; waited=$((waited + 10))
    done
    log "Timeout"
    return 1
}

is_job_running() {
    [ -n "$1" ] && [ "$(squeue -j "$1" -h -o "%T" 2>/dev/null)" = "RUNNING" ]
}

is_job_queued() {
    local state; state="$(squeue -j "$1" -h -o "%T" 2>/dev/null)"
    [ -n "$1" ] && { [ "$state" = "RUNNING" ] || [ "$state" = "PENDING" ]; }
}

test_ollama() {
    curl -s --max-time 3 "http://localhost:${LOCAL_PORT}/api/tags" | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK:', len(d.get('models',[])),'models')" 2>/dev/null
}

# ─── メインループ ───────────────────────────────────────────────
log "=== GPU Ollama Monitor started (PID=$$) ==="
CURRENT_JOB_ID=""

while true; do
    if [ -z "$CURRENT_JOB_ID" ] || ! is_job_queued "$CURRENT_JOB_ID"; then
        [ -n "$CURRENT_JOB_ID" ] && log "Job $CURRENT_JOB_ID ended. Resubmitting..."
        kill_tunnel

        CURRENT_JOB_ID=$(submit_job) || { sleep 60; continue; }
        [ -z "$CURRENT_JOB_ID" ] && { log "Submit failed."; sleep 60; continue; }

        NODE_INFO=$(wait_for_node "$CURRENT_JOB_ID") || {
            log "Node not ready. Retry in 30s."
            CURRENT_JOB_ID=""
            sleep 30
            continue
        }

        # ホスト:ポートをパース
        GPU_HOST="${NODE_INFO%%:*}"
        GPU_PORT="${NODE_INFO##*:}"

        # トンネルを張る
        start_tunnel "$GPU_HOST" "$GPU_PORT"

        # Ollama 疎通確認
        sleep 3
        if TEST=$(test_ollama); then
            log "Ollama tunnel working: $TEST"
            update_settings "http://localhost:${LOCAL_PORT}"
        else
            log "WARNING: Ollama tunnel test failed. Check ssh_tunnel_gpu.log"
        fi
    fi

    # トンネルが死んでいたら再接続
    if ! is_tunnel_alive && is_job_running "$CURRENT_JOB_ID"; then
        log "Tunnel died. Reconnecting to $GPU_HOST:$GPU_PORT..."
        start_tunnel "$GPU_HOST" "$GPU_PORT"
    fi

    sleep $CHECK_INTERVAL
done
