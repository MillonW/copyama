"""剪贴内容的数据模型。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ClipType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


@dataclass
class Clip:
    """一条剪贴历史。

    content 的语义随 type 变化：
    - text : 纯文本正文
    - image: 空，实际资源由 blob_hash 指向 blobs/<hash>
    - file : 文件绝对路径列表的 JSON 字符串
    """

    type: ClipType
    content: str = ""
    id: int | None = None
    kind: str | None = None      # FileKind 值，type=file 时按首个文件推断，供筛选/图标用
    blob_hash: str | None = None
    preview: str | None = None
    content_hash: str = ""
    size_bytes: int = 0
    source_app: str | None = None
    source_title: str | None = None
    created_at: int = 0
    pinned: bool = False
    deleted: bool = False

    # —— 便捷属性 ——
    @property
    def file_paths(self) -> list[str]:
        """type=file 时返回路径列表，否则空列表。"""
        if self.type is not ClipType.FILE or not self.content:
            return []
        try:
            data = json.loads(self.content)
        except json.JSONDecodeError:
            return []
        return [str(p) for p in data] if isinstance(data, list) else []

    @property
    def bubble_sources(self) -> str:
        """选词气泡的文本来源：文本条目取正文，文件条目取路径串。"""
        return self.content if self.type is ClipType.TEXT else "\n".join(self.file_paths)

    def to_row(self) -> dict[str, Any]:
        """转为可直接写入 SQLite 的 dict。"""
        return {
            "id": self.id,
            "type": self.type.value,
            "kind": self.kind,
            "content": self.content,
            "blob_hash": self.blob_hash,
            "preview": self.preview,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "source_app": self.source_app,
            "source_title": self.source_title,
            "created_at": self.created_at,
            "pinned": int(self.pinned),
            "deleted": int(self.deleted),
        }

    @classmethod
    def from_row(cls, row: Any) -> "Clip":
        """由 SQLite Row 构造 Clip（兼容缺少 kind 列的旧库）。"""
        keys = set(row.keys())
        return cls(
            id=row["id"],
            type=ClipType(row["type"]),
            kind=row["kind"] if "kind" in keys else None,
            content=row["content"] or "",
            blob_hash=row["blob_hash"],
            preview=row["preview"],
            content_hash=row["content_hash"],
            size_bytes=row["size_bytes"],
            source_app=row["source_app"],
            source_title=row["source_title"],
            created_at=row["created_at"],
            pinned=bool(row["pinned"]),
            deleted=bool(row["deleted"]),
        )
