"""Constructing another service must not recover an attempt that is still live."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from src.session.events import EventBus
from src.session.models import Attempt, AttemptStatus, Message, Session
from src.session.service import SessionBusyError, SessionService
from src.session.store import SessionStore


@pytest.mark.parametrize('started', [False, True])
@pytest.mark.parametrize('other_process', [False, True])
def test_second_service_preserves_live_attempt(tmp_path, monkeypatch, started, other_process):
    async def scenario():
        monkeypatch.setattr('src.session.service.get_shared_index', lambda: SimpleNamespace(
            index_session=lambda *args: None, index_message=lambda *args: None,
        ))
        store = SessionStore(tmp_path / 'sessions')
        owner = SessionService(store, EventBus(), tmp_path / 'runs')
        session = owner.create_session('Live request')
        gate = asyncio.Event()

        async def run(*args, **kwargs):
            await gate.wait()
            return {'status': 'success', 'content': 'Completed normally'}

        monkeypatch.setattr(owner, '_run_with_agent', run)
        sent = await owner.send_message(session.session_id, 'Analyze FPT')
        task = owner._active_tasks[session.session_id]
        try:
            if started:
                await asyncio.sleep(0)
            expected = AttemptStatus.RUNNING if started else AttemptStatus.PENDING
            assert store.get_attempt(session.session_id, sent['attempt_id']).status == expected
            if other_process:
                script = (
                    'from pathlib import Path; from types import SimpleNamespace; import sys; '
                    'from src.session.events import EventBus; from src.session.store import SessionStore; '
                    'import src.session.service as module; '
                    'module.get_shared_index=lambda: SimpleNamespace(index_message=lambda *a:None); '
                    'module.SessionService(SessionStore(Path(sys.argv[1])),EventBus(),Path(sys.argv[2]))'
                )
                subprocess.run([sys.executable, '-c', script, str(store.base_dir), str(tmp_path / 'runs')],
                               cwd=Path(__file__).resolve().parents[1], check=True,
                               capture_output=True, text=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            else:
                observer = SessionService(SessionStore(store.base_dir), EventBus(), tmp_path / 'runs')
                with pytest.raises(SessionBusyError):
                    await observer.send_message(session.session_id, 'Do not duplicate this attempt')
            assert store.get_attempt(session.session_id, sent['attempt_id']).status == expected
            assert not [message for message in store.get_messages(session.session_id) if message.role == 'assistant']
        finally:
            gate.set()
            await task
        replies = [message for message in store.get_messages(session.session_id) if message.role == 'assistant']
        assert len(replies) == 1
        assert replies[0].content == 'Completed normally'

    asyncio.run(scenario())


def test_api_service_initialization_is_serialized(tmp_path, monkeypatch):
    from src.api import state

    host = SimpleNamespace(_session_service=None, SESSIONS_DIR=tmp_path / 'sessions', RUNS_DIR=tmp_path / 'runs')
    monkeypatch.setitem(sys.modules, 'api_server', host)
    monkeypatch.setattr(state, '_session_service', None)
    monkeypatch.setattr(state, 'get_env_config', lambda: SimpleNamespace(api=SimpleNamespace(enable_session_runtime=True)))
    monkeypatch.setattr(state, '_attach_delivery_listener', lambda bus: None)
    monkeypatch.setattr('src.session.store.SessionStore', lambda **kwargs: object())
    monkeypatch.setattr('src.session.events.EventBus', lambda: SimpleNamespace(set_loop=lambda loop: None))
    entered, second_entered, release = threading.Event(), threading.Event(), threading.Event()
    constructed = []

    def construct(**kwargs):
        instance = object()
        constructed.append(instance)
        (entered if len(constructed) == 1 else second_entered).set()
        assert release.wait(5)
        return instance

    monkeypatch.setattr('src.session.service.SessionService', construct)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(state._get_session_service)
        assert entered.wait(5)
        second = executor.submit(state._get_session_service)
        second_entered.wait(0.2)
        release.set()
        assert first.result(timeout=5) is second.result(timeout=5)
    assert len(constructed) == 1


@pytest.mark.parametrize('changed_paths', [False, True])
def test_cleared_host_slot_reuses_the_local_service_only_for_the_same_store(tmp_path, monkeypatch, changed_paths):
    from src.api import state

    existing = SimpleNamespace(store=SimpleNamespace(base_dir=tmp_path / 'sessions'), runs_dir=tmp_path / 'runs')
    requested = tmp_path / 'other' if changed_paths else tmp_path
    host = SimpleNamespace(_session_service=None, SESSIONS_DIR=requested / 'sessions', RUNS_DIR=requested / 'runs')
    monkeypatch.setitem(sys.modules, 'api_server', host)
    monkeypatch.setattr(state, '_session_service', existing)
    monkeypatch.setattr(state, 'get_env_config', lambda: SimpleNamespace(api=SimpleNamespace(enable_session_runtime=True)))
    monkeypatch.setattr(state, '_attach_delivery_listener', lambda bus: None)
    monkeypatch.setattr('src.session.store.SessionStore', lambda **kwargs: object())
    monkeypatch.setattr('src.session.events.EventBus', lambda: SimpleNamespace(set_loop=lambda loop: None))
    replacement = object()
    monkeypatch.setattr('src.session.service.SessionService', lambda **kwargs: replacement)

    result = state._get_session_service()

    assert result is (replacement if changed_paths else existing)
    assert host._session_service is result


def test_process_exit_releases_the_claim_for_real_restart_recovery(tmp_path, monkeypatch):
    script = '''
import asyncio, json, os, sys
from pathlib import Path
from types import SimpleNamespace
from src.session.events import EventBus
from src.session.store import SessionStore
import src.session.service as module
module.get_shared_index = lambda: SimpleNamespace(index_session=lambda *a:None, index_message=lambda *a:None)
async def main():
    base = Path(sys.argv[1])
    service = module.SessionService(SessionStore(base / 'sessions'), EventBus(), base / 'runs')
    session = service.create_session('Process exits')
    async def wait(*args, **kwargs):
        await asyncio.Event().wait()
    service._run_with_agent = wait
    sent = await service.send_message(session.session_id, 'Persist before process exit')
    await asyncio.sleep(0)
    print(json.dumps(dict(session_id=session.session_id, **sent)), flush=True)
    os._exit(0)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], check=True,
                            capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    ids = json.loads(result.stdout)
    monkeypatch.setattr('src.session.service.get_shared_index', lambda: SimpleNamespace(index_message=lambda *a: None))
    store = SessionStore(tmp_path / 'sessions')
    assert store.get_attempt(ids['session_id'], ids['attempt_id']).status == AttemptStatus.RUNNING

    SessionService(store, EventBus(), tmp_path / 'runs')

    assert store.get_attempt(ids['session_id'], ids['attempt_id']).status == AttemptStatus.INTERRUPTED
    assert len(store.get_messages(ids['session_id'])) == 2


def test_recovery_reloads_the_attempt_after_acquiring_its_claim(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / 'sessions')
    session = Session(title='Completion races with startup scan')
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt='Analyze')
    attempt.mark_running()
    store.create_attempt(attempt)
    list_attempts = store.list_attempts

    def scan_then_complete():
        stale_snapshot = list_attempts()
        attempt.mark_completed('Final response')
        attempt.run_dir = str(tmp_path / 'runs' / 'completed-run')
        attempt.metrics = {'completed_steps': 3}
        store.append_message(Message(session_id=session.session_id, role='assistant',
                                     content='Final response', linked_attempt_id=attempt.attempt_id,
                                     metadata={'status': 'completed'}))
        store.update_attempt(attempt)
        return stale_snapshot

    monkeypatch.setattr(store, 'list_attempts', scan_then_complete)
    monkeypatch.setattr('src.session.service.get_shared_index', lambda: SimpleNamespace(index_message=lambda *a: None))

    SessionService(store, EventBus(), tmp_path / 'runs')

    saved = store.get_attempt(session.session_id, attempt.attempt_id)
    assert saved.status == AttemptStatus.COMPLETED
    assert saved.run_dir == attempt.run_dir
    assert saved.metrics == {'completed_steps': 3}
    assert len(store.get_messages(session.session_id)) == 1
