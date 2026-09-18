#!/usr/bin/env bash
# Fetch the local model weights the voice path needs. Weights are not committed (.gitignore).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)/backend"
DEST="${VAANIOS_MODEL_DIR:-$ROOT/models}"
mkdir -p "$DEST"

SILERO_URL="https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
SILERO_DEST="$DEST/silero_vad.onnx"

if [ -f "$SILERO_DEST" ]; then
  echo "silero_vad.onnx already present ($(stat -c%s "$SILERO_DEST") bytes)"
else
  echo "fetching Silero VAD v5..."
  curl -sSL -o "$SILERO_DEST" "$SILERO_URL"
  echo "wrote $SILERO_DEST ($(stat -c%s "$SILERO_DEST") bytes)"
fi

# A truncated download would fail at inference with an opaque ONNX error, so check the size here.
size=$(stat -c%s "$SILERO_DEST")
if [ "$size" -lt 1000000 ]; then
  echo "silero_vad.onnx looks truncated ($size bytes); delete it and retry" >&2
  exit 1
fi
echo "done."
