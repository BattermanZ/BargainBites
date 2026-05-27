import pytest

@pytest.mark.parametrize("settings,expected", [
    ({"sold_out": 0, "new_stock": 0, "stock_reduced": 0, "stock_increased": 0}, False),
    ({"sold_out": 0, "new_stock": 1, "stock_reduced": 0, "stock_increased": 0}, True),
    ({}, False),
])
def test_user_needs_notifications(settings, expected):
    import TooGoodToGo
    assert TooGoodToGo.TooGoodToGo._user_needs_notifications(settings) is expected


def test_import_toogoodtogo_module():
    import TooGoodToGo
    assert hasattr(TooGoodToGo, "TooGoodToGo")


def test_credentials_from_client_reads_token_fields():
    import TooGoodToGo

    class FakeClient:
        access_token = "AT"
        refresh_token = "RT"
        cookie = "datadome=abc"

    creds = TooGoodToGo.TooGoodToGo._credentials_from_client(FakeClient())
    assert creds == {"access_token": "AT", "refresh_token": "RT", "cookie": "datadome=abc"}


def test_format_message_handles_missing_optional_fields():
    import TooGoodToGo
    item = {
        "items_available": 3,
        "item": {"item_id": "i1", "price_including_taxes": {"minor_units": 499}},
        "store": {"store_id": "s1", "store_name": "Bakery",
                  "store_location": {"address": {"address_line": "1 Main St"}}},
        # no pickup_interval
    }
    message, item_id, store_id, store_name = TooGoodToGo.TooGoodToGo.format_message(item, "new_stock")
    assert item_id == "i1" and store_id == "s1" and store_name == "Bakery"
    assert "€4.99" in message and "3 bags available" in message
    assert message.startswith("*NEW BAGS AVAILABLE*")


def test_prune_seen_items_keeps_only_active():
    import TooGoodToGo
    seen = {"a": {"items_available": 1}, "b": {"items_available": 0}, "c": {"items_available": 2}}
    pruned = TooGoodToGo.TooGoodToGo._prune_seen_items(seen, active_ids={"a", "c"})
    assert set(pruned.keys()) == {"a", "c"}


import asyncio
import logging
from queue import Queue
from threading import Event, Lock


def _bare_instance():
    """Build a TooGoodToGo without running __init__ (which starts threads/loops)."""
    import TooGoodToGo
    inst = TooGoodToGo.TooGoodToGo.__new__(TooGoodToGo.TooGoodToGo)
    inst.logger = logging.getLogger("test")
    inst.message_queue = Queue()
    inst.connected_clients = {}
    inst._client_lock = Lock()
    return inst


def test_process_message_queue_dispatches_by_tuple_length():
    inst = _bare_instance()
    inst.shutdown_flag = Event()
    calls = {"text": [], "link": []}

    async def fake_send(key, message):
        calls["text"].append((key, message))

    async def fake_send_link(key, message, item_id, store_id, store_name):
        calls["link"].append((key, message, item_id, store_id, store_name))

    inst.send_message = fake_send
    inst.send_message_with_link = fake_send_link
    inst.message_queue.put(("u1", "hello"))
    inst.message_queue.put(("u2", "deal", "i1", "s1", "Bakery"))

    async def run():
        task = asyncio.create_task(inst.process_message_queue())
        while len(calls["text"]) + len(calls["link"]) < 2:
            await asyncio.sleep(0.02)
        inst.shutdown_flag.set()
        await task

    asyncio.run(run())
    assert calls["text"] == [("u1", "hello")]
    assert calls["link"] == [("u2", "deal", "i1", "s1", "Bakery")]


def test_complete_login_with_pin_no_pending_login():
    inst = _bare_instance()
    inst.pending_logins = {}
    inst.complete_login_with_pin("u1", "12345")
    payload = inst.message_queue.get_nowait()
    assert payload[0] == "u1"
    assert "No pending login" in payload[1]
    assert "u1" not in inst.pending_logins


def test_complete_login_with_pin_preserves_pending_on_bad_pin():
    from tgtg.exceptions import TgtgLoginError
    inst = _bare_instance()

    class FailingClient:
        access_token = refresh_token = cookie = None

        def _auth_by_pin(self, polling_id, pin):
            raise TgtgLoginError(400, b"bad pin")

    pending = {"client": FailingClient(), "polling_id": "pid", "email": "x@y.z"}
    inst.pending_logins = {"u1": pending}
    inst.complete_login_with_pin("u1", "99999")
    assert inst.pending_logins.get("u1") is pending  # restored so the user can retry
    payload = inst.message_queue.get_nowait()
    assert "Invalid or expired PIN" in payload[1]


def test_complete_login_with_pin_success_saves_credentials():
    inst = _bare_instance()
    inst.users_login_data = {}
    inst.users_settings_data = {}

    class FakeDB:
        def save_users_login_data(self, data):
            pass

        def save_users_settings_data(self, data):
            pass

    inst.db = FakeDB()

    class OkClient:
        access_token = "AT"
        refresh_token = "RT"
        cookie = "ck"

        def _auth_by_pin(self, polling_id, pin):
            pass

    client = OkClient()
    inst.pending_logins = {"u1": {"client": client, "polling_id": "pid", "email": "x@y.z"}}
    inst.complete_login_with_pin("u1", "11111")
    assert inst.users_login_data["u1"] == {"access_token": "AT", "refresh_token": "RT", "cookie": "ck"}
    assert "u1" not in inst.pending_logins
    assert inst.connected_clients["u1"] is client  # reused for a fast first /info
    payload = inst.message_queue.get_nowait()
    assert "logged in" in payload[1].lower()
