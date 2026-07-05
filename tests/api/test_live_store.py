"""LiveStore: in-memory state + SSE pub/sub. A fresh LiveStore() per test
(not the process-wide get_store() singleton) so tests can't interfere with
each other."""

from __future__ import annotations

import asyncio

from backend.api.live_store import LiveStore


def test_update_returns_true_on_first_write():
    store = LiveStore()
    changed = store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [])
    assert changed is True
    assert store.get_state(1)["last_pitch_ts"] == "t1"


def test_update_returns_false_when_last_pitch_ts_unchanged():
    store = LiveStore()
    store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [])
    changed = store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [])
    assert changed is False


def test_update_returns_true_when_last_pitch_ts_advances():
    store = LiveStore()
    store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [])
    changed = store.update(1, {"game_pk": 1, "last_pitch_ts": "t2"}, [])
    assert changed is True


def test_pa_pitches_preserved_when_not_passed_again():
    store = LiveStore()
    store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [{"pitch_number": 1}])
    store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, None)
    assert store.get_pa_pitches(1) == [{"pitch_number": 1}]


def test_all_states_and_has_data():
    store = LiveStore()
    assert store.has_data() is False
    store.update(1, {"game_pk": 1, "last_pitch_ts": "t1"}, [])
    store.update(2, {"game_pk": 2, "last_pitch_ts": "t1"}, [])
    assert store.has_data() is True
    assert {s["game_pk"] for s in store.all_states()} == {1, 2}


def test_subscribe_publish_unsubscribe():
    store = LiveStore()
    q = store.subscribe()
    store.publish(42)
    assert q.get_nowait() == 42
    store.unsubscribe(q)
    store.publish(42)  # no subscribers left; must not raise
    assert q.empty()


def test_publish_drops_signal_for_saturated_subscriber_without_raising():
    store = LiveStore()
    q = store.subscribe()
    for i in range(256):  # fill the bounded queue (maxsize=256)
        q.put_nowait(i)
    store.publish(999)  # queue is full; publish() must swallow QueueFull
    assert q.qsize() == 256
    drained = [q.get_nowait() for _ in range(256)]
    assert 999 not in drained  # the 999th signal was dropped, not queued


def test_publish_does_not_block_event_loop():
    async def _run():
        store = LiveStore()
        store.subscribe()
        store.publish(1)  # sync method; must complete without awaiting
        return True

    assert asyncio.run(_run()) is True
