from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import Settings
from app.schemas import VoiceProfile
from app.services.cosyvoice_service import CosyVoiceEngine


def load_cosyvoice_runner():
    runner_path = Path(__file__).resolve().parents[1] / "scripts" / "run_cosyvoice.py"
    spec = importlib.util.spec_from_file_location("run_cosyvoice_test_module", runner_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_fake_cosyvoice_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "CosyVoice"
    (repo / "cosyvoice" / "cli").mkdir(parents=True)
    (repo / "cosyvoice" / "cli" / "cosyvoice.py").write_text("# fake cosyvoice repo\n")
    model = repo / "pretrained_models" / "CosyVoice2-0.5B"
    model.mkdir(parents=True)
    return repo, model


def write_reference_wav(path: Path) -> None:
    sample_rate = 24000
    t = np.linspace(0, 0.3, int(sample_rate * 0.3), endpoint=False)
    waveform = (0.08 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(path, waveform, sample_rate)


def test_cosyvoice_status_is_unavailable_until_repo_and_model_are_configured(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path, cosyvoice_enabled=True, cosyvoice_repo_dir=tmp_path / "missing")
    engine = CosyVoiceEngine(settings)

    status = engine.status()

    assert status.loaded is False
    assert status.error
    assert "CosyVoice repo was not found" in status.error


def test_cosyvoice_status_accepts_local_repo_and_model_dir(tmp_path: Path):
    repo, _ = prepare_fake_cosyvoice_repo(tmp_path)
    settings = Settings(storage_dir=tmp_path, cosyvoice_enabled=True, cosyvoice_repo_dir=repo)
    engine = CosyVoiceEngine(settings)

    status = engine.status()

    assert status.error is None
    assert status.model_id == "pretrained_models/CosyVoice2-0.5B"


def test_cosyvoice_generate_uses_worker_payload_without_injecting_style_into_text(tmp_path: Path, monkeypatch):
    repo, _ = prepare_fake_cosyvoice_repo(tmp_path)
    reference = tmp_path / "voice.wav"
    write_reference_wav(reference)
    settings = Settings(storage_dir=tmp_path, cosyvoice_enabled=True, cosyvoice_repo_dir=repo, cosyvoice_python=sys.executable)
    engine = CosyVoiceEngine(settings)
    captured = {}

    def fake_run(command, cwd=None, capture_output=False, text=False, timeout=None, check=False):
        del cwd, capture_output, text, timeout, check
        request_path = Path(command[-1])
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        captured.update(payload)
        output_path = Path(payload["output_path"])
        write_reference_wav(output_path)
        result_path = Path(payload["result_json"])
        result_path.write_text(
            json.dumps({"ok": True, "path": str(output_path), "duration_seconds": 0.3, "sample_rate": 24000}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    voice = VoiceProfile(
        name="Narrator",
        transcript="참조 대본입니다.",
        audio_path=str(reference),
        audio_url="/api/files/voices/voice.wav",
    )

    output_path, duration = engine.generate(
        text="  이 대본만 읽어야 합니다.\n",
        voice=voice,
        instruct="차분하게, 다정하게",
        language="ko",
        speed=1.05,
    )

    assert output_path.exists()
    assert duration == 0.3
    assert captured["text"] == "이 대본만 읽어야 합니다."
    assert "차분하게" not in captured["text"]
    assert captured["instruct"] == "차분하게, 다정하게"
    assert captured["prompt_wav"] == str(reference.resolve())
    assert captured["prompt_text"] == "참조 대본입니다."
    assert captured["prefer_voice_clone"] is True
    assert captured["language"] == "ko"
    assert captured["speed"] == 1.05


def test_cosyvoice_runner_prioritizes_zero_shot_for_registered_voice_clone():
    runner = load_cosyvoice_runner()
    calls = []

    class FakeModel:
        def inference_instruct2(self, *args, **kwargs):
            calls.append(("instruct2", args, kwargs))
            return [{"tts_speech": np.array([0.1], dtype=np.float32)}]

        def inference_zero_shot(self, *args, **kwargs):
            calls.append(("zero_shot", args, kwargs))
            return [{"tts_speech": np.array([0.1], dtype=np.float32)}]

        def inference_cross_lingual(self, *args, **kwargs):
            calls.append(("cross_lingual", args, kwargs))
            return [{"tts_speech": np.array([0.1], dtype=np.float32)}]

    result = runner._infer(
        FakeModel(),
        {
            "text": "이 대본을 읽습니다.",
            "prompt_wav": "voice.wav",
            "prompt_text": "참조 대본입니다.",
            "prefer_voice_clone": True,
            "instruct": "차분하게<|endofprompt|>",
            "language": "ko",
            "speed": 1.0,
            "text_frontend": True,
        },
    )

    assert list(result)
    assert calls[0][0] == "zero_shot"
    assert calls[0][1][0] == "이 대본을 읽습니다."
    assert calls[0][1][1] == "참조 대본입니다."


def test_cosyvoice_runner_uses_cross_lingual_for_registered_voice_without_transcript():
    runner = load_cosyvoice_runner()
    calls = []

    class FakeModel:
        def inference_instruct2(self, *args, **kwargs):
            calls.append(("instruct2", args, kwargs))
            return [{"tts_speech": np.array([0.1], dtype=np.float32)}]

        def inference_cross_lingual(self, *args, **kwargs):
            calls.append(("cross_lingual", args, kwargs))
            return [{"tts_speech": np.array([0.1], dtype=np.float32)}]

    result = runner._infer(
        FakeModel(),
        {
            "text": "이 대본을 읽습니다.",
            "prompt_wav": "voice.wav",
            "prompt_text": "",
            "prefer_voice_clone": True,
            "instruct": "차분하게<|endofprompt|>",
            "language": "ko",
            "speed": 1.0,
            "text_frontend": True,
        },
    )

    assert list(result)
    assert calls[0][0] == "cross_lingual"
    assert calls[0][1][0].startswith("<|ko|>")
