"""Offline backup with OS ownership protection and SQLite's consistent backup API."""
import argparse
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    from app.core.config import data_dir
    from app.pipeline.runtime_lock import RuntimeLock
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, help="New backup directory outside the data root")
    args = parser.parse_args()
    root, destination = data_dir().resolve(), args.destination.resolve()
    if not (root / "app.db").is_file():
        parser.error("数据根中没有 app.db，拒绝创建空数据库备份")
    if destination.exists() or destination.is_relative_to(root):
        parser.error("备份目录必须不存在，且位于数据根目录之外")
    guard = RuntimeLock(root).acquire()
    try:
        destination.mkdir(parents=True)
        source = sqlite3.connect((root / "app.db").as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(destination / "app.db")
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        for path in root.iterdir():
            if path.name in ("app.db", "app.db-wal", "app.db-shm", ".worker.lock"):
                continue
            if path.is_dir():
                shutil.copytree(path, destination / path.name)
            elif path.is_file():
                shutil.copy2(path, destination / path.name)
        print(f"一致性备份完成：{destination}")
    finally:
        guard.close()

if __name__ == "__main__":
    main()
