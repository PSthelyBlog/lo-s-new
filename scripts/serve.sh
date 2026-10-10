#!/usr/bin/env bash
# Start llama-server on the student model. Extra arguments go straight to llama-server.
# Usage: scripts/serve.sh [MODEL.gguf] [--threads N ...]
#
# The llama.cpp build (llama.cpp/llama-b*/, with its CUDA runtime beside it in
# llama.cpp/cudart-*/) and the model files (models/) are looked for in runtime/ in this project,
# where scripts/setup.sh puts them. Set LOS_RUNTIME to use a folder you already have. Nothing is
# downloaded here.
#
# The server is started the plain way: llama.cpp decides which weights go on the GPU, and its
# prompt cache stays on. Answers can differ from one start to the next, and lo-s does not rely
# on them being the same.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${LOS_RUNTIME:-$ROOT/runtime}"
LLAMA="$(echo "$RUNTIME"/llama.cpp/llama-b*)"
if [ ! -x "$LLAMA/llama-server" ]; then
    echo "No llama.cpp build under $RUNTIME/llama.cpp." >&2
    echo "scripts/setup.sh downloads one there, with the model. If you have them already, set LOS_RUNTIME to the folder that holds them." >&2
    exit 1
fi
export LD_LIBRARY_PATH="$LLAMA:$(echo "$RUNTIME"/llama.cpp/cudart-*)"
model="gemma-4-26B-A4B-it-qat-q4_0.gguf"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then model="$1"; shift; fi
if [ ! -f "$RUNTIME/models/$model" ]; then
    echo "No model at $RUNTIME/models/$model. scripts/setup.sh model downloads the one lo-s was built with." >&2
    exit 1
fi

# One slot and no thinking: a line gets one short answer.
# Only pages served from this machine may read the server's answers in a browser.
exec "$LLAMA/llama-server" -m "$RUNTIME/models/$model" --host 127.0.0.1 --port "${PORT:-8080}" \
    --ctx-size 8192 --parallel 1 --reasoning-budget 0 --cors-origins localhost "$@"
