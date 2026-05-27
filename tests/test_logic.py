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
