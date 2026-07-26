import pytest

from diskvis.formatter import format_size, parse_size


def test_format_size() -> None:
    assert format_size(1024) == "1.00 KB"
    assert format_size(1048576) == "1.00 MB"
    assert format_size(1073741824) == "1.00 GB"
    assert format_size(0) == "0 B"


def test_parse_size() -> None:
    assert parse_size("100MB") == 104857600
    assert parse_size("1GB") == 1073741824
    assert parse_size("500KB") == 512000
    assert parse_size("42") == 42


def test_parse_size_invalid_input() -> None:
    with pytest.raises(ValueError):
        parse_size("")
    with pytest.raises(ValueError):
        parse_size("abc")
    with pytest.raises(ValueError):
        parse_size("10XB")


def test_format_size_invalid_input() -> None:
    with pytest.raises(ValueError):
        format_size(-1)
