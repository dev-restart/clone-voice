"""Never persist an upstream's echoed credential; keep API/plan provenance distinct."""
import json

import pytest

from app.config import Settings
from app.services import ai_api_client as wire
from app.services.ai_api_profiles import ProfileInput
from app.services.ai_text_provider_service import AiTextCompletion
from app.services.sound_effect_prompt_service import plan_sound_effect_prompt
from app.schemas import SoundEffectPromptPlan


@pytest.mark.parametrize('protocol', ['openai_chat', 'anthropic_messages', 'openai_responses'])
def test_upstream_auth_echo_is_blocked_in_normal_generation(protocol, monkeypatch):
    key = 'synthetic-test-only-token'
    profile = ProfileInput(name='QA', base_url='http://127.0.0.1:19999/v1', protocol=protocol,
                           models=[{'id': 'qa-model'}]).model_dump(exclude={'api_key'}) | {'id': 'api-qa'}
    text = json.dumps({'en': 'A response containing ' + key})
    if protocol == 'openai_chat':
        payload = {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]}
    elif protocol == 'anthropic_messages':
        payload = {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}
    else:
        payload = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                   'content': [{'type': 'output_text', 'text': text}]}]}
    monkeypatch.setattr(wire, '_http_json', lambda *args, **kwargs: payload)
    with pytest.raises(wire.ApiCallError) as error:
        wire.AiApiClient(profile, key, scope='qa', local_only=True).complete('source', 'system', 'qa-model')
    assert error.value.code == 'credential_in_response'
    assert key not in str(error.value)


@pytest.mark.parametrize('provider,expected', [
    ('apple', 'local-llm'), ('local', 'local-llm'),
    ('chatgpt', 'subscription-llm'), ('kimi', 'subscription-llm'),
    ('api-qa', 'api-llm'), ('compatible', 'api-llm'), ('nvidia', 'api-llm'),
])
def test_sound_planner_reports_connection_type(provider, expected, tmp_path, monkeypatch):
    settings = Settings(_env_file=None, storage_dir=tmp_path)
    monkeypatch.setattr('app.services.sound_effect_prompt_service.AiTextProviderService.complete',
        lambda self, *args, **kwargs: AiTextCompletion(
            json.dumps({'generation_prompt': 'A soft button click.', 'duration_seconds': 2}), provider, 'qa-model'))
    plan = plan_sound_effect_prompt('버튼 효과음', settings)
    assert plan.planner == expected
    validated = SoundEffectPromptPlan.model_validate(vars(plan))
    assert validated.provider == provider and validated.planner == expected
