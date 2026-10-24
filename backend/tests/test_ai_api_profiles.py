from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.api.routes.ai_profiles import router
from app.services.ai_api_client import AiApiClient, ApiCallError, connection_slot, parse_text
from app.services.ai_api_credentials import ApiCredentialVault, CredentialError
from app.services.ai_api_profiles import AiApiProfilesStore, ModelProfile, ProfileConflict, ProfileInput, RoutingInput, profile_url, request_url
from app.services.ai_text_connections import AiTextConnectionsStore
from app.services.ai_text_provider_service import AiTextProviderService, AiTextSelection
from app.services.translation_service import OpenAICompatibleTranslator


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_dir=tmp_path, ai_text_settings_path=tmp_path / 'selection.json')


def profile_request(**changes):
    return ProfileInput(name='Local QA', base_url='http://127.0.0.1:19999/v1', auth_type='none', models=[ModelProfile(id='qa-model')], **changes)


def change_request(store, profile, **changes):
    fields = set(ProfileInput.model_fields) - {'api_key', 'clear_api_key', 'confirm_destination_change', 'expected_revision'}
    payload = {k: v for k, v in profile.items() if k in fields}
    if payload.get('credential_storage') == 'legacy':
        payload['credential_storage'] = 'keychain'
    payload.update(expected_revision=profile['revision'], **changes)
    return ProfileInput.model_validate(payload)


@pytest.fixture
def store(settings):
    return AiApiProfilesStore(settings)


@pytest.fixture
def client(settings):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize('url', [
    'http://external.test/v1', 'ftp://localhost/v1', 'https://a:b@host/v1',
    'https://host/v1?key=fake-secret', 'https://host/v1#fragment',
    'https://host/../v1', 'https://host/v 1', 'http://127.0.0.1.evil.test/v1',
    'https://host:bad/v1', 'https://host/\r\nheader',
])
def test_bad_urls_rejected(url):
    with pytest.raises(ValueError):
        profile_url(url)


@pytest.mark.parametrize('protocol,suffix', [('openai_chat', 'chat/completions'), ('anthropic_messages', 'messages'), ('openai_responses', 'responses')])
def test_endpoint_suffix_normalization(protocol, suffix):
    p = ProfileInput(name='test', base_url=f'https://host/v1/{suffix}/', protocol=protocol)
    assert p.base_url == 'https://host/v1'
    assert request_url(p.model_dump()) == f'https://host/v1/{suffix}'


def test_migration_preserves_legacy_key_and_selection(settings, store):
    legacy = AiTextConnectionsStore(settings)
    legacy.update({'provider_id': 'compatible', 'base_url': 'http://localhost:1234/v1', 'model_id': 'legacy-id', 'api_key': 'fake-legacy-key'})
    old_bytes = legacy.path.read_bytes()
    service = AiTextProviderService(settings)
    service.store.save(AiTextSelection('compatible', 'legacy-id'))
    public = store.public()
    p = next(p for p in public['profiles'] if p['id'] == 'api-legacy-compatible')
    assert p['has_api_key']
    assert 'fake-legacy-key' not in json.dumps(public)
    assert not store.path.exists()  # Reading settings never migrates/writes keys.
    assert store.key(store.find(p['id'])) == 'fake-legacy-key'
    store.save(profile_request())
    assert legacy.path.read_bytes() == old_bytes
    assert service.store.get().provider_id == 'compatible'


def test_profile_crud_revision_and_name_conflict(store):
    p = store.save(profile_request())
    assert p['revision'] == 1
    assert p['models'][0]['id'] == 'qa-model'
    with pytest.raises(ValueError):
        store.save(profile_request())
    updated = store.save(change_request(store, p, name='Renamed'), p['id'])
    assert updated['revision'] == 2
    with pytest.raises(ProfileConflict):
        store.save(change_request(store, p, name='Stale'), p['id'])
    with pytest.raises(ProfileConflict):
        store.delete(p['id'], 1)
    store.delete(p['id'], 2)
    with pytest.raises(KeyError):
        store.find(p['id'])


