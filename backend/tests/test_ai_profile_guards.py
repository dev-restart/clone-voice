"""Regression checks for live policy changes and application task routing.

No real API credentials, external model requests, or host Keychain items are used.
"""
from contextlib import contextmanager
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.api.routes.settings import router as settings_router
from app.services import ai_api_client as wire
from app.services.ai_api_credentials import ApiCredentialVault, CredentialError
from app.services.ai_api_profiles import AiApiProfilesStore, ModelProfile, ProfileInput, RoutingInput
from app.services.ai_text_connections import AiTextConnectionsStore
from app.services.ai_text_provider_service import AiTextProviderService
from app.services.sound_effect_prompt_service import request_sound_effect_plan
from app.services.translation_service import OpenAICompatibleTranslator


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_dir=tmp_path, ai_text_settings_path=tmp_path / 'selection.json')


def new_request(name='QA', **changes):
    return ProfileInput.model_validate({
        'name': name, 'base_url': 'http://127.0.0.1:19001/v1',
        'auth_type': 'none', 'models': [{'id': 'test-model'}], **changes,
    })


@pytest.mark.parametrize('change', ['local_only', 'disable', 'delete'])
def test_queued_request_rechecks_policy_before_http(settings, monkeypatch, change):
    store = AiApiProfilesStore(settings)
    store.legacy.update({'local_only': False})
    request = new_request(base_url='https://example.test/v1')
    profile = store.save(request)
    service = AiTextProviderService(settings)

    @contextmanager
    def queued(*args):
        if change == 'local_only':
            store.legacy.update({'local_only': True})
        elif change == 'disable':
            store.save(request.model_copy(update={'enabled': False, 'expected_revision': profile['revision']}), profile['id'])
        else:
            store.delete(profile['id'], profile['revision'])
        yield

    monkeypatch.setattr(wire, 'connection_slot', queued)
    monkeypatch.setattr(wire, '_http_json', lambda *a, **kw: pytest.fail('An invalidated request must not be sent'))
    with pytest.raises(RuntimeError):
        service.complete('private source', system_prompt='system', provider_id=profile['id'], model_id='test-model')


def test_private_key_write_failure_removes_incomplete_file(settings, monkeypatch):
    vault = ApiCredentialVault(settings.storage_dir / 'test-secrets')
    def failed_fsync(fd):
        raise OSError('simulated disk failure')
    monkeypatch.setattr('app.services.ai_api_credentials.os.fsync', failed_fsync)
    with pytest.raises(CredentialError):
        vault.put('fake-test-only-key', 'private_file')
    assert list(vault.directory.iterdir()) == []


def test_keychain_vault_contract_without_host_access(settings, monkeypatch):
    vault = ApiCredentialVault(settings.storage_dir / 'test-secrets')
    entries = {}
    def fake_keychain(action, reference, secret=''):
        if action == 'add':
            entries[reference] = secret
        elif action == 'delete':
            entries.pop(reference, None)
        else:
            return entries[reference]
        return ''
    monkeypatch.setattr(vault, '_keychain', fake_keychain)
    reference = vault.put('fake-test-only-key', 'keychain')
    assert vault.get(reference, 'keychain') == 'fake-test-only-key'
    vault.delete(reference, 'keychain')
    assert entries == {} and not vault.directory.exists()


def test_legacy_settings_validation_does_not_echo_key(settings):
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        result = client.put('/api/ai/providers/connections', json={'provider_id': 'invalid', 'api_key': 'fake-test-only-key'})
        assert result.status_code == 422
        assert 'fake-test-only-key' not in result.text
        result = client.put('/api/ai/providers/connections', json={'local_only': False}, headers={'Origin': 'https://untrusted.test'})
        assert result.status_code == 403
        assert AiTextConnectionsStore(settings).get()['local_only']


