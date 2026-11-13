#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键更新舞萌数据、打包插件，并推送到 GitHub。

默认流程：
    1. 运行 plugin/update_and_pack.py：抓取最新国服快照 → 校验 → 测试 → 同步插件 data/ → 重打 zip
    2. 提交并推送源仓库（默认 origin）
    3. 同步「仓库根即插件」的发布仓库，提交并推送（AstrBot 从仓库检查更新用）

用法：
    python update_and_publish.py                 # 完整更新并推送两个仓库
    python update_and_publish.py --pack-only     # 不联网，只用当前快照重打包并推送
    python update_and_publish.py --dry-run       # 只看上游差异，不写文件、不推送
    python update_and_publish.py --no-push       # 只更新和打包，不提交、不推送
    python update_and_publish.py --skip-update   # 跳过更新，只提交当前改动并推送
    python update_and_publish.py --skip-tests    # 更新时跳过单元测试（不推荐）
    python update_and_publish.py --offline       # 更新时全部用本地源文件

发布仓库默认是 ../astrbot_plugin_maimai_kb，可用 --plugin-repo-dir 改；
远端默认读 metadata.yaml 的 repo 字段，可用 --plugin-remote 改。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "plugin" / "astrbot_plugin_maimai_kb"
SNAPSHOT = ROOT / "snapshot_meta.json"
UPDATER = ROOT / "plugin" / "update_and_pack.py"
PUBLISHER = ROOT / "scripts" / "publish_plugin_repo.py"
DEFAULT_PLUGIN_REPO = ROOT.parent / "astrbot_plugin_maimai_kb"
SSL_ERROR_RE = re.compile(
    r"(SSL|TLS|certificate|schannel|CRYPT_E_|unexpected eof|server certificate)",
    re.IGNORECASE,
)


def read_metadata() -> tuple[str, str]:
    text = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")
    version = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    repo = re.search(r"^repo:\s*(\S+)", text, re.MULTILINE)
    if not version:
        raise SystemExit("metadata.yaml 里找不到 version")
    return version.group(1).strip("\"'"), (repo.group(1).strip("\"'") if repo else "")


def read_snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _print(text: str) -> None:
    if text and text.strip():
        print(text.rstrip())


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True,
        env: Optional[dict] = None, capture: bool = False
        ) -> subprocess.CompletedProcess:
    printable = " ".join(str(part) for part in cmd)
    print(f"\n$ {printable}")
    result = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if capture:
        _print(result.stdout or "")
        _print(result.stderr or "")
    if check and result.returncode:
        raise SystemExit(f"命令失败（退出码 {result.returncode}）：{printable}")
    return result


