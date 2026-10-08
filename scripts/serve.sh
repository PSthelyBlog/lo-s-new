#!/usr/bin/env bash
# Start llama-server on the student model. Extra arguments go straight to llama-server.
# Usage: scripts/serve.sh [MODEL.gguf] [--threads N ...]
#
# LOS_RUNTIME is the folder that holds the llama.cpp build (llama.cpp/llama-b*/, with its CUDA
# runtime beside it in llama.cpp/cudart-*/) and the model files (models/). It defaults to
# runtime/ in this project. Point it at a folder you already have; nothing is downloaded here.
#
# The server is started the plain way: llama.cpp decides which weights go on the GPU, and its
# prompt cache stays on. Answers can differ from one start to the next, and lo-s does not rely
# on them being the same.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${LOS_RUNTIME:-$ROOT/runtime}"
LLAMA="$(echo "$RUNTIME"/llama.cpp/llama-b*)"
if [ ! -x "$LLAMA/llama-server" ]; then
    echo "No llama.cpp build under $RUNTIME/llama.cpp. Set LOS_RUNTIME to the folder that holds it." >&2
    exit 1
fi
export LD_LIBRARY_PATH="$LLAMA:$(echo "$RUNTIME"/llama.cpp/cudart-*)"
model="gemma-4-26B-A4B-it-qat-q4_0.gguf"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then model="$1"; shift; fi

# One slot and no thinking: a line gets one short answer.
# Only pages served from this machine may read the server's answers in a browser.
exec "$LLAMA/llama-server" -m "$RUNTIME/models/$model" --host 127.0.0.1 --port "${PORT:-8080}" \
    --ctx-size 8192 --parallel 1 --reasoning-budget 0 --cors-origins localhost "$@"
