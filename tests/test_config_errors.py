import pytest

from ne_kosis_mcp import config, errors


def test_resolve_api_key():
    assert config.resolve_api_key({"KOSIS_API_KEY": " abc "}) == "abc"
    with pytest.raises(config.CredentialsError):
        config.resolve_api_key({})
    with pytest.raises(config.CredentialsError):
        config.resolve_api_key({"KOSIS_API_KEY": "  "})


def test_dotenv_fills_only_missing(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# c\nKOSIS_API_KEY="fromfile"\nexport OTHER=x\n', encoding="utf-8")
    env = {"OTHER": "keep"}
    config.load_dotenv_if_present(f, env)
    assert env == {"OTHER": "keep", "KOSIS_API_KEY": "fromfile"}


def test_mask_key():
    masked = errors.mask_key("https://x?apiKey=SECRET&a=1")
    assert "SECRET" not in masked
    assert "apiKey=***" in masked


def test_kosis_error_detection():
    assert errors.kosis_error_code({"err": "30", "errMsg": "없음"}) == ("30", "없음")
    assert errors.kosis_error_code([{"a": 1}]) is None
    assert "40,000" in errors.format_kosis_error("u", "31", "")
