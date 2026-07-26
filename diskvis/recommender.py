"""Cleanup recommendation rules."""

from __future__ import annotations

from .duplicates import potential_saved_size
from .formatter import format_size
from .models import DuplicateGroup, FileInfo, FolderStat, ScanSummary, TypeStat

ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv"}
REGENERABLE_NAMES = {"node_modules", ".venv", "dist", "build"}


def generate_recommendations(
    summary: ScanSummary,
    largest_files: list[FileInfo],
    type_stats: list[TypeStat],
    folder_stats: list[FolderStat],
    duplicates: list[DuplicateGroup],
) -> list[str]:
    recommendations: list[str] = []

    duplicate_savings = potential_saved_size(duplicates)
    if duplicate_savings >= 100 * 1024**2:
        recommendations.append(
            f"检测到重复文件理论可节省 {format_size(duplicate_savings)}，建议人工确认后再处理。"
        )

    if any(file.size >= 1024**3 for file in largest_files):
        recommendations.append("存在超过 1GB 的大文件，建议检查是否为过期安装包、导出文件或临时文件。")

    archive_size = sum(stat.total_size for stat in type_stats if stat.suffix in ARCHIVE_SUFFIXES)
    if archive_size >= 500 * 1024**2:
        recommendations.append(f"压缩包占用 {format_size(archive_size)}，建议清理重复下载或旧备份。")

    for folder in folder_stats:
        if folder.path.name in REGENERABLE_NAMES and folder.total_size >= 200 * 1024**2:
            recommendations.append(
                f"{folder.path.name} 占用 {format_size(folder.total_size)}，如果可重新生成，可考虑清理。"
            )

    video_size = sum(stat.total_size for stat in type_stats if stat.suffix in VIDEO_SUFFIXES)
    if summary.total_size > 0 and video_size / summary.total_size >= 0.35:
        recommendations.append(f"视频文件占比较高，当前占用 {format_size(video_size)}，建议归档或迁移。")

    if not recommendations:
        recommendations.append("未发现明显的高风险占用项。建议先从最大文件和占用最高的文件夹开始人工检查。")

    return recommendations
