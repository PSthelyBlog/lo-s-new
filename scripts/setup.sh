#!/usr/bin/env bash
# Download what the student needs: a llama.cpp build and the model lo-s was built with.
# Usage: scripts/setup.sh [llama] [model]      (both, when neither is named)
#
# They go into runtime/ in this project, or into LOS_RUNTIME when that is set, which is where
# scripts/serve.sh looks. That is about 16 GB, nearly all of it the model. Nothing is installed
# outside that folder, and deleting it undoes this. A download that stops is taken up again
# where it stopped the next time.
#
# The build is the one for Linux on x64 with an NVIDIA card. For another machine, put a build of
# your own in llama.cpp/llama-b*/ under that folder, or serve the model some other way and say
# where in los.toml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${LOS_RUNTIME:-$ROOT/runtime}"
BUILD=b11146        # the llama.cpp build lo-s was built and measured with
CUDA=13.4
RELEASE="https://github.com/ggml-org/llama.cpp/releases/download/$BUILD"
MODEL="https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf/resolve/main/gemma-4-26B_q4_0-it.gguf"

fetch() {   # URL FILE: download once, and mark the file when all of it has arrived
    mkdir -p "$(dirname "$2")"
    [ -f "$2.done" ] && return 0
    curl -L --fail --retry 20 --retry-delay 5 --retry-all-errors -C - -sS -o "$2" "$1"
    touch "$2.done"
}

llama() {   # the build, and the CUDA runtime it was built against
    mkdir -p "$RUNTIME/llama.cpp"
    for archive in "llama-$BUILD-bin-ubuntu-cuda-$CUDA-x64" "cudart-llama-$BUILD-bin-ubuntu-cuda-$CUDA-x64"; do
        fetch "$RELEASE/$archive.tar.gz" "$RUNTIME/dl/$archive.tar.gz"
        tar -xzf "$RUNTIME/dl/$archive.tar.gz" -C "$RUNTIME/llama.cpp"
    done
}

model() {   # saved under the name los.toml and scripts/serve.sh use
    fetch "$MODEL" "$RUNTIME/models/gemma-4-26B-A4B-it-qat-q4_0.gguf"
}

[ $# -eq 0 ] && set -- llama model
for step in "$@"; do
    case "$step" in
        llama|model) "$step"; echo "$(date +%T) done: $step, in $RUNTIME" ;;
        *) echo "Usage: scripts/setup.sh [llama] [model]" >&2; exit 2 ;;
    esac
done
