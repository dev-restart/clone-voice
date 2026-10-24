from __future__ import annotations

import argparse
import gc
import os
import random
import shutil
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import librosa
import numpy as np
import soundfile as sf
import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local SoulX-Singer AI cover job.")
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--preprocess-model-dir", type=Path, required=True)
    parser.add_argument("--whisper-model-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-voice", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--cfg-scale", type=float, default=2.0)
    parser.add_argument("--pitch-shift", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--auto-shift", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--separate-vocals", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mix-accompaniment", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def clear_mps_cache() -> None:
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


def prepare_prompt(source: Path, destination: Path, max_seconds: int = 30) -> None:
    waveform, _ = librosa.load(source, sr=24000, mono=True)
    waveform = waveform[: max_seconds * 24000]
    if waveform.size < 24000:
        raise RuntimeError("기준 목소리는 잡음이 적은 1초 이상의 음성이 필요합니다.")
    sf.write(destination, waveform, 24000)


def separate_source(args: argparse.Namespace, target_vocal: Path, accompaniment: Path) -> None:
    from preprocess.tools.vocal_separation.model import VocalSeparator

    separator_dir = args.preprocess_model_dir / "mel-band-roformer-karaoke"
    separator = VocalSeparator(
        sep_model_path=str(separator_dir / "mel_band_roformer_karaoke_becruily.ckpt"),
        sep_config_path=str(separator_dir / "config_karaoke_becruily.yaml"),
        der_model_path="",
        der_config_path="",
        device=args.device,
        chunk_length_sec=5,
        use_der=False,
    )
    separated = separator.process(str(args.source))
    sf.write(target_vocal, separated.vocals_dereverbed.T, separated.sample_rate)
    sf.write(accompaniment, separated.accompaniment.T, separated.sample_rate)
    del separated, separator
    clear_mps_cache()


def use_source_as_vocal(source: Path, target_vocal: Path) -> None:
    waveform, sample_rate = librosa.load(source, sr=None, mono=True)
    sf.write(target_vocal, waveform, sample_rate)


def extract_f0(args: argparse.Namespace, prompt: Path, target_vocal: Path, prompt_f0: Path, target_f0: Path) -> None:
    from preprocess.tools.f0_extraction import F0Extractor

    duration = max(librosa.get_duration(path=str(prompt)), librosa.get_duration(path=str(target_vocal)))
    extractor = F0Extractor(
        str(args.preprocess_model_dir / "rmvpe/rmvpe.pt"),
        device=args.device,
        max_duration=max(30, duration + 1),
        verbose=True,
    )
    extractor.process(str(prompt), f0_path=str(prompt_f0))
    extractor.process(str(target_vocal), f0_path=str(target_f0))
    del extractor
    clear_mps_cache()


def run_svc(
    args: argparse.Namespace,
    prompt: Path,
    target_vocal: Path,
    prompt_f0: Path,
    target_f0: Path,
    generated_dir: Path,
) -> int:
    from cli.inference_svc import process
    from scripts.mlx_bridge import load_component_state
    from soulxsinger.models.soulxsinger_svc import SoulXSingerSVC
    from soulxsinger.utils.file_utils import load_config

    config = load_config(str(args.repo_dir / "soulxsinger/config/soulxsinger.yaml"))
    model = SoulXSingerSVC(config).to(args.device)
    model.load_state_dict(load_component_state(args.model_dir, "svc"), strict=True)
    model.eval().to(args.device)
    inference_args = SimpleNamespace(
        device=args.device,
        prompt_wav_path=str(prompt),
        target_wav_path=str(target_vocal),
        prompt_f0_path=str(prompt_f0),
        target_f0_path=str(target_f0),
        save_dir=str(generated_dir),
        auto_shift=args.auto_shift,
        pitch_shift=args.pitch_shift,
        n_steps=args.steps,
        cfg=args.cfg_scale,
        use_fp16=False,
    )
    process(inference_args, config, model)
    generated_shift = int(inference_args.pitch_shift)
    del model
    clear_mps_cache()
    return generated_shift


def accompaniment_shift(semitones: int) -> int:
    shifted = abs(semitones) % 12 * (-1 if semitones < 0 else 1)
    if shifted > 6:
        shifted -= 12
    if shifted < -6:
        shifted += 12
    return shifted


def mix_cover(generated: Path, accompaniment: Path, output: Path, pitch_shift: int) -> None:
    backing, sample_rate = sf.read(accompaniment, always_2d=True, dtype="float32")
    shift = accompaniment_shift(pitch_shift)
    if shift:
        backing = librosa.effects.pitch_shift(backing.T, sr=sample_rate, n_steps=shift).T
    vocal, _ = librosa.load(generated, sr=sample_rate, mono=True)
    output_length = max(len(backing), len(vocal))
    mixed = np.zeros((output_length, backing.shape[1]), dtype=np.float32)
    mixed[: len(backing)] = backing
    mixed[: len(vocal)] += vocal[:, None]
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.98:
        mixed *= 0.98 / peak
    sf.write(output, mixed, sample_rate)


def main() -> None:
    started_at = perf_counter()
    args = parse_args()
    args.repo_dir = args.repo_dir.resolve()
    args.model_dir = args.model_dir.resolve()
    args.preprocess_model_dir = args.preprocess_model_dir.resolve()
    args.whisper_model_dir = args.whisper_model_dir.resolve()
    args.source = args.source.resolve()
    args.target_voice = args.target_voice.resolve()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("SoulX-Singer requires an Apple Silicon MPS runtime on this Mac.")
    if not 1 <= args.steps <= 32:
        raise ValueError("steps must be between 1 and 32")
    if not 0.5 <= args.cfg_scale <= 4.0:
        raise ValueError("cfg-scale must be between 0.5 and 4.0")

    sys.path.insert(0, str(args.repo_dir))
    os.environ["SOULX_WHISPER_MODEL"] = str(args.whisper_model_dir)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    prompt = args.output_dir / "prompt.wav"
    target_vocal = args.output_dir / "target-vocal.wav"
    accompaniment = args.output_dir / "accompaniment.wav"
    prompt_f0 = args.output_dir / "prompt-f0.npy"
    target_f0 = args.output_dir / "target-f0.npy"
    generated_dir = args.output_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    prepare_prompt(args.target_voice, prompt)
    stage_started = perf_counter()
    if args.separate_vocals:
        separate_source(args, target_vocal, accompaniment)
    else:
        use_source_as_vocal(args.source, target_vocal)
    print(f"[SoulX-Singer] vocal preparation: {perf_counter() - stage_started:.2f}s", flush=True)
    stage_started = perf_counter()
    extract_f0(args, prompt, target_vocal, prompt_f0, target_f0)
    print(f"[SoulX-Singer] F0 extraction: {perf_counter() - stage_started:.2f}s", flush=True)
    stage_started = perf_counter()
    generated_shift = run_svc(args, prompt, target_vocal, prompt_f0, target_f0, generated_dir)
    print(f"[SoulX-Singer] SVC inference: {perf_counter() - stage_started:.2f}s", flush=True)

    generated = generated_dir / "generated.wav"
    output = args.output_dir / "final.wav"
    if args.mix_accompaniment and args.separate_vocals and accompaniment.exists():
        mix_cover(generated, accompaniment, output, generated_shift)
    else:
        shutil.copyfile(generated, output)
    print(f"SoulX-Singer output: {output}", flush=True)
    print(f"[SoulX-Singer] total: {perf_counter() - started_at:.2f}s", flush=True)


if __name__ == "__main__":
    main()