def test_private_key_not_in_metadata_and_rotated_deleted(settings, store):
    req = ProfileInput(name='keyed', base_url='http://localhost:1234/v1', credential_storage='private_file', api_key='fake-old-key', models=[ModelProfile(id='qa')])
    p = store.save(req)
    raw = store.find(p['id'])
    old_ref = raw['credential_ref']
    assert store.key(raw) == 'fake-old-key'
    assert 'fake-old-key' not in store.path.read_text()
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.vault._file(old_ref).stat().st_mode & 0o777 == 0o600
    assert 'credential_ref' not in p
    p = store.save(change_request(store, p, name='renamed'), p['id'])
    assert store.key(store.find(p['id'])) == 'fake-old-key'
    p = store.save(change_request(store, p, api_key='fake-new-key'), p['id'])
    assert not store.vault._file(old_ref).exists()
    new_ref = store.find(p['id'])['credential_ref']
    assert store.key(store.find(p['id'])) == 'fake-new-key'
    p = store.save(change_request(store, p, clear_api_key=True), p['id'])
    assert not p['has_api_key']
    assert not store.vault._file(new_ref).exists()


def test_keychain_failure_never_falls_back(store, monkeypatch):
    def deny(*a, **kw):
        raise CredentialError('Keychain unavailable')
    monkeypatch.setattr(store.vault, '_keychain', deny)
    with pytest.raises(CredentialError):
        store.save(ProfileInput(name='keychain', base_url='https://example.test/v1', api_key='fake-key'))
    assert not store.path.exists()
    assert not store.vault.directory.exists()


def test_save_failure_rolls_back_new_secret(store, monkeypatch):
    monkeypatch.setattr(store, '_write', lambda data: (_ for _ in ()).throw(RuntimeError('save failed')))
    with pytest.raises(RuntimeError):
        store.save(ProfileInput(name='keyed', base_url='https://example.test/v1', api_key='fake-key', credential_storage='private_file'))
    assert list(store.vault.directory.iterdir()) == []


def test_destination_changes_require_confirmation_and_new_key(store):
    p = store.save(ProfileInput(name='test', base_url='https://one.test/v1', api_key='fake-key', credential_storage='private_file'))
    with pytest.raises(ValueError, match='변경'):
        store.save(change_request(store, p, base_url='https://two.test/v1'), p['id'])
    with pytest.raises(ValueError, match='키'):
        store.save(change_request(store, p, base_url='https://two.test/v1', confirm_destination_change=True), p['id'])
    p = store.save(change_request(store, p, base_url='https://two.test/v1', confirm_destination_change=True, clear_api_key=True), p['id'])
    assert p['base_url'] == 'https://two.test/v1'
    assert not p['has_api_key']


@pytest.mark.parametrize('changes', [
    {'extra_headers': {'Authorization': 'fake-key'}}, {'extra_headers': {'Host': 'evil.test'}},
    {'extra_headers': {'X-Title': 'hello\r\nsecret'}}, {'api_key': 'fake\nkey'},
    {'models': [{'id': 'x'}, {'id': 'x'}]}, {'models': [{'id': 'x'}], 'default_model_id': 'y'},
    {'protocol': 'anthropic_messages', 'models': [{'id': 'x', 'structured_output': 'json_schema'}]},
    {'local_engine': 'ollama', 'base_url': 'https://remote.test/v1'}, {'max_concurrency': 99},
])
def test_bad_profile_data(changes):
    payload = {'name': 'valid', 'base_url': 'http://localhost:1234/v1', **changes}
    with pytest.raises(ValidationError):
        ProfileInput.model_validate(payload)


def test_invalid_requests_do_not_echo_secrets(client):
    payload = {'name': 'invalid', 'base_url': 'https://user:fake-secret@evil.test/v1', 'api_key': 'another-fake-secret', 'models': [{'id': ''}]}
    response = client.post('/api/ai/connections', json=payload)
    assert response.status_code == 422
    assert 'fake-secret' not in response.text
    assert 'evil.test' not in response.text
    assert client.post('/api/ai/connections', json={'api_key': 'fake-secret'}, headers={'Origin': 'https://evil.test'}).status_code == 403


def test_active_selection_and_routing_protect_delete(settings, store):
    p = store.save(profile_request())
    service = AiTextProviderService(settings)
    service.save_selection(p['id'], 'qa-model')
    with pytest.raises(ProfileConflict):
        store.delete(p['id'], p['revision'])
    with pytest.raises(ProfileConflict):
        store.save(change_request(store, p, models=[], default_model_id=''), p['id'])
    service.store.save(AiTextSelection('apple', 'apple-on-device'))
    store.save_routing(RoutingInput(expected_revision=store.get()['revision'], translation={'provider_id': p['id'], 'model_id': 'qa-model'}))
    with pytest.raises(ProfileConflict):
        store.delete(p['id'], p['revision'])
    with pytest.raises(ProfileConflict):
        store.save_routing(RoutingInput(expected_revision=0))


