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