def git(args: list[str], *, cwd: Path = ROOT, check: bool = True,
        env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return run(["git", "-c", "core.quotepath=false", *args],
               cwd=cwd, check=check, env=env, capture=True)


def git_env() -> dict:
    env = os.environ.copy()
    # 没有凭据时直接失败，不要卡在交互式输入上。
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def push_with_tls_fallback(cwd: Path, remote: str, branch: str) -> None:
    """推送；若本机证书链导致 TLS 失败，仅对本次重试关闭校验。"""
    env = git_env()
    args = ["push", "-u", remote, f"HEAD:{branch}"]
    result = git(args, cwd=cwd, check=False, env=env)
    if result.returncode and SSL_ERROR_RE.search((result.stdout or "") + (result.stderr or "")):
        print("⚠ 本机证书校验失败，按同一命令重试一次（仅本次关闭 SSL 校验）…")
        retry_env = env.copy()
        retry_env["GIT_SSL_NO_VERIFY"] = "true"
        result = git(args, cwd=cwd, check=False, env=retry_env)
    if result.returncode:
        raise SystemExit(f"git push 失败：{remote} {branch}")


def current_branch(cwd: Path) -> str:
    result = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
    branch = (result.stdout or "").strip()
    return branch if branch and branch != "HEAD" else "main"


def commit_repo(cwd: Path, message: str) -> bool:
    git(["add", "-A"], cwd=cwd)
    status = git(["status", "--porcelain"], cwd=cwd, check=False)
    if not (status.stdout or "").strip():
        print(f"没有内容变化，跳过提交：{cwd}")
        return False

    name = (git(["config", "user.name"], cwd=cwd, check=False).stdout or "").strip()
    email = (git(["config", "user.email"], cwd=cwd, check=False).stdout or "").strip()
    args: list[str] = []
    if name:
        args += ["-c", f"user.name={name}"]
    if email:
        args += ["-c", f"user.email={email}"]
    args += ["commit", "-m", message]
    git(args, cwd=cwd)
    print(f"已提交：{cwd.name}｜{message}")
    return True


def update_plugin(args: argparse.Namespace) -> None:
    cmd = [sys.executable, UPDATER]
    if args.pack_only:
        cmd.append("--pack-only")
    else:
        if args.dry_run:
            cmd.append("--dry-run")
        if args.skip_tests:
            cmd.append("--skip-tests")
        if args.offline:
            cmd.append("--offline")
        if args.timeout:
            cmd.extend(["--timeout", str(args.timeout)])
        if args.extra:
            cmd.extend(args.extra)

    result = run(cmd, check=False)
    attempts = max(1, args.retries + 1)
    attempt = 1
    while result.returncode and attempt < attempts:
        print(f"\n更新失败（退出码 {result.returncode}），{attempt}/{attempts - 1} 次重试将在 8 秒后开始…")
        time.sleep(8)
        attempt += 1
        result = run(cmd, check=False)
    if result.returncode:
        raise SystemExit(
            f"更新/打包失败（退出码 {result.returncode}），没有提交或推送。\n"
            "网络源不稳定时可先重跑，或加 --pack-only 用当前快照重打包。")


def publish_plugin_repo(repo_dir: Path, remote: str, message: str) -> None:
    # 发布仓库已有历史时必须先 clone，否则 publish_plugin_repo.py 在空目录
    # git init 后推一个 unrelated history，会被远端拒绝（non-fast-forward）。
    if not (repo_dir / ".git").exists():
        if repo_dir.exists() and any(repo_dir.iterdir()):
            raise SystemExit(f"{repo_dir} 已存在但不是 git 仓库，请先移走或换 --plugin-repo-dir。")
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        clone = ["git", "clone", remote, str(repo_dir)]
        result = run(clone, check=False, capture=True, env=git_env())
        if result.returncode and SSL_ERROR_RE.search((result.stdout or "") + (result.stderr or "")):
            print("⚠ clone 遇到证书校验失败，仅本次关闭 SSL 校验重试…")
            env = git_env()
            env["GIT_SSL_NO_VERIFY"] = "true"
            result = run(clone, check=False, capture=True, env=env)
        if result.returncode:
            raise SystemExit(f"clone 发布仓库失败：{remote}")

    cmd = [sys.executable, PUBLISHER,
           "--repo-dir", repo_dir,
           "--remote", remote,
           "--message", message]
    result = run(cmd, check=False, capture=True)
    if result.returncode and SSL_ERROR_RE.search((result.stdout or "") + (result.stderr or "")):
        print("⚠ 发布仓库推送遇到证书校验失败，仅本次关闭 SSL 校验重试…")
        env = git_env()
        env["GIT_SSL_NO_VERIFY"] = "true"
        result = run(cmd, check=False, capture=True, env=env)
    if result.returncode:
        raise SystemExit(f"发布仓库同步/推送失败（退出码 {result.returncode}）。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="更新舞萌数据、打包插件并推送到 GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pack-only", action="store_true",
                        help="不联网，只用当前根目录快照同步插件并重打 zip")
    parser.add_argument("--dry-run", action="store_true",
                        help="只检查上游差异，不写文件、不提交、不推送")
    parser.add_argument("--skip-update", action="store_true",
                        help="跳过更新和打包，只提交/推送当前改动")
    parser.add_argument("--skip-tests", action="store_true",
                        help="更新时跳过单元测试（不推荐）")
    parser.add_argument("--offline", action="store_true",
                        help="更新时全部使用本地源文件")
    parser.add_argument("--no-push", action="store_true",
                        help="只更新和打包，不提交、不推送")
    parser.add_argument("--no-plugin-repo", action="store_true",
                        help="只推源仓库，不推 AstrBot 插件发布仓库")
    parser.add_argument("--message", default="", help="自定义提交信息")
    parser.add_argument("--source-remote", default="origin",
                        help="源仓库 remote 名，默认 origin")
    parser.add_argument("--plugin-repo-dir", type=Path, default=DEFAULT_PLUGIN_REPO,
                        help=f"插件发布仓库本地目录，默认 {DEFAULT_PLUGIN_REPO}")
    parser.add_argument("--plugin-remote", default="",
                        help="插件发布仓库远端，默认读 metadata.yaml 的 repo")
    parser.add_argument("--timeout", type=int, default=0,
                        help="更新时单个网络请求超时秒数（透传 update_all.py）")
    parser.add_argument("--retries", type=int, default=1,
                        help="更新失败后的重试次数，默认 1")
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="其余参数原样传给 plugin/update_and_pack.py")
    args, unknown = parser.parse_known_args()
    if unknown:
        args.extra.extend(unknown)
    args.extra = [part for part in args.extra if part != "--"]

    if args.pack_only and args.extra:
        raise SystemExit("--pack-only 不能和额外的 update_all 参数一起用")
    if args.pack_only and args.dry_run:
        raise SystemExit("--pack-only 和 --dry-run 不能同时用。")
    if args.skip_update and args.dry_run:
        raise SystemExit("--skip-update 和 --dry-run 不能同时用。")

    if not args.skip_update:
        update_plugin(args)
        if args.dry_run:
            print("\ndry-run 结束：没有写文件、没有提交或推送。")
            return 0

    version, meta_repo = read_metadata()
    snapshot = read_snapshot()
    snapshot_version = str(snapshot.get("version") or "未知版本")
    songs = snapshot.get("songs", "?")
    charts = snapshot.get("charts", "?")
    default_message = (f"数据更新至 {snapshot_version}（{songs} 首 / {charts} 张，"
                       f"插件 v{version}）")
    message = args.message or default_message

    zip_path = ROOT / "dist" / "astrbot_plugin_maimai_kb.zip"
    if not zip_path.exists():
        raise SystemExit(f"找不到插件包：{zip_path}，请先运行更新或 --pack-only。")

    print(f"\n插件 v{version}｜快照 {snapshot_version}｜{songs} 首 / {charts} 张")
    print(f"插件包：{zip_path}")

    if args.no_push:
        print("\n--no-push：已完成更新和打包，未提交、未推送。")
        return 0

    # 1) 源仓库
    changed = commit_repo(ROOT, message)
    branch = current_branch(ROOT)
    if changed:
        print(f"推送源仓库：{args.source_remote}/{branch}")
        push_with_tls_fallback(ROOT, args.source_remote, branch)
    else:
        print("源仓库没有需要推送的新提交。")

    # 2) AstrBot 发布仓库（仓库根 = 插件）
    if args.no_plugin_repo:
        print("\n--no-plugin-repo：跳过插件发布仓库。")
        return 0
    remote = args.plugin_remote or meta_repo
    if not remote:
        raise SystemExit("metadata.yaml 没有 repo 字段，请用 --plugin-remote 指定。")
    repo_dir = args.plugin_repo_dir.expanduser().resolve()
    print(f"\n发布插件仓库：{remote}\n本地目录：{repo_dir}")
    publish_plugin_repo(repo_dir, remote, args.message or
                        f"v{version}：数据更新至 {snapshot_version}（{songs} 首 / {charts} 张）")

    print("\n✅ 全部完成")
    print(f"源仓库：https://github.com/Oranven/maimai-knowledge-skill")
    print(f"插件仓库：{remote.removesuffix('.git')}")
    print("AstrBot：面板 → 插件 → 检查更新（或上传 dist/astrbot_plugin_maimai_kb.zip）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
