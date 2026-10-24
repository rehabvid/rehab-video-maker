#!/usr/bin/env bash
# Download the ComfyUI models used by the EchoMimic V3-Flash-Pro avatar path.
#
# Usage:
#   ./download_models.sh [COMFYUI_DIR]
#
# Default COMFYUI_DIR is ./tools/ComfyUI relative to the repository root.
# The script is idempotent; Hugging Face resumes partial downloads.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMFY="${1:-$ROOT/tools/ComfyUI}"
HF="${HF:-$COMFY/.venv/bin/hf}"

if [[ ! -x "$HF" ]]; then
  echo "error: hf CLI not found at $HF" >&2
  echo "Install ComfyUI first, or set HF=/path/to/hf." >&2
  exit 1
fi

STAGE="$COMFY/.hf-downloads"
mkdir -p "$STAGE" \
  "$COMFY/models/echo_mimic/transformer" \
  "$COMFY/models/echo_mimic/echomimicv3-flash-pro" \
  "$COMFY/models/echo_mimic/chinese-wav2vec2-base" \
  "$COMFY/models/vae" \
  "$COMFY/models/text_encoders" \
  "$COMFY/models/clip" \
  "$COMFY/models/clip_vision"

echo "==> Wan2.1-Fun-V1.1-1.3B-InP transformer + VAE"
"$HF" download alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP \
  diffusion_pytorch_model.safetensors config.json Wan2.1_VAE.pth \
  --local-dir "$STAGE/wan"
mv -f "$STAGE/wan/diffusion_pytorch_model.safetensors" \
  "$COMFY/models/echo_mimic/transformer/diffusion_pytorch_model.safetensors"
mv -f "$STAGE/wan/config.json" \
  "$COMFY/models/echo_mimic/transformer/config.json"
mv -f "$STAGE/wan/Wan2.1_VAE.pth" "$COMFY/models/vae/Wan2.1_VAE.pth"

echo "==> EchoMimic V3 Flash Pro transformer"
"$HF" download BadToBest/EchoMimicV3 \
  echomimicv3-flash-pro/config.json \
  echomimicv3-flash-pro/diffusion_pytorch_model.safetensors \
  --local-dir "$COMFY/models/echo_mimic"

echo "==> Chinese wav2vec2 audio encoder"
"$HF" download TencentGameMate/chinese-wav2vec2-base \
  config.json preprocessor_config.json pytorch_model.bin \
  chinese-wav2vec2-base-fairseq-ckpt.pt \
  --local-dir "$COMFY/models/echo_mimic/chinese-wav2vec2-base"

echo "==> Wan text encoder + CLIP vision"
# The old repo name redirects to Comfy-Org/Wan-2.1, which is the canonical
# name and avoids a slow redirect on some networks.
"$HF" download Comfy-Org/Wan-2.1 \
  split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
  split_files/clip_vision/clip_vision_h.safetensors \
  --local-dir "$STAGE/comfy-org"
mv -f "$STAGE/comfy-org/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
  "$COMFY/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
mv -f "$STAGE/comfy-org/split_files/clip_vision/clip_vision_h.safetensors" \
  "$COMFY/models/clip_vision/clip_vision_h.safetensors"

# The upstream EchoMimic example workflow uses this filename. A symlink is
# enough and avoids downloading the same 1.26 GB file twice.
ln -sfn clip_vision_h.safetensors \
  "$COMFY/models/clip_vision/clip_vision_h_wan.safetensors"

# ComfyUI's CLIPLoader looks in models/text_encoders first but several
# workflows still reference models/clip. Expose the same file there too.
ln -sfn ../text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
  "$COMFY/models/clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors"

rm -rf "$STAGE"

echo
echo "Done. Model layout:"
find "$COMFY/models/echo_mimic" "$COMFY/models/vae" \
  "$COMFY/models/text_encoders" "$COMFY/models/clip_vision" \
  -maxdepth 3 -type f -o -type l | sort
