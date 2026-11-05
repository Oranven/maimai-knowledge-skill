#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 plugin/astrbot_plugin_maimai_kb 打成可直接上传 AstrBot 面板的插件 zip。

用法：
    python scripts/build_astrbot_plugin.py              # 同步数据 → 打包 → 校验
    python scripts/build_astrbot_plugin.py --no-sync    # 不覆盖插件 data/，直接打包
    python scripts/build_astrbot_plugin.py --check      # 只校验已存在的 zip

AstrBot 的安装门禁（core/star/updater.py::_PluginUpdater.inspect_plugin_archive）只接受
两种布局：metadata.yaml 在 zip 根目录，或 zip 只有一个顶层目录且该目录里有 metadata.yaml；
metadata 必须含非空的 name / desc / version / author。装了 astrbot 时这里直接调用它的门禁，
没装时用同一套规则复刻。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin" / "astrbot_plugin_maimai_kb"
OUT_ZIP = ROOT / "dist" / f"{PLUGIN_DIR.name}.zip"
DATA_FILES = ("songs.json", "level_index.json", "snapshot_meta.json")
REQUIRED_FIELDS = ("name", "desc", "version", "author")
METADATA_NAMES = ("metadata.yaml", "metadata.yml")
# tests/ 不进安装包；缓存与系统垃圾一律排除
SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_FILES = {".DS_Store", "Thumbs.db",
              # 聊天里录入的手动库 / 谱面补丁 / 官方别名补丁属于安装环境本地数据，
              # 不进包，升级覆盖安装才不会丢
              "manual_songs.json", "manual_pending.json", "manual_charts.json",
              "official_aliases.json"}


def sync_data() -> list[str]:
    """把仓库根目录的快照复制进插件 data/，返回真正同步过的文件名。"""
    data_dir = PLUGIN_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    synced = []
    for name in DATA_FILES:
        source = ROOT / name
        if not source.exists():
            raise SystemExit(f"缺数据文件 {source}，先跑 python scripts/update_all.py")
        target = data_dir / name
        if not target.exists() or source.read_bytes() != target.read_bytes():
            shutil.copy2(source, target)
            synced.append(name)
    return synced


def drifted_data() -> list[str]:
    """返回与仓库根目录快照不一致的插件数据文件。"""
    return [name for name in DATA_FILES
            if not (PLUGIN_DIR / "data" / name).exists()
            or (PLUGIN_DIR / "data" / name).read_bytes() != (ROOT / name).read_bytes()]


