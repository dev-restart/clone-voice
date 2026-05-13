from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

_LANGUAGE_TAGS = {
    "zh": "<|zh|>",
    "cn": "<|zh|>",
    "chinese": "<|zh|>",
    "en": "<|en|>",
    "english": "<|en|>",
    "ja": "<|ja|>",
    "jp": "<|ja|>",
    "japanese": "<|ja|>",
    "yue": "<|yue|>",
    "cantonese": "<|yue|>",
    "ko": "<|ko|>",
    "kr": "<|ko|>",
    "korean": "<|ko|>",
}


def _write_result(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _resolve_model_dir(repo_dir: Path, model_dir: str, allow_download: bool) -> str:
    raw = model_dir.strip()
    path = Path(raw).expanduser()
    if path.is_absolute():
        if path.exists():
            return str(path)
        if allow_download:
            return raw
        raise FileNotFoundError(f"CosyVoice model directory was not found: {path}")
    repo_path = repo_dir / path
    if repo_path.exists():
        return str(repo_path)
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return str(cwd_path)
    if allow_download:
        return raw
    raise FileNotFoundError(f"CosyVoice model directory was not found: {repo_path}")


def _to_numpy(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 2:
        if 1 in array.shape:
            array = np.squeeze(array)
        elif array.shape[0] < array.shape[1]:
            array = array[0]
    return np.ravel(array).astype(np.float32)


def _collect_waveform(outputs) -> np.ndarray:
    chunks = []
    for item in outputs:
        if not isinstance(item, dict) or "tts_speech" not in item:
            continue
        chunk = _to_numpy(item["tts_speech"])
        if chunk.size:
            chunks.append(chunk)
    if not chunks:
        raise RuntimeError("CosyVoice did not produce speech samples.")
    return np.concatenate(chunks)


def _with_end_prompt(text: str | None) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if "<|endofprompt|>" in cleaned:
        return cleaned
    return f"{cleaned}<|endofprompt|>"


def _cross_lingual_text(text: str, language: str | None) -> str:
    cleaned = text.strip()
    if cleaned.startswith("<|"):
        return cleaned
    tag = _LANGUAGE_TAGS.get((language or "").strip().lower())
    return f"{tag}{cleaned}" if tag else cleaned


def _infer(model, payload: dict):
    text = str(payload["text"]).strip()
    prompt_wav = payload.get("prompt_wav")
    prompt_text = (payload.get("prompt_text") or "").strip()
    prefer_voice_clone = bool(payload.get("prefer_voice_clone", False))
    default_spk_id = (payload.get("default_spk_id") or "").strip()
    instruct = (payload.get("instruct") or "").strip()
    speed = float(payload.get("speed") or 1.0)
    text_frontend = bool(payload.get("text_frontend", True))
    language = payload.get("language")
    common = {"stream": False, "speed": speed, "text_frontend": text_frontend}

    if prompt_wav:
        prompt_path = str(Path(prompt_wav).expanduser().resolve())
        if prefer_voice_clone:
            if prompt_text:
                return model.inference_zero_shot(text, prompt_text, prompt_path, **common)
            return model.inference_cross_lingual(_cross_lingual_text(text, language), prompt_path, **common)
        if instruct and hasattr(model, "inference_instruct2"):
            return model.inference_instruct2(text, _with_end_prompt(instruct), prompt_path, **common)
        if prompt_text:
            return model.inference_zero_shot(text, prompt_text, prompt_path, **common)
        return model.inference_cross_lingual(_cross_lingual_text(text, language), prompt_path, **common)

    if default_spk_id:
        if instruct and hasattr(model, "inference_instruct"):
            return model.inference_instruct(text, default_spk_id, _with_end_prompt(instruct), **common)
        if not hasattr(model, "inference_sft"):
            raise RuntimeError("Configured CosyVoice model does not expose SFT speaker inference.")
        return model.inference_sft(text, default_spk_id, **common)

    raise RuntimeError(
        "CosyVoice requires a reference voice or CLONE_VOICE_COSYVOICE_DEFAULT_SPK_ID / CLONE_VOICE_COSYVOICE_PROMPT_WAV."
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: run_cosyvoice.py <request.json>", file=sys.stderr)
        return 2
    request_path = Path(sys.argv[1]).resolve()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    result_json = Path(payload["result_json"]).resolve()
    try:
        repo_dir = Path(payload["repo_dir"]).expanduser().resolve()
        sys.path.insert(0, str(repo_dir))
        matcha_dir = repo_dir / "third_party" / "Matcha-TTS"
        if matcha_dir.exists():
            sys.path.insert(0, str(matcha_dir))
        from cosyvoice.cli.cosyvoice import AutoModel

        model_dir = _resolve_model_dir(repo_dir, payload["model_dir"], bool(payload.get("allow_model_download", False)))
        model = AutoModel(model_dir=model_dir, fp16=bool(payload.get("fp16", False)))
        sample_rate = int(getattr(model, "sample_rate", 24000) or 24000)
        if payload.get("check_only"):
            _write_result(result_json, {"ok": True, "sample_rate": sample_rate})
            return 0
        output_path = Path(payload["output_path"]).resolve()
        waveform = _collect_waveform(_infer(model, payload))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, waveform, sample_rate)
        _write_result(
            result_json,
            {
                "ok": True,
                "path": str(output_path),
                "duration_seconds": float(len(waveform) / sample_rate) if sample_rate else None,
                "sample_rate": sample_rate,
            },
        )
        return 0
    except Exception as exc:
        _write_result(result_json, {"ok": False, "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
