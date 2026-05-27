def test_import_toogoodtogo_module():
    import TooGoodToGo
    assert hasattr(TooGoodToGo, "TooGoodToGo")