def collect_files() -> list[Path]:
    files = []
    for path in sorted(PLUGIN_DIR.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(PLUGIN_DIR)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix in SKIP_SUFFIXES or path.name in SKIP_FILES:
            continue
        files.append(path)
    return files


def build(sync: bool = True) -> Path:
    """打 zip：顶层只有 <插件名>/ 一个目录，metadata.yaml 在其根。"""
    if not (PLUGIN_DIR / "metadata.yaml").exists():
        raise SystemExit(f"{PLUGIN_DIR} 里没有 metadata.yaml，不是合法的插件目录")
    if sync:
        for name in sync_data():
            print(f"  数据已同步：{name}")

    OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in collect_files():
            archive.write(path, f"{PLUGIN_DIR.name}/{path.relative_to(PLUGIN_DIR).as_posix()}")
    return OUT_ZIP


def _parse_flat_yaml(text: str) -> dict:
    """无 pyyaml 时的最小顶层标量解析：只认 `key: value` 一行一条。

    够用于元数据门禁（只校验 name/desc/version/author 这类顶层字符串）；
    嵌套块会被跳过，宁可让门禁报“缺字段”，也不静默放行。
    """
    result: dict = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            quote = value[0]
            end = value.rfind(quote)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = value.split(" #", 1)[0].strip()
        result[key.strip()] = value
    return result


def _load_metadata(text: str) -> dict:
    """解析 metadata.yaml：有 pyyaml 用 pyyaml，没有就用最小解析器。"""
    try:
        import yaml
    except ImportError:
        return _parse_flat_yaml(text)
    return yaml.safe_load(text)


def _inspect_local(zip_path: Path) -> dict:
    """不依赖 astrbot 的门禁复刻：返回 {metadata_entry, metadata}。"""

    with zipfile.ZipFile(zip_path) as archive:
        entries = [name for name in archive.namelist() if not name.endswith("/")]
        tops = {name.split("/")[0] for name in entries}
        metadata_entry = None
        for filename in METADATA_NAMES:
            if filename in entries:
                metadata_entry = filename
                break
            if len(tops) == 1:
                candidate = f"{next(iter(tops))}/{filename}"
                if candidate in entries:
                    metadata_entry = candidate
                    break
        if metadata_entry is None:
            raise SystemExit(
                "校验失败：压缩包里找不到顶层的 metadata.yaml，"
                "AstrBot 会报「压缩包不是合法的 AstrBot 插件」。")
        metadata = _load_metadata(archive.read(metadata_entry).decode("utf-8"))
    if not isinstance(metadata, dict):
        raise SystemExit(f"校验失败：{metadata_entry} 不是合法的 YAML 映射")
    missing = [field for field in REQUIRED_FIELDS
               if not isinstance(metadata.get(field), str) or not metadata[field].strip()]
    if missing:
        raise SystemExit(f"校验失败：{metadata_entry} 缺字段或为空：{missing}")
    return {"metadata_entry": metadata_entry, "metadata": metadata}


@contextlib.contextmanager
def _isolated_cwd():
    """导入 astrbot 会在当前目录写 data/cmd_config.json；在临时目录里做完再切回来。"""
    old = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="astrbot-gate-")
    os.chdir(tmp)
    try:
        yield
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def inspect(zip_path: Path) -> dict:
    """优先用 AstrBot 自己的门禁函数校验，装不上再退回本地复刻。"""
    gate = "local"
    try:
        with _isolated_cwd():
            from astrbot.core.star.updater import _PluginUpdater  # 私有类，但这就是面板用的门禁
    except Exception:
        info = _inspect_local(zip_path)
    else:
        gate = "astrbot"
        try:
            with _isolated_cwd():
                info = _PluginUpdater.inspect_plugin_archive(str(zip_path))
        except ValueError as exc:  # AstrBot 的报错原文直接透出，便于对照
            raise SystemExit(f"校验失败（AstrBot 门禁）：{exc}") from exc
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
    info = dict(info)
    info["files"] = len(names)
    info["size_mb"] = round(zip_path.stat().st_size / 1024 / 1024, 2)
    info["gate"] = gate
    return info


def _astrbot_version() -> str:
    try:
        from importlib.metadata import version
        return version("astrbot")
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 AstrBot 舞萌DX知识库插件包")
    parser.add_argument("--check", action="store_true", help="只校验已有的 zip")
    parser.add_argument("--no-sync", action="store_true", help="不把根目录快照同步进插件 data/")
    args = parser.parse_args()

    zip_path = OUT_ZIP
    drifted = drifted_data()
    if args.check:
        if not zip_path.exists():
            raise SystemExit(f"{zip_path} 不存在，先不带 --check 跑一次")
    else:
        if drifted and not args.no_sync:
            print(f"  插件 data/ 与仓库快照不一致，将同步：{', '.join(drifted)}")
        zip_path = build(sync=not args.no_sync)

    info = inspect(zip_path)
    metadata = info["metadata"]
    print(f"已生成 {zip_path.relative_to(ROOT).as_posix()}"
          f"（{info['files']} 个文件，{info['size_mb']} MB）")
    print(f"  metadata：{info['metadata_entry']} → {metadata.get('name')} v{metadata.get('version')}")
    print(f"  校验方式：{('AstrBot ' + _astrbot_version()).strip() if info['gate'] == 'astrbot' else '本地复刻规则'}")
    print("  校验：通过，可直接在 AstrBot 面板「插件 → 安装 → 上传文件」安装")
    if drifted and args.no_sync:
        print(f"  ⚠ 注意：zip 里的 data/ 与根目录快照不同步：{', '.join(drifted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
