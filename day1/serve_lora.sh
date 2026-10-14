#!/bin/bash
# Start vLLM on the T4 with multi-LoRA, using the rig's tpu.env for every serving value (as ~/bin/vllm-t4
# does), without the drafter, and sample EngineCore RSS + swap every 2 s into $RSS_LOG (default day1/rss.<time>.log).
# Writes the rig's run/vllm.pid, so `vllm-t4 stop` stops it.
# usage: day1/serve_lora.sh <adapter_dir> [extra vllm args...]
set -e
rig=${VLLM_T4_RIG:-$HOME/gemma4-dev/gpu-vllm-t4-2b-w4a16}
here=$(cd "$(dirname "$0")" && pwd)
adapters=$1; shift
rigval() { sed -n "s/^$1=//p" "$rig/tpu.env" | tail -1; }
export PYTHONUSERBASE=$(rigval PYTHONUSERBASE) TMPDIR=$(rigval TMPDIR)
~/bin/vllm-t4 swap
mmflag=; [ "$(rigval LANGUAGE_MODEL_ONLY)" = true ] && mmflag=--language-model-only
mkdir -p "$rig/run"
echo "=== serve_lora $(date -Is) $*" >> "$rig/run/vllm.log"
nohup "$(rigval PYTHON_BIN)" -m vllm.entrypoints.openai.api_server \
  --model "$(rigval MODEL_NAME)" --host "$(rigval HOST)" --port "$(rigval PORT)" \
  --dtype "$(rigval DTYPE)" --kv-cache-dtype "$(rigval KV_CACHE_DTYPE)" \
  --tensor-parallel-size "$(rigval TENSOR_PARALLEL_SIZE)" \
  --gpu-memory-utilization "$(rigval GPU_MEMORY_UTILIZATION)" \
  --max-model-len "$(rigval MAX_MODEL_LEN)" --max-num-seqs "$(rigval MAX_NUM_SEQS)" $mmflag \
  --enable-lora --max-loras 2 --max-lora-rank 8 \
  --lora-modules zero="$adapters/zero" rand="$adapters/rand" \
  "$@" >> "$rig/run/vllm.log" 2>&1 &
pid=$!; disown; echo $pid > "$rig/run/vllm.pid"; echo "pid $pid"
nohup bash -c "while [ -d /proc/$pid ]; do
  e=\$(ps -eo pid=,ppid=,args= | awk '\$2==$pid && \$3==\"VLLM::EngineCore\"{print \$1; exit}')
  echo \"\$(date +%T) api_rss_kb=\$(awk '/VmRSS/{print \$2}' /proc/$pid/status 2>/dev/null) engine_rss_kb=\$(awk '/VmRSS/{print \$2}' /proc/\$e/status 2>/dev/null) engine_swap_kb=\$(awk '/VmSwap/{print \$2}' /proc/\$e/status 2>/dev/null) mem_avail_kb=\$(awk '/MemAvailable/{print \$2}' /proc/meminfo) swap_used_kb=\$(awk '/SwapTotal/{t=\$2}/SwapFree/{f=\$2}END{print t-f}' /proc/meminfo) vram_mib=\$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)\"
  sleep 2; done" > "${RSS_LOG:-$here/rss.$(date +%Y%m%dT%H%M%S).log}" 2>&1 &
disown
