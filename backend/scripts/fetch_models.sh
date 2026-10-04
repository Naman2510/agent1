#!/usr/bin/env bash
# Fetch the local model weights the voice path needs. Weights are not committed (.gitignore).
# The same pinned file and checksum are used by infra/docker/backend.Dockerfile.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)/backend"
DEST="${VAANIOS_MODEL_DIR:-$ROOT/models}"
mkdir -p "$DEST"

# Silero VAD v6.2, pinned to a release tag and verified by hash: `master` moves, and a different
# model would silently change what counts as speech.
SILERO_URL="https://raw.githubusercontent.com/snakers4/silero-vad/v6.2/src/silero_vad/data/silero_vad.onnx"
SILERO_SHA256="1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
SILERO_DEST="$DEST/silero_vad.onnx"

if [ -f "$SILERO_DEST" ]; then
  echo "silero_vad.onnx already present"
else
  echo "fetching Silero VAD v6.2..."
  curl -sSL --fail -o "$SILERO_DEST" "$SILERO_URL"
fi

if ! echo "$SILERO_SHA256  $SILERO_DEST" | sha256sum --check --status; then
  echo "silero_vad.onnx does not match the pinned v6.2 checksum; delete it and retry" >&2
  exit 1
fi
echo "done: $SILERO_DEST (v6.2, checksum verified)"
