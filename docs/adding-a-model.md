# 모델 추가하기

[English summary](#english-summary)

새 모델은 **어댑터 클래스 하나**를 등록하면 설정 → 모델의 해당 영역 목록과 각 작업 화면의 모델 선택에 나타납니다. 화면 코드는 고치지 않습니다.

## 영역

| 영역(domain) | capability 플래그 | 라우터 purpose | 호출되는 메서드 |
| --- | --- | --- | --- |
| 음성 `voice` | `tts` | `tts` | `generate(**kwargs)` |
| 커버 `cover` | `voice_conversion` | `voice_conversion` | `convert_voice(source_audio, target_voice, **kwargs)` |
| 효과음 `sfx` | `sound_effect_generation` | `sound_effect_generation` | `generate_sound_effect(**kwargs)` |
| 음악 `music` | `music_generation` | `music_generation` | 아직 호출하는 작업 화면이 없습니다. 영역과 선택 UI만 준비되어 있습니다. |

한 모델이 여러 capability를 가지면 여러 영역에 동시에 나타납니다. 대응표는 `backend/app/services/model_router.py`의 `DOMAIN_CAPABILITY`, `PURPOSE_DOMAIN`에 있습니다.

## 1. 어댑터 작성

`backend/app/services/model_router.py`(또는 여기서 import되는 모듈)에 `BaseModelAdapter`를 상속한 클래스를 만들고 `@register_adapter`를 붙입니다.

```python
@register_adapter
class MyVoiceAdapter(BaseModelAdapter):
    model_id = "my-voice"                      # 설정·API에서 쓰는 고유 id
    label = "My Voice"
    provider = "Example Lab"
    sample_rate = 24000
    homepage = "https://example.com/my-voice"  # 모델 카드에 표시 (모두 선택)
    license = "Apache-2.0"
    platforms = ("macOS", "Linux")
    install_command = "./download-models.sh --my-voice"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = MyVoiceEngine(settings)   # 무거운 로딩은 지연시키세요

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["한국어 낭독"], ["Narration"])   # 한/영 모두 제공

    def status(self) -> RuntimeModelStatus:
        engine = self.engine.status()
        return RuntimeModelStatus(
            id=self.model_id, label=self.label, provider=self.provider,
            enabled=self.settings.my_voice_enabled,
            loaded=engine.loaded,
            status="available" if engine.available else "unavailable",
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=engine.message,                # 설치 안내 등 사용자에게 보일 문장
        )

    def generate(self, **kwargs) -> EngineOutput:
        path, duration = self.engine.generate(**kwargs)
        return EngineOutput(path=path, duration_seconds=duration)
```

기존 `VoxCPMAdapter`, `SoulXSingerAdapter`, `StableAudioSfxAdapter`가 완성된 예시입니다. 사용자에게 보이는 문장은 `tr("한국어", "English")`로 두 언어를 모두 적습니다.

## 2. 설정 연결

`backend/app/config.py`에 켜고 끄는 값과 필요한 경로를 추가합니다.

```python
my_voice_enabled: bool = False
my_voice_model_path: Path | None = None
```

## 3. 등록 목록에 추가

환경에서 모델을 켭니다. `backend/.env`:

```env
CLONE_VOICE_REGISTERED_MODELS=voxcpm,soulx-singer,stable-audio-sfx,my-voice
CLONE_VOICE_MY_VOICE_ENABLED=true
```

모든 사용자에게 기본으로 포함하려면 `config.py`의 `DEFAULT_REGISTERED_MODELS`에 id를 추가합니다. 등록되지 않은 id는 경고만 남기고 무시됩니다.

## 4. 설치 스크립트 (선택)

모델을 내려받아야 한다면 `download-models.sh`에 옵션(`--my-voice`)과 `download_my_voice` 함수를 추가하고, 설치 후 `.env`에 켜는 값을 쓰도록 `enable_installed_models`에 한 줄을 더합니다. `install.sh`의 모델 선택 목록에도 같은 이름을 추가하면 처음 설치할 때 고를 수 있습니다.

## 5. 기본 모델과 사용 여부

앱을 실행하면 설정 → 모델에서 영역별로 기본 모델, 사용 여부, 순서를 정할 수 있습니다. 서버 기본값은 `CLONE_VOICE_DEFAULT_TTS_MODEL`, `CLONE_VOICE_DEFAULT_VC_MODEL`, `CLONE_VOICE_DEFAULT_SFX_MODEL`, `CLONE_VOICE_DEFAULT_MUSIC_MODEL`입니다. 음성·커버 영역은 최소 한 개의 모델이 켜져 있어야 합니다.

## 6. 테스트

`backend/tests/test_model_registry.py`를 참고해 다음을 확인합니다.

- 어댑터가 `ADAPTER_REGISTRY`에 등록되고 올바른 영역에 나타난다.
- 설치되지 않았을 때 `status()`가 예외 없이 `unavailable`과 안내 문장을 돌려준다.
- 실제 모델을 쓰지 않는 가짜 엔진으로 `generate`가 `EngineOutput`을 돌려준다.

```bash
cd backend && uv run pytest tests/test_model_registry.py
```

## English summary

Add a `BaseModelAdapter` subclass decorated with `@register_adapter` in `backend/app/services/model_router.py`, declare its `ModelCapabilities` (`tts`, `voice_conversion`, `sound_effect_generation`, or `music_generation`) and implement the matching method (`generate`, `convert_voice`, `generate_sound_effect`). Add its settings to `config.py`, list the id in `CLONE_VOICE_REGISTERED_MODELS`, and optionally add a `download-models.sh` option. The model then appears in Settings → Models under its area and in the model picker of the matching workspace. Write user-facing strings with `tr("한국어", "English")`. The `music` area has no workspace that calls a generator yet.
