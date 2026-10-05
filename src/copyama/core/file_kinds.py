"""文件类型识别：把剪贴到的文件按扩展名归类。

用于：列表图标、分组筛选、批量导出命名、标题栏统计（如「3 张图片、1 个压缩包」）。
纯逻辑，无平台依赖，可跨平台单测。
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from pathlib import Path


class FileKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    PDF = "pdf"
    CODE = "code"
    FONT = "font"
    EXECUTABLE = "executable"
    OTHER = "other"


# 展示用中文名（UI 与文案统一从这里取）
KIND_LABELS: dict[FileKind, str] = {
    FileKind.IMAGE: "图片",
    FileKind.VIDEO: "视频",
    FileKind.AUDIO: "音频",
    FileKind.ARCHIVE: "压缩包",
    FileKind.DOCUMENT: "文档",
    FileKind.SPREADSHEET: "表格",
    FileKind.PRESENTATION: "演示文稿",
    FileKind.PDF: "PDF",
    FileKind.CODE: "代码",
    FileKind.FONT: "字体",
    FileKind.EXECUTABLE: "可执行文件",
    FileKind.OTHER: "其它",
}

# 归入「文档大类」的种类，用于 UI 上的粗分组
DOCUMENT_LIKE = frozenset(
    {FileKind.DOCUMENT, FileKind.SPREADSHEET, FileKind.PRESENTATION, FileKind.PDF}
)

_GROUPS: dict[FileKind, tuple[str, ...]] = {
    FileKind.IMAGE: (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff",
        ".svg", ".ico", ".heic", ".avif", ".raw",
    ),
    FileKind.VIDEO: (
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
        ".mpg", ".mpeg", ".ts", ".rmvb", ".3gp",
    ),
    FileKind.AUDIO: (
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".ape", ".opus",
    ),
    FileKind.ARCHIVE: (
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso", ".cab",
    ),
    FileKind.DOCUMENT: (".doc", ".docx", ".rtf", ".odt", ".txt", ".md", ".wps"),
    FileKind.SPREADSHEET: (".xls", ".xlsx", ".csv", ".ods", ".et"),
    FileKind.PRESENTATION: (".ppt", ".pptx", ".odp", ".dps"),
    FileKind.PDF: (".pdf",),
    FileKind.CODE: (
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go",
        ".rs", ".rb", ".php", ".html", ".css", ".scss", ".json", ".xml", ".yaml",
        ".yml", ".toml", ".ini", ".sql", ".sh", ".ps1", ".kt", ".swift", ".vue",
        ".jsx", ".tsx", ".ipynb",
    ),
    FileKind.FONT: (".ttf", ".otf", ".woff", ".woff2"),
    FileKind.EXECUTABLE: (".exe", ".msi", ".dll", ".bat", ".cmd", ".apk", ".app"),
}

EXT_KIND: dict[str, FileKind] = {
    ext: kind for kind, exts in _GROUPS.items() for ext in exts
}


def classify_file(path: str | Path) -> FileKind:
    """按扩展名判断单个文件的类型；未知后缀归入 OTHER。"""
    ext = Path(str(path)).suffix.casefold()
    return EXT_KIND.get(ext, FileKind.OTHER)


def classify_paths(paths: list[str]) -> dict[FileKind, list[str]]:
    """把一组路径按类型分组，保持组内原始顺序。"""
    grouped: dict[FileKind, list[str]] = {}
    for p in paths:
        grouped.setdefault(classify_file(p), []).append(p)
    return grouped


def summarize(paths: list[str]) -> str:
    """生成人类可读的统计文案，如「图片 3、压缩包 1」。"""
    if not paths:
        return "空"
    counter: Counter[FileKind] = Counter(classify_file(p) for p in paths)
    parts = [f"{KIND_LABELS[k]} {n}" for k, n in counter.most_common()]
    return "、".join(parts)
