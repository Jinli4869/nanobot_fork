#!/usr/bin/env bash
set -euo pipefail

MODEL_ID="${MODEL_ID:-Qwen/Qwen3-VL-8B-Instruct}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3-vl-8b-instruct}"
MODEL_DIR="${MODEL_DIR:-/home/ma-user/work/ShiboSu/models/Qwen3-VL-8B-Instruct}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18000}"
ASCEND_DEVICES="${ASCEND_DEVICES:-0}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
MAX_BATCHED_TOKENS="${MAX_BATCHED_TOKENS:-16384}"
SKIP_PIP_INSTALL="${SKIP_PIP_INSTALL:-0}"
MODE="${1:-all}"

source_if_exists() {
  local file="$1"
  if [[ -f "$file" ]]; then
    # shellcheck disable=SC1090
    source "$file"
  fi
}

setup_ascend_env() {
  source_if_exists /usr/local/Ascend/ascend-toolkit/set_env.sh
  source_if_exists /usr/local/Ascend/nnal/atb/set_env.sh

  export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICES"
  export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-max_split_size_mb:256}"
}

download_model() {
  mkdir -p "$(dirname "$MODEL_DIR")"
  if [[ "$SKIP_PIP_INSTALL" != "1" ]]; then
    python -m pip install -U modelscope qwen_vl_utils
  fi
  modelscope download \
    --model "$MODEL_ID" \
    --local_dir "$MODEL_DIR"
}

serve_model() {
  setup_ascend_env
  command -v vllm >/dev/null 2>&1 || {
    echo "vllm command not found. Please run this inside the vllm-ascend image/environment." >&2
    exit 1
  }

  exec vllm serve "$MODEL_DIR" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --host "$HOST" \
    --port "$PORT" \
    --dtype bfloat16 \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-batched-tokens "$MAX_BATCHED_TOKENS" \
    --trust-remote-code \
    --enforce-eager
}

check_server() {
  curl -sS "http://127.0.0.1:${PORT}/v1/models"
}

case "$MODE" in
  download)
    download_model
    ;;
  serve)
    serve_model
    ;;
  check)
    check_server
    ;;
  all)
    download_model
    serve_model
    ;;
  *)
    echo "Usage: $0 [all|download|serve|check]" >&2
    exit 2
    ;;
esac
