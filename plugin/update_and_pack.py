#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插件目录里的一键更新 + 打包。

用法：
    python plugin/update_and_pack.py               # 拉源 → 更新快照 → 同步 data/ → 重打 zip → 门禁校验
    python plugin/update_and_pack.py --dry-run     # 只看差异，不写文件、不打包
    python plugin/update_and_pack.py --skip-tests  # 跳过单元测试（更新快，风险自负）
    python plugin/update_and_pack.py --pack-only   # 不联网，只把根目录快照同步进 data/ 并重打 zip

其余参数原样传给 scripts/update_all.py：
    --offline --cn-file --details-file --fallback-file --aliases-file --onecat-file
    --onecat-url --add-missing-charts --no-onecat --no-backup --no-docs --version
    --report --timeout --force

为什么放在 plugin/ 而不是 plugin/astrbot_plugin_maimai_kb/：
    后者会被整体打进插件 zip，脚本不该进安装包；plugin/ 是仓库里的插件工作目录。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PLUGIN_WORKDIR = Path(__file__).resolve().parent
ROOT = PLUGIN_WORKDIR.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_astrbot_plugin as builder  # noqa: E402  同一套打包/门禁逻辑


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finish(zip_path: Path) -> int:
    """校验产物并打印上传所需信息。"""
    info = builder.inspect(zip_path)  # 装了 astrbot 就走它的门禁，否则本地复刻
    drift = builder.drifted_data()
    print("\n" + "=" * 56)
    print(f"插件包：{zip_path.relative_to(ROOT).as_posix()}")
    print(f"  metadata：{info['metadata_entry']} → {info['metadata'].get('name')} "
          f"v{info['metadata'].get('version')}")
    print(f"  文件数：{info['files']}｜体积：{info['size_mb']} MB")
    print(f"  SHA-256：{_sha256(zip_path)}")
    print(f"  门禁校验：通过（{'AstrBot' if info['gate'] == 'astrbot' else '本地复刻规则'}）")
    if drift:
        print(f"  ⚠ data/ 与根目录快照不同步：{', '.join(drift)}（重跑一次不带 --pack-only 可修复）")
    print("  下一步：AstrBot 面板 → 插件 → 安装 → 上传文件，选上面这个 zip")
    print("=" * 56)
    return 0


def main() -> int:
    argv = sys.argv[1:]

    if "--no-plugin" in argv:
        raise SystemExit("这是一键更新打包入口，不接受 --no-plugin。"
                         "只想更新知识库请跑：python scripts/update_all.py --no-plugin")

    if "--pack-only" in argv:
        extra = [arg for arg in argv if arg != "--pack-only"]
        if extra:
            raise SystemExit(f"--pack-only 不能和其它参数一起用：{' '.join(extra)}")
        print("打包模式：不联网，只同步快照并重打 zip …")
        return finish(builder.build(sync=True))

    import update_all  # 延迟导入：--pack-only 不需要 requests 等更新依赖

    sys.argv = ["update_all.py", *argv]
    code = update_all.main()
    if code:
        print(f"\n更新中止（退出码 {code}），没有打包。")
        return code
    if "--dry-run" in argv:
        print("dry-run 结束：没有写文件，也没有重打 zip。")
        return 0
    return finish(builder.OUT_ZIP)


if __name__ == "__main__":
    raise SystemExit(main())
