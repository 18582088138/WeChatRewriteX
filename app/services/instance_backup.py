"""Offline instance backup: data + config + dotenv, with verified isolated restore."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3

FORMAT = 1


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("备份/恢复不支持符号链接，请先将文件归集到普通目录")
        if path.is_file():
            yield path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _database_check(path: Path) -> int:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性校验失败")
        return conn.execute("PRAGMA user_version").fetchone()[0]


def backup_instance(runtime: Path, data: Path, destination: Path) -> None:
    from ..pipeline.runtime_lock import RuntimeLock
    from .. import APP_VERSION
    runtime, data, destination = runtime.resolve(), data.resolve(), destination.resolve()
    if not (data / "app.db").is_file() or not (runtime / "config" / "settings.yaml").is_file():
        raise ValueError("数据或配置不完整，拒绝创建实例备份")
    # Local sibling backups are supported, but never recurse into a source tree.
    if destination.exists() or any(destination.is_relative_to(p) for p in (data, runtime / "config")):
        raise ValueError("备份目标必须为全新目录，且位于数据根和配置目录之外")
    if runtime.is_relative_to(data):
        raise ValueError("运行目录不能位于数据根内，请先分离目录")
    guard = RuntimeLock(data).acquire()
    try:
        destination.mkdir(parents=True, mode=0o700)
        (destination / "resource").mkdir()
        with closing(sqlite3.connect((data / "app.db").as_uri() + "?mode=ro", uri=True)) as source:
            target = sqlite3.connect(destination / "resource" / "app.db")
            try:
                source.backup(target)
            finally:
                target.close()
        for path in _files(data):
            if path.relative_to(data).as_posix() in ("app.db", "app.db-wal", "app.db-shm", ".worker.lock"):
                continue
            target = destination / "resource" / path.relative_to(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        for path in _files(runtime / "config"):
            target = destination / "config" / path.relative_to(runtime / "config")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if (runtime / ".env").is_file():
            if (runtime / ".env").is_symlink():
                raise ValueError(".env 不能是符号链接")
            shutil.copy2(runtime / ".env", destination / ".env")
            os.chmod(destination / ".env", 0o600)
        manifest = {"format": FORMAT, "app_version": APP_VERSION,
                    "schema_version": _database_check(destination / "resource" / "app.db"),
                    "files": {p.relative_to(destination).as_posix(): _hash(p) for p in _files(destination)}}
        # This completion marker is created only after every component is copied.
        (destination / "backup-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完整离线备份完成：{destination}")
    finally:
        guard.close()


def restore_instance(source: Path, destination: Path) -> None:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("恢复只允许全新且位于备份之外的运行目录，不覆盖已有数据")
    manifest = json.loads((source / "backup-manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("format") != FORMAT or not isinstance(files, dict):
        raise ValueError("不支持的备份格式")
    if not {"resource/app.db", "config/settings.yaml"}.issubset(files):
        raise ValueError("备份缺少数据库或配置")
    for name, checksum in files.items():
        if not isinstance(name, str) or "\\" in name or ":" in name:
            raise ValueError("备份路径无效")
        relative = Path(name)
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise ValueError("备份路径无效")
        if relative.parts[0] not in ("resource", "config") and name != ".env":
            raise ValueError("备份包含非实例数据")
        path = source / relative
        if not path.resolve().is_relative_to(source) or path.is_symlink() or not path.is_file() or _hash(path) != checksum:
            raise ValueError("备份文件缺失或 SHA256 校验失败")
    actual = {p.relative_to(source).as_posix() for p in _files(source)} - {"backup-manifest.json"}
    if actual != set(files):
        raise ValueError("备份文件清单不一致")
    if _database_check(source / "resource" / "app.db") != manifest["schema_version"]:
        raise ValueError("备份数据库版本不一致")
    # Validate first. Failed copies leave an isolated incomplete destination, never replace a live root.
    destination.mkdir(parents=True, mode=0o700)
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    if (destination / ".env").exists():
        os.chmod(destination / ".env", 0o600)
    print(f"完整备份校验与隔离恢复完成：{destination}")
    print("隔离启动必须显式设置 --runtime-dir <恢复目录> --data-dir <恢复目录>/resource --log-dir <恢复目录>/log，防止旧配置指向原数据")