def test_local_policy_blocks_before_reading_key_or_http(settings, store, monkeypatch):
    p = store.save(ProfileInput(name='external', base_url='https://example.test/v1', auth_type='none', models=[ModelProfile(id='qa')]))
    service = AiTextProviderService(settings)
    monkeypatch.setattr(service.api_profiles, 'key', lambda _: pytest.fail('key should not be read'))
    with pytest.raises(ApiCallError, match='로컬 전용'):
        service.complete('test', system_prompt='test', provider_id=p['id'], model_id='qa')
    with pytest.raises(ApiCallError):
        service.save_selection(p['id'], 'qa')
    assert store.legacy.get()['local_only'] is True


@pytest.fixture
def upstream():
    observed = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send_json(self, payload, status=200):
            data = json.dumps(payload).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            observed.append((self.path, dict(self.headers), None))
            self.send_json({'data': [{'id': 'qa-model', 'display_name': 'QA model'}]})
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
            observed.append((self.path, dict(self.headers), data))
            if self.path.startswith('/redirect'):
                self.send_response(307); self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/leak'); self.send_header('Content-Length', '0'); self.end_headers(); return
            if self.path.startswith('/denied'):
                self.send_json({'error': 'fake-api-key and private prompt must not leak'}, 401); return
            if self.path == '/api/show':
                self.send_json({'remote_model': 'cloud'}); return
            text = 'OK'
            if self.path.endswith('/messages'):
                self.send_json({'content': [{'type': 'thinking', 'thinking': 'not output'}, {'type': 'text', 'text': text}], 'stop_reason': 'end_turn'})
            elif self.path.endswith('/responses'):
                self.send_json({'status': 'completed', 'output': [{'type': 'reasoning'}, {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]})
            else:
                self.send_json({'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', observed
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.mark.parametrize('protocol,auth,path', [('openai_chat', 'bearer', '/v1/chat/completions'), ('anthropic_messages', 'x-api-key', '/v1/messages'), ('openai_responses', 'bearer', '/v1/responses')])
def test_real_loopback_http_protocol_frames(upstream, settings, store, protocol, auth, path):
    base, observed = upstream
    p = store.save(ProfileInput(name='loopback', base_url=base+'/v1', protocol=protocol, auth_type=auth, api_key='fake-api-key', credential_storage='private_file', models=[ModelProfile(id='qa-model', max_output_tokens=256)]))
    service = AiTextProviderService(settings)
    response = service.complete('hello', system_prompt='system', provider_id=p['id'], model_id='qa-model', max_tokens=1000)
    assert response.content == 'OK'
    endpoint, headers, request = observed[-1]
    assert endpoint == path
    assert ('temperature' not in request) and request['model'] == 'qa-model'
    if protocol == 'openai_chat':
        assert headers['Authorization'] == 'Bearer fake-api-key'
        assert request['messages'][0]['role'] == 'system' and request['max_tokens'] == 256
    elif protocol == 'anthropic_messages':
        assert headers.get('X-Api-Key') == 'fake-api-key' or headers.get('X-api-key') == 'fake-api-key'
        assert request['system'] == 'system' and request['max_tokens'] == 256
        assert any(k.lower() == 'anthropic-version' for k in headers)
    else:
        assert request['instructions'] == 'system' and request['input'] == 'hello'
        assert request['max_output_tokens'] == 256 and request['store'] is False
    client = AiApiClient(store.find(p['id']), 'fake-api-key', scope='test', local_only=True)
    assert client.models()['models'][0]['id'] == 'qa-model'
    assert observed[-1][0] == '/v1/models'


def test_redirect_and_error_bodies_cannot_leak(upstream, store):
    base, observed = upstream
    for route in ('redirect', 'denied'):
        p = store.save(ProfileInput(name=route, base_url=base+'/'+route, api_key='fake-api-key', credential_storage='private_file', models=[ModelProfile(id='qa-model')]))
        client = AiApiClient(store.find(p['id']), 'fake-api-key', scope='test', local_only=True)
        with pytest.raises(ApiCallError) as error:
            client.complete('private prompt', 'system', 'qa-model')
        assert 'fake-api-key' not in str(error.value)
        assert 'private prompt' not in str(error.value)
        assert not any(path == '/leak' for path, _, _ in observed)


@pytest.mark.parametrize('protocol,payload', [
 ('openai_chat', {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]}),
 ('openai_chat', {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}),
 ('openai_chat', {'choices': [{'message': {'content': 'text', 'tool_calls': [{}]}, 'finish_reason': 'stop'}]}),
 ('anthropic_messages', {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': 'partial'}]}),
 ('anthropic_messages', {'stop_reason': 'tool_use', 'content': []}),
 ('anthropic_messages', {'stop_reason': 'pause_turn', 'content': []}),
 ('openai_responses', {'status': 'incomplete', 'output': []}),
 ('openai_responses', {'status': 'completed', 'output': [{'type': 'function_call'}]}),
 ('openai_responses', {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal'}]}]}),
 ('openai_chat', {'choices': []}), ('anthropic_messages', {'content': None}),
])
def test_incomplete_or_non_text_response_rejected(protocol, payload):
    with pytest.raises(ApiCallError):
        parse_text(payload, protocol)


def test_budget_refuses_without_sending(upstream, store):
    base, observed = upstream
    p = store.save(ProfileInput(name='budget', base_url=base+'/v1', auth_type='none', models=[ModelProfile(id='qa-model', max_input_chars=256)]))
    with pytest.raises(ApiCallError, match='문자 예산'):
        AiApiClient(store.find(p['id']), '', scope='test', local_only=True).complete('x'*256, 'system', 'qa-model')
    assert not observed


def test_ollama_cloud_is_blocked(upstream, store):
    base, observed = upstream
    p = store.save(ProfileInput(name='ollama', base_url=base+'/v1', auth_type='none', local_engine='ollama', models=[ModelProfile(id='qa-model')]))
    with pytest.raises(ApiCallError, match='클라우드'):
        AiApiClient(store.find(p['id']), '', scope='test', local_only=True).complete('hello', 'system', 'qa-model')
    assert [x[0] for x in observed] == ['/api/show']


def test_routes_and_translation_use_fixed_profile(settings, store, monkeypatch):
    p = store.save(profile_request())
    other = store.save(ProfileInput(name='other', base_url='http://127.0.0.1:18888/v1', auth_type='none', models=[ModelProfile(id='other-model')]))
    store.save_routing(RoutingInput(expected_revision=store.get()['revision'], translation={'provider_id': p['id'], 'model_id': 'qa-model'}, writing={'provider_id': other['id'], 'model_id': 'other-model'}, sound_prompt={'provider_id': p['id'], 'model_id': 'qa-model'}))
    service = AiTextProviderService(settings)
    assert service.task_selection('writing').model_id == 'other-model'
    assert service.task_selection('sound_prompt').model_id == 'qa-model'
    calls = []
    def respond(self, prompt, system, model_id, **kwargs):
        calls.append((self.profile['base_url'], model_id))
        if len(calls) == 1:
            current = store.find(p['id'])
            store.save(change_request(store, current, base_url='http://127.0.0.1:17777/v1', confirm_destination_change=True), p['id'])
        code = kwargs['schema']['required'][0]
        return json.dumps({code: 'translated'})
    monkeypatch.setattr(AiApiClient, 'complete', respond)
    result = OpenAICompatibleTranslator(settings).translate('Source text.', ['en', 'ja'])
    assert set(result.translations) == {'en', 'ja'}
    assert calls == [('http://127.0.0.1:19999/v1', 'qa-model')]*2
    assert service.translation_selection({'available': True}).provider_id == 'apple'


def test_profile_probe_api_and_stale_revision(client, store, upstream):
    base, _ = upstream
    r = client.post('/api/ai/connections', json={'name': 'probe', 'base_url': base+'/v1', 'auth_type': 'none', 'models': [{'id': 'qa-model'}]})
    assert r.status_code == 201
    p = r.json()['profile']
    probe = client.post(f"/api/ai/connections/{p['id']}/test", json={'expected_revision': 1})
    assert probe.status_code == 200
    assert probe.json()['instruction_followed']
    assert probe.json()['content'] == 'OK'
    assert client.post(f"/api/ai/connections/{p['id']}/models", json={'expected_revision': 99}).status_code == 409
    assert client.put('/api/ai/routing', json={'expected_revision': store.get()['revision'], 'writing': {'provider_id': p['id'], 'model_id': 'absent'}}).status_code == 422


def test_per_connection_concurrency_limit_and_cleanup():
    active = maximum = 0
    mutex = threading.Lock()
    def work():
        nonlocal active, maximum
        with connection_slot('qa-concurrency', 2, 3):
            with mutex:
                active += 1; maximum = max(active, maximum)
            time.sleep(.025)
            with mutex:
                active -= 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: work(), range(12)))
    assert maximum == 2 and active == 0
    with pytest.raises(RuntimeError):
        with connection_slot('qa-error-release', 1, 1):
            raise RuntimeError('intentional')
    with connection_slot('qa-error-release', 1, 1):
        pass