def test_model_list_cannot_reflect_auth_key(settings, monkeypatch):
    profile = new_request().model_dump(exclude={'api_key'}) | {'id': 'api-qa'}
    monkeypatch.setattr(wire, '_http_json', lambda *a, **kw: {'data': [
        {'id': 'fake-test-only-key'},
        {'id': 'usable-model', 'name': 'Echo fake-test-only-key'},
    ]})
    result = wire.AiApiClient(profile, 'fake-test-only-key', scope='qa', local_only=True).models()
    assert result['models'][0]['id'] == 'usable-model'
    assert 'fake-test-only-key' not in json.dumps(result)


def test_anthropic_temperature_range():
    with pytest.raises(ValidationError):
        new_request(protocol='anthropic_messages', models=[{'id': 'qa', 'temperature': 1.5}])
    assert new_request(protocol='anthropic_messages', models=[{'id': 'qa', 'temperature': 1}]).models[0].temperature == 1


@pytest.mark.parametrize('protocol', ['openai_chat', 'openai_responses'])
def test_structured_output_and_token_field(protocol, monkeypatch):
    model = ModelProfile(id='qa', structured_output='json_schema', token_parameter='max_completion_tokens')
    profile = new_request(protocol=protocol, models=[model]).model_dump(exclude={'api_key'}) | {'id': 'api-qa'}
    observed = []
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}
    def respond(url, **kwargs):
        observed.append(kwargs['body'])
        if protocol == 'openai_responses':
            return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '{"text":"ok"}'}]}]}
        return {'choices': [{'message': {'content': '{"text":"ok"}'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr(wire, '_http_json', respond)
    result = wire.AiApiClient(profile, '', scope='qa', local_only=True).complete('source', 'system', 'qa', schema=schema, max_tokens=128)
    assert json.loads(result)['text'] == 'ok'
    payload = observed[0]
    if protocol == 'openai_chat':
        assert payload['max_completion_tokens'] == 128 and 'max_tokens' not in payload
        assert payload['response_format']['json_schema']['schema'] == schema
    else:
        assert payload['max_output_tokens'] == 128
        assert payload['text']['format']['schema'] == schema


def test_writing_translation_and_sound_prompt_use_assigned_connections(settings, monkeypatch):
    store = AiApiProfilesStore(settings)
    assignments = {}
    for task, protocol in [('writing', 'openai_chat'), ('translation', 'anthropic_messages'), ('sound_prompt', 'openai_responses')]:
        profile = store.save(new_request(name=task, protocol=protocol, models=[{'id': task + '-model'}]))
        assignments[task] = {'provider_id': profile['id'], 'model_id': task + '-model'}
    store.save_routing(RoutingInput(expected_revision=store.get()['revision'], **assignments))
    store.legacy.update({'translation_mode': 'selected'})
    calls = []
    def respond(url, **kwargs):
        payload = kwargs['body']; calls.append((url, payload['model']))
        if url.endswith('/messages'):
            text = json.dumps({'en': 'Translated script.'})
            return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}
        if url.endswith('/responses'):
            text = json.dumps({'generation_prompt': 'A soft button click, clean studio recording.', 'duration_seconds': 2})
            return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]}
        return {'choices': [{'message': {'content': 'Revised script.'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr(wire, '_http_json', respond)
    assert AiTextProviderService(settings).complete('Draft', system_prompt='Revise').content == 'Revised script.'
    translation = OpenAICompatibleTranslator(settings).translate('안내 대본입니다.', ['en'])
    assert translation.provider == assignments['translation']['provider_id']
    assert translation.translations['en'] == 'Translated script.'
    prompt, duration, provider, model = request_sound_effect_plan('버튼 효과음', settings)
    assert 'button click' in prompt and duration == 2
    assert provider == assignments['sound_prompt']['provider_id'] and model == 'sound_prompt-model'
    assert calls == [
        ('http://127.0.0.1:19001/v1/chat/completions', 'writing-model'),
        ('http://127.0.0.1:19001/v1/messages', 'translation-model'),
        ('http://127.0.0.1:19001/v1/responses', 'sound_prompt-model'),
    ]
