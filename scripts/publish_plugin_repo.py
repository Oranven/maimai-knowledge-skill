# -*- coding: utf-8 -*-
"""把 plugin/astrbot_plugin_maimai_kb 同步成「仓库根就是插件」的独立仓库并推送。

AstrBot 的「从仓库安装 / 更新」要求仓库根目录有 metadata.yaml，所以插件发布仓库
的根 = 插件目录（main.py / core/ / data/ / metadata.yaml），文档只带 README 和
COMMANDS.md。源仓库结构（plugin/ 子目录 + 知识库 + 脚本）不变。

用法：
    python scripts/publish_plugin_repo.py --repo-dir <本地仓库目录> \
        --remote https://github.com/<user>/astrbot_plugin_maimai_kb.git

首次执行会 git init 并推送；之后每次执行同步文件、按版本号提交并推送。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "astrbot_plugin_maimai_kb"
DOCS = {ROOT / "plugin" / "README.md": "README.md",
        ROOT / "plugin" / "COMMANDS.md": "COMMANDS.md"}

SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".tmp"}
# 运行时数据：属于安装环境本地，不进仓库
SKIP_NAMES = {"manual_songs.json", "manual_pending.json", "manual_charts.json",
              "official_aliases.json"}

GITIGNORE = """# Python
__pycache__/
*.pyc
*.pyo

# 运行时数据（AstrBot 的 data/plugin_data/<插件名>/ 才是真正的存放位置）
manual_songs.json
manual_pending.json
manual_charts.json
official_aliases.json

# 系统 / 编辑器
.DS_Store
Thumbs.db
.idea/
.vscode/
"""


def read_version() -> str:
    text = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    if not match:
        raise SystemExit("metadata.yaml 里找不到 version")
    return match.group(1).strip("\"'")


def sync_files(repo_dir: Path, remote: str) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    # 清掉除 .git 之外的内容，保证仓库里不留已删除的旧文件
    for item in repo_dir.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()

    for source in sorted(PLUGIN.rglob("*")):
        relative = source.relative_to(PLUGIN)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if source.suffix in SKIP_SUFFIXES or source.name in SKIP_NAMES:
            continue
        target = repo_dir / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for source, name in DOCS.items():
        if source.exists():
            shutil.copy2(source, repo_dir / name)

    (repo_dir / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    # 让 metadata 里的 repo 指向发布仓库，AstrBot 更新时用到
    metadata = repo_dir / "metadata.yaml"
    text = metadata.read_text(encoding="utf-8")
    if re.search(r"^repo:.*$", text, re.MULTILINE):
        text = re.sub(r"^repo:.*$", f"repo: {remote.removesuffix('.git')}",
                      text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\nrepo: {remote.removesuffix('.git')}\n"
    metadata.write_text(text, encoding="utf-8")


def git(repo_dir: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_dir), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：\n{result.stderr.strip()}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", required=True,
                        help="本地仓库目录（首次可不存在）")
    parser.add_argument("--remote", required=True,
                        help="插件仓库地址，如 https://github.com/Oren/astrbot_plugin_x.git")
    parser.add_argument("--message", default="", help="提交信息，默认带版本号")
    parser.add_argument("--dry-run", action="store_true", help="只同步文件不提交")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    version = read_version()
    sync_files(repo_dir, args.remote)
    print(f"已同步 v{version} → {repo_dir}")

    if args.dry_run:
        return 0

    if not (repo_dir / ".git").exists():
        git(repo_dir, "init", "-b", "main")
    git(repo_dir, "add", "-A")
    status = git(repo_dir, "status", "--porcelain")
    if not status:
        print("没有内容变化，跳过提交")
    else:
        message = args.message or f"v{version}"
        git(repo_dir, "-c", "user.name=Oranven",
            "-c", "user.email=2561860767@qq.com", "commit", "-m", message)
        print(f"已提交：{message}")

    remotes = git(repo_dir, "remote")
    if "origin" in remotes.split():
        git(repo_dir, "remote", "set-url", "origin", args.remote)
    else:
        git(repo_dir, "remote", "add", "origin", args.remote)
    git(repo_dir, "push", "-u", "origin", "HEAD:main")
    print(f"已推送：{args.remote}（v{version}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
