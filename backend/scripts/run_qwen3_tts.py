"""One-shot Qwen3-TTS Base voice-clone runner. Experimental, called by Qwen3TTSAdapter.

Runs in its own interpreter because qwen-tts pins transformers==4.57.3 while the backend uses 5.x.
It reloads the model on every call, so it is only suitable for evaluation, not interactive use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="float32", choices=("float32", "float16", "bfloat16"))
    parser.add_argument("--ref-audio", required=True)
    parser.add_argument("--ref-text", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", default="Korean")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=400, help="~12.5 tokens per second of audio")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    if args.cache_dir:
        os.environ["HF_HUB_CACHE"] = args.cache_dir  # must be set before huggingface_hub is imported

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = Qwen3TTSModel.from_pretrained(
        args.model_id,
        device_map=device,
        dtype=getattr(torch, args.dtype),
        attn_implementation="sdpa",
        **({"local_files_only": True} if args.local_files_only else {}),
    )
    wavs, sample_rate = model.generate_voice_clone(
        text=args.text,
        language=args.language,
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        x_vector_only_mode=False,
        max_new_tokens=args.max_new_tokens,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, wavs[0], sample_rate)
    print(json.dumps({"sample_rate": int(sample_rate), "samples": int(len(wavs[0])), "device": device}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
