from diskvis import __version__


def test_single_runtime_version_source() -> None:
    assert __version__ == "0.9.0"
