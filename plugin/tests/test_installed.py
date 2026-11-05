# -*- coding: utf-8 -*-
"""安装态测试：把插件放进 data/plugins/ 按 AstrBot 的方式导入，检查处理器是否注册。

需要装有 astrbot 的环境：
  $TMPDIR/astrbot-429/Scripts/python.exe -m unittest discover -s plugin/tests
"""

import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "astrbot_plugin_maimai_kb"


class InstalledPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import astrbot.api.star  # noqa: F401  先导入，避免 4.14 的循环导入
            from astrbot.core.star.star_handler import star_handlers_registry  # noqa: F401
        except Exception as exc:  # 没装 astrbot 时跳过
            raise unittest.SkipTest(f"未安装 astrbot：{exc}")

        cls.root = Path(tempfile.mkdtemp(prefix="astrbot-plugin-test-"))
        target = cls.root / "data" / "plugins" / "astrbot_plugin_maimai_kb"
        shutil.copytree(PLUGIN_DIR, target)
        sys.path.insert(0, str(cls.root))
        cls.module = importlib.import_module("data.plugins.astrbot_plugin_maimai_kb.main")

    def test_handlers_registered(self):
        from astrbot.core.star.star_handler import star_handlers_registry

        names = set()
        for handler in star_handlers_registry:
            module_path = getattr(handler, "handler_module_path", "") or ""
            if "astrbot_plugin_maimai_kb" in module_path:
                names.add(getattr(handler, "handler_name", ""))
        self.assertIn("maimai", names)
        self.assertIn("maimai_lookup", names)
        self.assertIn("inject_chart_info", names)
        # 手动录歌的引导会话必须真的注册成消息处理器，否则聊天里追问不生效
        self.assertIn("manual_session", names)

    def test_plugin_instantiates_and_answers(self):
        import asyncio

        class Ctx:
            pass

        class Ev:
            message_str = "舞萌 Oshama Scramble!"
            unified_msg_origin = "test:1"

            def plain_result(self, text):
                return text

        # 手动库写到临时目录，别污染仓库/真实 data/plugin_data
        plugin = self.module.Main(Ctx(), {"manual_dir": str(self.root / "plugin_data")})

        async def drive():
            return [chunk async for chunk in plugin.maimai(Ev())]

        reply = asyncio.run(drive())[0]
        self.assertIn("13.6", reply)


if __name__ == "__main__":
    unittest.main()
