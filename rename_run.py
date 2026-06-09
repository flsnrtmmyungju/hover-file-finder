#!/usr/bin/env python3
"""서버 없이 이름정리를 직접 실행하는 스크립트.

사용법:
  python rename_run.py            # 전체 (downloads 하위 모든 폴더)
  python rename_run.py downloads  # 다운로드 폴더 최상위만
  python rename_run.py archive    # 소설 폴더만
"""
import sys
from server import _do_rename, load_config, resolve_downloads_dir
import os

config = load_config()
downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
archive_folder = config.get("archive_folder", "archive")
novel_dir = os.path.join(downloads_dir, archive_folder)

mode = sys.argv[1] if len(sys.argv) > 1 else "all"

if mode == "downloads":
    _do_rename(downloads_dir, "다운로드", recursive=False)
elif mode == "archive":
    if not os.path.isdir(novel_dir):
        print(f"오류: {novel_dir} 폴더가 없습니다.")
        sys.exit(1)
    _do_rename(novel_dir, "소설폴더", recursive=True)
else:
    _do_rename(downloads_dir, "전체", recursive=True)
