#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/home/ma-user/work/ShiboSu/models/Qwen3-VL-8B-Instruct}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3-vl-8b-instruct}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18000}"
ASCEND_DEVICES="${ASCEND_DEVICES:-0}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.70}"
LOG_FILE="${LOG_FILE:-/root/qwen3vl_vllm.log}"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"

source_if_exists() {
  local file="$1"
  if [[ -f "$file" ]]; then
    # shellcheck disable=SC1090
    set +u
    source "$file"
    set -u
  fi
}

model_ready() {
  [[ -s "$MODEL_DIR/config.json" ]] || return 1
  [[ -s "$MODEL_DIR/model.safetensors.index.json" ]] || return 1
  for shard in \
    model-00001-of-00004.safetensors \
    model-00002-of-00004.safetensors \
    model-00003-of-00004.safetensors \
    model-00004-of-00004.safetensors
  do
    [[ -s "$MODEL_DIR/$shard" ]] || return 1
  done
}

if curl -fsS "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
  echo "vLLM already serving on port ${PORT}."
  exit 0
fi

while ! model_ready; do
  echo "$(date '+%F %T') waiting for complete model files in ${MODEL_DIR}..."
  sleep "$CHECK_INTERVAL"
done

source_if_exists /usr/local/Ascend/ascend-toolkit/set_env.sh
source_if_exists /usr/local/Ascend/nnal/atb/set_env.sh

export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICES"
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-max_split_size_mb:256}"

exec vllm serve "$MODEL_DIR" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --trust-remote-code \
  --enforce-eager \
  > "$LOG_FILE" 2>&1
