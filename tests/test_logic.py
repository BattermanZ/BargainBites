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
