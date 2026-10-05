"""SQLite 存储层：建表、写入、查询、分页、清理、导出。

不含任何 GUI / Win32 依赖，可在非 Windows 平台开发与测试。

性能与空间策略（对应「别太臃肿、注意占用空间」）：
- WAL 模式，写不阻塞读；写操作共用一把可重入锁，跨线程安全；
- 列表**分页查询**，UI 不一次性把历史全渲染出来；
- 图片原图落 ``blobs/<hash>``，展示统一走 ``blobs/thumb/<hash>.webp`` 缩略图；
- 三道清理闸门：条数上限、保留天数、原图总配额，均只淘汰**未固定**记录；
- 软删进回收站 → 物理删除时才回收磁盘，并顺带清掉孤儿文件。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from copyama.config import default_data_dir
from copyama.data import thumbnails
from copyama.core.models import Clip, ClipType
from copyama.core.retention import CleanupPlan, RetentionPolicy, plan_cleanup
from copyama.utils.logger import get_logger

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL,
    kind         TEXT,
    content      TEXT,
    blob_hash    TEXT,
    preview      TEXT,
    content_hash TEXT    NOT NULL,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    source_app   TEXT,
    source_title TEXT,
    created_at   INTEGER NOT NULL,
    pinned       INTEGER NOT NULL DEFAULT 0,
    deleted      INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clips_hash ON clips(content_hash);
CREATE INDEX IF NOT EXISTS idx_clips_pinned_created
    ON clips(pinned DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_kind ON clips(kind);
CREATE INDEX IF NOT EXISTS idx_clips_active
    ON clips(deleted, pinned DESC, created_at DESC);
"""

_INSERT_COLUMNS = (
    "type", "kind", "content", "blob_hash", "preview", "content_hash",
    "size_bytes", "source_app", "source_title", "created_at", "pinned", "deleted",
)

DEFAULT_MAX_ITEMS = 200
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_BLOB_QUOTA_MB = 300


def content_hash(clip_type: ClipType, payload: str | bytes) -> str:
    """生成去重键：type + 内容 sha256。

    同一条内容反复 Ctrl+C 只会命中同一个 hash，因此存储层天然「重复只留一条」。
    """
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    digest = hashlib.sha256(raw).hexdigest()
    return f"{clip_type.value}:{digest}"


def now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


