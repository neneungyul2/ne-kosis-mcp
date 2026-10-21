import os

import pytest


def pytest_collection_modifyitems(config, items):
    """@pytest.mark.live 테스트는 KOSIS_LIVE_TEST=1 일 때만 실행한다."""
    if os.environ.get("KOSIS_LIVE_TEST") == "1":
        return
    skip = pytest.mark.skip(reason="KOSIS_LIVE_TEST=1 일 때만 실행 (실제 API 호출)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
