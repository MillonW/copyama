"""文件类型识别单测。"""

from __future__ import annotations

from copyama.core.file_kinds import (
    FileKind,
    classify_file,
    classify_paths,
    summarize,
)


def test_classify_by_extension_case_insensitive():
    assert classify_file("a.PNG") is FileKind.IMAGE
    assert classify_file("b.Mp4") is FileKind.VIDEO
    assert classify_file("c.mp3") is FileKind.AUDIO
    assert classify_file("d.7z") is FileKind.ARCHIVE
    assert classify_file("e.docx") is FileKind.DOCUMENT
    assert classify_file("f.pdf") is FileKind.PDF
    assert classify_file("g.py") is FileKind.CODE
    assert classify_file("h.unknown") is FileKind.OTHER


def test_classify_full_path():
    assert classify_file(r"C:\Users\me\pic.jpg") is FileKind.IMAGE
    assert classify_file("/tmp/archive.tar") is FileKind.ARCHIVE


def test_classify_paths_groups():
    grouped = classify_paths(["a.png", "b.png", "c.zip", "d.mp4"])
    assert grouped[FileKind.IMAGE] == ["a.png", "b.png"]
    assert grouped[FileKind.ARCHIVE] == ["c.zip"]
    assert grouped[FileKind.VIDEO] == ["d.mp4"]


def test_summarize():
    assert summarize(["a.png", "b.png", "c.zip"]) == "图片 2、压缩包 1"
    assert summarize([]) == "空"