class Storage:
    """剪贴历史的持久化门面。"""

    def __init__(
        self,
        db_path: Path | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        *,
        thumb_max_px: int = thumbnails.THUMB_MAX_PX,
        thumb_format: str = thumbnails.THUMB_FORMAT,
        blob_quota_mb: int | None = DEFAULT_BLOB_QUOTA_MB,
    ) -> None:
        base = db_path or (default_data_dir() / "copyama.db")
        base.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = base
        self.max_items = max_items
        self.max_age_days = max_age_days
        self.thumb_max_px = thumb_max_px
        self.thumb_format = thumb_format
        self.blob_quota_mb = blob_quota_mb

        self.blob_dir = base.parent / "blobs"
        self.blob_dir.mkdir(exist_ok=True)
        thumbnails.thumb_dir(self.blob_dir)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(base), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # WAL 默认只复用不截断，常驻进程写久了 -wal 会一直占着历史峰值；
        # 限制日志体积，配合 vacuum/close 里的检查点把磁盘真正还回去。
        self._conn.execute("PRAGMA journal_size_limit=1048576")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # —— 策略 ——
    @property
    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(max_items=self.max_items, max_age_days=self.max_age_days)

    def set_policy(self, *, max_items: int | None = None, max_age_days: int | None = None) -> None:
        """更新保留策略（UI 改设置后调用）。"""
        if max_items is not None:
            self.max_items = max(0, int(max_items))
        if max_age_days is not None:
            self.max_age_days = max(0, int(max_age_days))

    # —— Blob 资源 ——
    def blob_path(self, blob_hash: str) -> Path:
        """原图路径。"""
        safe = blob_hash.replace(":", "_").replace("/", "_")
        return self.blob_dir / safe

    def thumb_path(self, blob_hash: str) -> Path:
        """缩略图路径。"""
        return thumbnails.thumb_path(self.blob_dir, blob_hash, self.thumb_format)

    def thumb_file(self, clip: Clip) -> Path | None:
        """取某条图片记录的缩略图文件；不存在返回 None（UI 显示占位）。"""
        if clip.type is not ClipType.IMAGE or not clip.blob_hash:
            return None
        if clip.preview:
            candidate = thumbnails.thumb_dir(self.blob_dir) / clip.preview
            if candidate.exists():
                return candidate
        fallback = self.thumb_path(clip.blob_hash)
        return fallback if fallback.exists() else None

    def blob_file(self, clip: Clip) -> Path | None:
        """取某条图片记录的原图文件；不存在返回 None。"""
        if clip.type is not ClipType.IMAGE or not clip.blob_hash:
            return None
        path = self.blob_path(clip.blob_hash)
        return path if path.exists() else None

    def image_bytes(self, clip: Clip) -> bytes | None:
        """读取原图字节（预览窗口按需加载，不进列表渲染路径）。"""
        if not clip.blob_hash:
            return None
        path = self.blob_path(clip.blob_hash)
        return path.read_bytes() if path.exists() else None

    def _store_blob(self, data: bytes, clip: Clip) -> None:
        """原图落盘 + 生成缩略图 + 回填 hash / 体积 / 缩略图名。"""
        digest = hashlib.sha256(data).hexdigest()[:32]
        clip.blob_hash = f"img_{digest}"
        clip.size_bytes = len(data)
        path = self.blob_path(clip.blob_hash)
        if not path.exists():
            path.write_bytes(data)
        thumb = thumbnails.ensure(
            self.blob_dir,
            clip.blob_hash,
            data,
            max_px=self.thumb_max_px,
            fmt=self.thumb_format,
        )
        clip.preview = thumb.path.name if thumb else None

    def _drop_blob(self, blob_hash: str | None) -> None:
        """删除原图与缩略图（物理删除记录时调用）。"""
        if not blob_hash:
            return
        for path in (self.blob_path(blob_hash), self.thumb_path(blob_hash)):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - 文件被占用等
                log.debug("删除 blob 失败 %s：%s", path, exc)

    # —— 写入 ——
    def add(self, clip: Clip, blob: bytes | None = None) -> Clip:
        """插入一条记录。

        - 内容重复（content_hash 相同）时只刷新时间并置顶，**不新增行**，
          对应需求「按了很多遍 Ctrl+C 重复内容只复制一次」；
        - ``blob`` 给定时按图片处理：原图落盘、生成缩略图。
        """
        with self._lock:
            if not clip.created_at:
                clip.created_at = now_ms()
            if clip.type is ClipType.IMAGE and blob is not None:
                self._store_blob(blob, clip)
            if not clip.content_hash and clip.type is ClipType.IMAGE and not (
                clip.blob_hash or clip.content
            ):
                # 平台层只提供图片元信息（体积/尺寸）时，用「体积 + 时间」构造回退键，
                # 避免不同图片因共享空载荷而被误判成同一条重复记录。
                clip.content_hash = content_hash(
                    ClipType.IMAGE, f"meta:{clip.size_bytes}:{clip.created_at}"
                )
            if not clip.content_hash:
                clip.content_hash = content_hash(clip.type, self._hash_payload(clip))

            existing = self._conn.execute(
                "SELECT id, created_at, pinned FROM clips WHERE content_hash = ?",
                (clip.content_hash,),
            ).fetchone()
            if existing is not None:
                # 重复复制：刷新时间置顶；若原本被软删则恢复
                self._conn.execute(
                    "UPDATE clips SET created_at = ?, deleted = 0 WHERE id = ?",
                    (clip.created_at, existing["id"]),
                )
                self._conn.commit()
                clip.id = int(existing["id"])
                clip.pinned = bool(existing["pinned"])
                return clip

            values = clip.to_row()
            sql = (
                f"INSERT INTO clips ({', '.join(_INSERT_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _INSERT_COLUMNS)})"
            )
            cur = self._conn.execute(sql, tuple(values[c] for c in _INSERT_COLUMNS))
            self._conn.commit()
            clip.id = int(cur.lastrowid or 0)
            # 入库路径只做轻量的条数淘汰；过期 / 原图配额 / 孤儿扫描交给启动维护
            # 与定时清理，避免「每复制一次就全量扫一遍 blob 目录」。
            if self.count() > self.max_items:
                self.enforce_limit()
            return clip

    def store_text(self, text: str, *, source_app: str | None = None,
                   source_title: str | None = None) -> Clip:
        """写入一条文本。"""
        return self.add(Clip(type=ClipType.TEXT, content=text,
                             source_app=source_app, source_title=source_title))

    def store_files(self, paths: Sequence[str], *, kind: str | None = None,
                    source_app: str | None = None, source_title: str | None = None) -> Clip:
        """写入一条文件记录（多个文件存进同一条）。"""
        body = json.dumps(list(paths), ensure_ascii=False)
        return self.add(Clip(type=ClipType.FILE, content=body, kind=kind,
                             source_app=source_app, source_title=source_title))

    def store_image(self, data: bytes, *, kind: str = "image",
                    source_app: str | None = None, source_title: str | None = None) -> Clip:
        """写入一张图片：原图存盘、缩略图供列表展示。"""
        return self.add(
            Clip(type=ClipType.IMAGE, kind=kind,
                 source_app=source_app, source_title=source_title),
            blob=data,
        )

    @staticmethod
    def _hash_payload(clip: Clip) -> str | bytes:
        """取用于去重的载荷；图片用 blob_hash，文件用路径串。"""
        if clip.type is ClipType.IMAGE:
            return clip.blob_hash or clip.content or ""
        return clip.content or ""

    # —— 查询 ——
    def get(self, clip_id: int) -> Clip | None:
        row = self._conn.execute(
            "SELECT * FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
        return Clip.from_row(row) if row else None

    def recent(self, limit: int = DEFAULT_MAX_ITEMS) -> list[Clip]:
        """返回最近记录（未删除，固定项优先）。"""
        sql = (
            "SELECT * FROM clips WHERE deleted = 0 "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?"
        )
        return [Clip.from_row(r) for r in self._conn.execute(sql, (limit,))]

    @staticmethod
    def _where(keyword: str = "", kinds: Sequence[str] | None = None,
               include_deleted: bool = False) -> tuple[str, list[object]]:
        clauses = ["1=1"] if include_deleted else ["deleted = 0"]
        params: list[object] = []
        if keyword:
            clauses.append("(content LIKE ? OR preview LIKE ? OR source_title LIKE ?)")
            like = f"%{keyword}%"
            params += [like, like, like]
        if kinds:
            clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params += list(kinds)
        return " AND ".join(clauses), params

    def page(
        self,
        offset: int = 0,
        limit: int = 60,
        keyword: str = "",
        kinds: Sequence[str] | None = None,
        *,
        include_deleted: bool = False,
    ) -> list[Clip]:
        """分页查询（滚动加载用，避免一次性拉全量）。"""
        where, params = self._where(keyword, kinds, include_deleted)
        sql = (
            f"SELECT * FROM clips WHERE {where} "
            "ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ? OFFSET ?"
        )
        params += [max(1, limit), max(0, offset)]
        return [Clip.from_row(r) for r in self._conn.execute(sql, tuple(params))]

    def page_after(
        self,
        before: tuple[int, int] | tuple[int, int, int] | None = None,
        limit: int = 60,
        keyword: str = "",
        kinds: Sequence[str] | None = None,
    ) -> list[Clip]:
        """键集分页：取「上一条之后」的记录，游标与排序键严格对应。

        排序键是 ``(pinned DESC, created_at DESC, id DESC)``，因此游标也必须是三元组
        ``(pinned, created_at, id)``：快速连续复制时多条记录会落在同一毫秒，
        只用 ``(pinned, created_at)`` 会把同毫秒里更旧的记录整批漏掉。
        仍兼容旧的二元组游标（退化为仅按 pinned + created_at 过滤）。
        """
        where, params = self._where(keyword, kinds)
        if before is not None:
            pinned, created = int(before[0]), int(before[1])
            if len(before) >= 3:
                where += (
                    " AND (pinned < ? OR (pinned = ? AND (created_at < ?"
                    " OR (created_at = ? AND id < ?))))"
                )
                params += [pinned, pinned, created, created, int(before[2])]
            else:
                where += " AND (pinned < ? OR (pinned = ? AND created_at < ?))"
                params += [pinned, pinned, created]
        sql = (
            f"SELECT * FROM clips WHERE {where} "
            "ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ?"
        )
        params.append(max(1, limit))
        return [Clip.from_row(r) for r in self._conn.execute(sql, tuple(params))]

    @staticmethod
    def cursor_of(clip: Clip) -> tuple[int, int, int]:
        """取键集游标三元组，供 page_after 继续翻页。"""
        return (int(clip.pinned), int(clip.created_at), int(clip.id or 0))

    def search(
        self, keyword: str = "", limit: int = DEFAULT_MAX_ITEMS,
        kinds: Sequence[str] | None = None,
    ) -> list[Clip]:
        """关键词模糊搜索 + 可选类型筛选；空关键词等价于 recent。"""
        where, params = self._where(keyword, kinds)
        sql = (
            f"SELECT * FROM clips WHERE {where} "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?"
        )
        params.append(limit)
        return [Clip.from_row(r) for r in self._conn.execute(sql, tuple(params))]

    def count_filtered(self, keyword: str = "", kinds: Sequence[str] | None = None) -> int:
        """符合条件的条数（供 UI 判断是否还有下一页）。"""
        where, params = self._where(keyword, kinds)
        return int(
            self._conn.execute(
                f"SELECT COUNT(*) FROM clips WHERE {where}", tuple(params)
            ).fetchone()[0]
        )

    def count(self, *, include_deleted: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM clips" + ("" if include_deleted else " WHERE deleted = 0")
        return int(self._conn.execute(sql).fetchone()[0])

    def active_clips(self, limit: int | None = None) -> list[Clip]:
        """全部未删记录（清理规划用）。"""
        sql = "SELECT * FROM clips WHERE deleted = 0 ORDER BY created_at DESC, id DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return [Clip.from_row(r) for r in self._conn.execute(sql, params)]

    def recycle_bin(self, limit: int = DEFAULT_MAX_ITEMS) -> list[Clip]:
        """回收站内容（软删记录）。"""
        sql = ("SELECT * FROM clips WHERE deleted = 1 "
               "ORDER BY created_at DESC LIMIT ?")
        return [Clip.from_row(r) for r in self._conn.execute(sql, (limit,))]

    # —— 管理 ——
    def set_pinned(self, clip_id: int, pinned: bool) -> None:
        """固定 / 取消固定。"""
        with self._lock:
            self._conn.execute(
                "UPDATE clips SET pinned = ? WHERE id = ?", (int(pinned), clip_id)
            )
            self._conn.commit()

    def delete(self, clip_ids: Sequence[int], hard: bool = False) -> int:
        """批量删除：默认软删除（可撤销到回收站），hard=True 时物理删除并回收磁盘。"""
        ids = [int(i) for i in clip_ids]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._lock:
            if hard:
                rows = self._conn.execute(
                    f"SELECT blob_hash FROM clips WHERE id IN ({placeholders})", tuple(ids)
                ).fetchall()
                for row in rows:
                    self._drop_blob(row["blob_hash"])
                cur = self._conn.execute(
                    f"DELETE FROM clips WHERE id IN ({placeholders})", tuple(ids)
                )
            else:
                cur = self._conn.execute(
                    f"UPDATE clips SET deleted = 1, pinned = 0 WHERE id IN ({placeholders})",
                    tuple(ids),
                )
            self._conn.commit()
            return cur.rowcount

    def purge(self, clip_ids: Sequence[int]) -> int:
        """物理删除（清理策略与「彻底删除」共用）。"""
        return self.delete(clip_ids, hard=True)

    def purge_deleted(self) -> int:
        """清空回收站（物理删除全部软删项）。"""
        with self._lock:
            rows = self._conn.execute("SELECT blob_hash FROM clips WHERE deleted = 1").fetchall()
            for row in rows:
                self._drop_blob(row["blob_hash"])
            cur = self._conn.execute("DELETE FROM clips WHERE deleted = 1")
            self._conn.commit()
            return cur.rowcount

    def restore(self, clip_ids: Sequence[int]) -> int:
        """从回收站还原。"""
        ids = [int(i) for i in clip_ids]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE clips SET deleted = 0 WHERE id IN ({placeholders})", tuple(ids)
            )
            self._conn.commit()
            return cur.rowcount

    # —— 清理（性能 / 空间）——
    def enforce_limit(self, max_items: int | None = None) -> int:
        """按条数上限淘汰最旧的未固定记录。"""
        policy = RetentionPolicy(
            max_items=max_items if max_items is not None else self.max_items,
            max_age_days=0,
        )
        plan = plan_cleanup(self.active_clips(), now_ms(), policy)
        return self.purge(plan.all_ids()) if plan.total else 0

    def purge_expired(self, max_age_days: int | None = None, *, now: int | None = None) -> int:
        """删除早于保留期的记录（默认 7 天）。"""
        policy = RetentionPolicy(
            max_items=0,
            max_age_days=max_age_days if max_age_days is not None else self.max_age_days,
        )
        plan = plan_cleanup(self.active_clips(), now or now_ms(), policy)
        return self.purge(plan.all_ids()) if plan.total else 0

    def run_cleanup(
        self, policy: RetentionPolicy | None = None, *, now: int | None = None
    ) -> dict[str, int]:
        """一次完整清理：过期 + 超限 + 原图配额 + 孤儿文件。

        返回各项清理数量，供 UI 展示与日志留痕。
        """
        with self._lock:
            current = policy or self.policy
            now_value = now or now_ms()
            plan = plan_cleanup(self.active_clips(), now_value, current)
            removed = self.purge(plan.all_ids()) if plan.total else 0
            quota_removed = self.enforce_blob_quota()
            orphans = self.sweep_orphans()
            if removed or quota_removed or orphans:
                log.debug(
                    "清理完成：超期/超限 %d 条，配额 %d 条，孤儿文件 %d 个",
                    removed, quota_removed, orphans,
                )
            return {
                "expired": len(plan.expired_ids),
                "overflow": len(plan.overflow_ids),
                "removed": removed,
                "quota_removed": quota_removed,
                "orphans": orphans,
                "kept": plan.keep_count,
            }

    def enforce_blob_quota(self, quota_mb: int | None = None) -> int:
        """原图总量超过配额时，从最旧的图片记录开始物理删除。返回删除条数。"""
        quota = self.blob_quota_mb if quota_mb is None else quota_mb
        if not quota or quota <= 0:
            return 0
        limit_bytes = quota * 1024 * 1024
        rows = self._conn.execute(
            "SELECT id, size_bytes, pinned FROM clips "
            "WHERE deleted = 0 AND type = ? ORDER BY created_at ASC, id ASC",
            (ClipType.IMAGE.value,),
        ).fetchall()
        total = sum(int(r["size_bytes"] or 0) for r in rows)
        if total <= limit_bytes:
            return 0
        doomed: list[int] = []
        for row in rows:
            if total <= limit_bytes:
                break
            if row["pinned"]:
                continue
            doomed.append(int(row["id"]))
            total -= int(row["size_bytes"] or 0)
        return self.purge(doomed) if doomed else 0

    def sweep_orphans(self) -> int:
        """删除没有任何记录引用的 blob / 缩略图文件（含软删记录仍引用的一律保留）。"""
        referenced = {
            r["blob_hash"]
            for r in self._conn.execute(
                "SELECT DISTINCT blob_hash FROM clips WHERE blob_hash IS NOT NULL"
            )
        }
        referenced |= {
            r["preview"].rsplit(".", 1)[0]
            for r in self._conn.execute(
                "SELECT DISTINCT preview FROM clips WHERE preview IS NOT NULL"
            )
        }
        removed = 0
        for folder in (self.blob_dir, thumbnails.thumb_dir(self.blob_dir)):
            for path in folder.glob("*"):
                if not path.is_file():
                    continue
                stem = path.stem
                if stem not in referenced and path.stem.replace("_", ":", 1) not in referenced:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:  # pragma: no cover
                        pass
        return removed

    # —— 统计 ——
    def disk_usage(self) -> dict[str, int]:
        """磁盘占用明细（字节），供设置界面展示「占用空间」。"""

        def total(folder: Path) -> int:
            return sum(f.stat().st_size for f in folder.glob("*") if f.is_file())

        db_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        wal = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        if wal.exists():
            db_bytes += wal.stat().st_size
        blob_bytes = total(self.blob_dir)
        thumb_bytes = total(thumbnails.thumb_dir(self.blob_dir))
        return {
            "db_bytes": db_bytes,
            "blob_bytes": blob_bytes,
            "thumb_bytes": thumb_bytes,
            "total_bytes": db_bytes + blob_bytes + thumb_bytes,
            "thumb_count": sum(1 for f in thumbnails.thumb_dir(self.blob_dir).glob("*") if f.is_file()),
        }

    def vacuum(self) -> int:
        """回收 SQLite 空洞空间，返回回收后的库体积。物理删除后调用。"""
        with self._lock:
            # 先把 WAL 落盘并截断，否则 VACUUM 之后 -wal 仍占着历史峰值体积
            self._checkpoint()
            self._conn.execute("VACUUM")
            self._conn.commit()
            self._checkpoint()
        return self.db_path.stat().st_size if self.db_path.exists() else 0

    def _checkpoint(self) -> None:
        """把 WAL 落盘并截断到 0，释放常驻进程长期占用的磁盘。"""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:  # pragma: no cover - 并发读锁 / 连接已关闭
            # 捕 sqlite3.Error 基类：连接被重复关闭时抛的是 ProgrammingError，
            # 关闭路径不该因此失败。
            log.debug("WAL 检查点暂不可执行：%s", exc)

    # —— 导出 ——
    def export(
        self, clip_ids: Sequence[int], fmt: str = "txt", dest: Path | None = None
    ) -> Path:
        """批量导出为 txt / md / json，返回导出文件路径。"""
        clips = [c for c in (self.get(i) for i in clip_ids) if c is not None]
        if fmt == "json":
            body = json.dumps([asdict(c) for c in clips], ensure_ascii=False, indent=2)
        elif fmt == "md":
            body = "\n\n".join(
                f"## {i + 1}. {c.type.value}\n\n{c.content}" for i, c in enumerate(clips)
            )
        elif fmt == "txt":
            body = ("\n" + "-" * 40 + "\n").join(c.content for c in clips)
        else:
            raise ValueError(f"不支持的导出格式：{fmt}")

        target = dest or (default_data_dir() / f"export_{now_ms()}.{fmt}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    # —— 生命周期 ——
    def close(self) -> None:
        with self._lock:
            self._checkpoint()
            self._conn.close()

    # 兼容旧接口
    def _evict_if_needed(self) -> int:
        """超出 max_items 时淘汰最旧的未固定项（保留自早期版本）。"""
        return self.enforce_limit()
