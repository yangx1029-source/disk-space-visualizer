from pathlib import PurePosixPath, PureWindowsPath

from diskvis.gui import default_report_name


def test_default_report_name_for_folder() -> None:
    assert default_report_name(PurePosixPath("/home/demo")) == "demo-report.html"


def test_default_report_name_for_windows_drive_root() -> None:
    assert default_report_name(PureWindowsPath("E:/")) == "E-report.html"


def test_default_report_name_for_filesystem_root() -> None:
    assert default_report_name(PurePosixPath("/")) == "root-report.html"
