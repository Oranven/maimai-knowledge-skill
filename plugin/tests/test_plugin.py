# -*- coding: utf-8 -*-
"""插件单元测试：直接调用 handler，不依赖真实平台适配器。

运行：python -m unittest discover -s plugin/tests
"""

import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "astrbot_plugin_maimai_kb"
sys.path.insert(0, str(PLUGIN_DIR.parent))


class FakeEvent:
    def __init__(self, message: str, sender_id: str = "10001", admin: bool = False):
        self.message_str = message
        self.unified_msg_origin = "test:group:1"
        self.sent = []
        self.sender_id = sender_id
        self.admin = admin
        self.stopped = False

    def plain_result(self, text: str):
        self.sent.append(text)
        return text

    def get_sender_name(self) -> str:
        return "tester"

    def get_sender_id(self) -> str:
        return self.sender_id

    def is_admin(self) -> bool:
        return self.admin

    def stop_event(self) -> None:
        self.stopped = True


class FakeContext:
    pass


class FakeRequest:
    def __init__(self):
        self.system_prompt = "你是测试人格。"


def load_plugin():
    try:
        import astrbot  # noqa: F401
    except ImportError as exc:  # 没有 astrbot 时跳过，别让整个套件报 ERROR
        raise unittest.SkipTest(f"未安装 astrbot：{exc}")
    return importlib.import_module("astrbot_plugin_maimai_kb.main")


class MaimaiPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_plugin()
        # 手动库指到临时目录：不然 Main 初始化会给真实环境建 data/plugin_data
        manual_dir = tempfile.mkdtemp(prefix="maimai-manual-")
        cls.addClassCleanup(shutil.rmtree, manual_dir, ignore_errors=True)
        cls.plugin = cls.module.Main(
            FakeContext(), {"inject_enabled": True, "manual_dir": manual_dir})

    def run_command(self, text: str) -> str:
        event = FakeEvent(text)
        import asyncio

        async def drive():
            return [chunk async for chunk in self.plugin.maimai(event)]

        asyncio.get_event_loop_policy()
        return asyncio.run(drive())[0]

    def test_song_query_shows_level_and_constant(self):
        reply = self.run_command("舞萌 Oshama Scramble!")
        self.assertIn("Oshama Scramble!", reply)
        self.assertIn("定数", reply)
        self.assertIn("13.6", reply)   # DX MASTER 定数
        self.assertIn("14.5", reply)   # 标准 MASTER 定数

    def test_alias_query_resolves(self):
        reply = self.run_command("舞萌 牛乳")
        self.assertIn("Oshama Scramble!", reply)

    def test_level_query_with_filters(self):
        reply = self.run_command("舞萌 13+ dx master")
        self.assertIn("13+", reply)
        self.assertIn("DX", reply)

    def test_ds_range_query(self):
        reply = self.run_command("舞萌 定数 14.9-15.0")
        self.assertIn("定数", reply)
        self.assertIn("15.0", reply)

    def test_ds_range_with_type_and_difficulty_filter(self):
        # 回归：「区间 + 筛选」曾经因为尾部类型词没统一剥离而静默匹配失败
        reply = self.run_command("舞萌 定数 14.8-15.0 dx")
        self.assertIn("定数 14.8–15.0（DX）", reply)
        self.assertNotIn("标准 MASTER", reply)

        reply = self.run_command("舞萌 定数 13.5-13.9 紫")
        self.assertIn("MASTER", reply)
        self.assertNotIn("EXPERT", reply)

    def test_same_title_songs_both_listed(self):
        reply = self.run_command("舞萌 Link")
        self.assertIn("Clean Tears", reply)
        self.assertIn("Circle of friends", reply)

    def test_placeholder_charter_hidden(self):
        reply = self.run_command("舞萌 Oshama Scramble!")
        self.assertNotIn("谱师 -", reply)

    def test_stats_query(self):
        reply = self.run_command("舞萌 统计")
        self.assertIn("谱面", reply)
        self.assertIn("CN", reply)

    def test_help_and_unknown(self):
        self.assertIn("舞萌", self.run_command("舞萌 帮助"))
        unknown = self.run_command("舞萌 这歌根本不存在zzz")
        self.assertTrue("没有找到" in unknown or "可能是这些" in unknown)

    def test_llm_tool_returns_text(self):
        import asyncio
        text = asyncio.run(self.plugin.maimai_lookup(FakeEvent(""), "Oshama Scramble!", "ds"))
        self.assertIn("定数", text)
        self.assertIn("13.6", text)

    def test_injection_adds_chart_info(self):
        import asyncio
        request = FakeRequest()
        # 用户输入没带曲名里的感叹号，也要能命中
        asyncio.run(self.plugin.inject_chart_info(FakeEvent("Oshama Scramble 的紫谱难吗"), request))
        self.assertIn("舞萌DX知识库资料", request.system_prompt)
        self.assertIn("13.6", request.system_prompt)
        self.assertIn("不要凭记忆编造", request.system_prompt)

    def test_injection_skips_unrelated_message(self):
        import asyncio
        request = FakeRequest()
        asyncio.run(self.plugin.inject_chart_info(FakeEvent("今天天气不错"), request))
        self.assertNotIn("舞萌DX知识库资料", request.system_prompt)

    def test_metadata_and_data_files(self):
        base = PLUGIN_DIR
        self.assertTrue((base / "metadata.yaml").exists())
        self.assertTrue((base / "data" / "songs.json").exists())
        self.assertEqual(self.plugin.store.song_count, self.plugin.store.snapshot()["songs"])
        self.assertEqual(self.plugin.store.chart_count, self.plugin.store.snapshot()["charts"])


class ManualEntryPluginTests(unittest.TestCase):
    """聊天内手动录入：权限、一条命令、引导流程、审核、查询贯通。"""

    @classmethod
    def setUpClass(cls):
        cls.module = load_plugin()

    # -------------------------------------------------- 工具

    def make_plugin(self, config=None):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="maimai-manual-")
        shutil.copytree(PLUGIN_DIR / "data", Path(tmp) / "data")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        old = self.module.PLUGIN_DIR
        self.module.PLUGIN_DIR = tmp
        try:
            settings = {"inject_enabled": False, "manual_dir": str(Path(tmp) / "plugin_data")}
            settings.update(config or {})
            plugin = self.module.Main(FakeContext(), settings)
        finally:
            self.module.PLUGIN_DIR = old
        return plugin

    @staticmethod
    def drive(generator):
        import asyncio

        async def collect():
            return [chunk async for chunk in generator]

        return asyncio.run(collect())

    def command(self, plugin, text, **kwargs) -> str:
        chunks = self.drive(plugin.maimai(FakeEvent(text, **kwargs)))
        return chunks[0] if chunks else ""

    def session_line(self, plugin, text, **kwargs):
        event = FakeEvent(text, **kwargs)
        chunks = self.drive(plugin.manual_session(event))
        return (chunks[0] if chunks else ""), event

    # -------------------------------------------------- 权限

    def test_non_admin_cannot_write_but_can_submit(self):
        plugin = self.make_plugin({"admin_qq": "999"})
        refused = self.command(plugin, "舞萌 添加歌曲 越权曲 | 某人", sender_id="10001")
        self.assertIn("管理员", refused)
        self.assertIn("提交", refused)
        submitted = self.command(plugin, "舞萌 提交 越权曲 | 某人 | 紫 | 13+ | 13.8",
                                 sender_id="10001")
        self.assertIn("审核", submitted)
        self.assertEqual(len(plugin.store.manual.pending()), 1)

    def test_whitelisted_admin_can_write(self):
        plugin = self.make_plugin({"admin_qq": "10001,10002"})
        reply = self.command(plugin, "舞萌 添加歌曲 白名单曲 | 某人 | 舞萌 | 手动录入")
        self.assertIn("已建档", reply)
        self.assertEqual(plugin.store.manual_song_count, 1)

    def test_platform_admin_can_write(self):
        plugin = self.make_plugin()
        reply = self.command(plugin, "舞萌 添加歌曲 平台管理员曲 | 某人", admin=True)
        self.assertIn("已建档", reply)

    def test_manual_disabled_blocks_writes(self):
        plugin = self.make_plugin({"admin_qq": "10001", "manual_enabled": False})
        reply = self.command(plugin, "舞萌 添加歌曲 关闭曲 | 某人")
        self.assertIn("关闭", reply)
        self.assertEqual(plugin.store.manual_song_count, 0)

    # -------------------------------------------------- 一条命令

    def test_one_line_add_then_chart_and_query(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 添加歌曲 一条命令曲 | 艺术家A | 流行&动漫 | 手动录入")
        self.assertIn("已建档", reply)
        self.assertIn("接着发谱面", reply)

        reply = self.command(plugin, "舞萌 加谱面 一条命令曲 | 紫 | 14+ | 14.9")
        self.assertIn("MASTER", reply)

        shown = self.command(plugin, "舞萌 一条命令曲")
        self.assertIn("一条命令曲", shown)
        self.assertIn("手动录入", shown)
        self.assertIn("14.9", shown)
        self.assertIn("艺术家A", shown)

        # 等级 / 定数区间查询也能命中手动条目
        self.assertIn("一条命令曲", self.command(plugin, "舞萌 14+ dx"))

    def test_add_song_with_aliases_in_one_command(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(
            plugin, "舞萌 添加歌曲 别名命令曲 | 艺术家E | 舞萌 | 手动录入 | 小干脆面、魔法士")
        self.assertIn("已建档", reply)

        self.assertIn("别名命令曲", self.command(plugin, "舞萌 小干脆面"))
        shown = self.command(plugin, "舞萌 魔法士")
        self.assertIn("别名命令曲", shown)
        self.assertIn("小干脆面", shown)   # 详情里的别名行

    def test_add_and_remove_alias_commands(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲 别名管理曲 | 艺术家F")
        reply = self.command(plugin, "舞萌 加别名 别名管理曲 | 甲乙, 丙丁")
        self.assertIn("已加别名", reply)
        self.assertIn("别名管理曲", self.command(plugin, "舞萌 甲乙"))

        reply = self.command(plugin, "舞萌 删除别名 别名管理曲 | 甲乙")
        self.assertIn("已删除别名", reply)
        self.assertIn("没有找到", self.command(plugin, "舞萌 甲乙"))
        self.assertIn("别名管理曲", self.command(plugin, "舞萌 丙丁"))

    def test_scoped_alias_in_one_command(self):
        """第 6 段填 dx/标准：别名只挂在那类谱面上。"""
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(
            plugin,
            "舞萌 添加歌曲 分类型曲 | 艺术家H | 舞萌 | 手动录入 | DX专属名 | dx")
        self.assertIn("已建档", reply)
        self.command(plugin, "舞萌 加谱面 分类型曲 | 标准 | 紫 | 14 | 14.2")
        self.command(plugin, "舞萌 加谱面 分类型曲 | dx | 紫 | 14+ | 14.8")

        shown = self.command(plugin, "舞萌 DX专属名")
        self.assertIn("分类型曲", shown)
        self.assertIn("14.8", shown)
        self.assertNotIn("14.2", shown)
        self.assertIn("DX 谱面专属别名", shown)
        self.assertIn("别名（DX 谱面）", shown)

        # 曲名查询不受影响，两种谱面都在
        both = self.command(plugin, "舞萌 分类型曲")
        self.assertIn("14.2", both)
        self.assertIn("14.8", both)

    def test_alias_scope_suffix_in_alias_command(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲 后缀类型曲 | 艺术家I")
        self.command(plugin, "舞萌 加谱面 后缀类型曲 | 标准 | 紫 | 13 | 13.0")
        self.command(plugin, "舞萌 加谱面 后缀类型曲 | dx | 紫 | 13+ | 13.7")

        reply = self.command(plugin, "舞萌 加别名 后缀类型曲 | 标准专属名 | 标准")
        self.assertIn("标准谱面专属", reply)
        reply = self.command(plugin, "舞萌 加别名 后缀类型曲 | DX专属名 | dx")
        self.assertIn("DX 谱面专属", reply)

        shown = self.command(plugin, "舞萌 标准专属名")
        self.assertIn("13.0", shown)
        self.assertNotIn("13.7", shown)
        self.assertIn("标准谱面专属别名", shown)

        # 删错类型不会误删
        reply = self.command(plugin, "舞萌 删除别名 后缀类型曲 | 标准专属名 | dx")
        self.assertIn("没有", reply)
        self.assertIn("后缀类型曲", self.command(plugin, "舞萌 标准专属名"))
        reply = self.command(plugin, "舞萌 删除别名 后缀类型曲 | 标准专属名 | 标准")
        self.assertIn("已删除别名", reply)

    # -------------------------------------------------- 官方曲目补谱面

    def test_add_dx_chart_to_official_song(self):
        """官方快照已有的歌：加谱面直接打补丁，不新建手动歌曲。"""
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加谱面 Oshama Scramble! | dx | 白 | 15 | 15.0")
        self.assertIn("官方条目", reply)
        self.assertIn("撤销", reply)
        self.assertEqual(plugin.store.manual_song_count, 0)   # 没重复建档

        shown = self.command(plugin, "舞萌 Oshama Scramble!")
        self.assertIn("Re:MASTER Lv.15", shown)
        self.assertIn("📝 手动修正", shown)
        # 等级 / 定数区间检索也带上，并标 📝
        self.assertIn("Oshama Scramble!", self.command(plugin, "舞萌 15 dx remaster"))
        self.assertIn("📝", self.command(plugin, "舞萌 15 dx remaster"))
        self.assertIn("Oshama Scramble!", self.command(plugin, "舞萌 定数 15.0-15.0"))
        # 手动列表里能看到补丁
        listing = self.command(plugin, "舞萌 手动列表")
        self.assertIn("谱面补丁", listing)
        self.assertIn("Oshama Scramble!", listing)

        # 撤销后恢复官方数据
        reply = self.command(plugin, "舞萌 删除谱面 Oshama Scramble! | dx 白")
        self.assertIn("恢复官方", reply)
        self.assertNotIn("Re:MASTER Lv.15", self.command(plugin, "舞萌 Oshama Scramble!"))
        self.assertNotIn("Oshama Scramble!", self.command(plugin, "舞萌 15 dx remaster"))

    def test_patch_official_song_with_artist_suffix(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(
            plugin, "舞萌 加谱面 Oshama Scramble!@t+pazolite | 紫 13+ 13.7")
        self.assertIn("官方条目", reply)
        shown = self.command(plugin, "舞萌 Oshama Scramble! 紫")
        self.assertIn("13.7", shown)
        self.assertIn("📝 手动修正", shown)

    def test_patch_unknown_song_asks_to_create(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加谱面 官方也没有的曲 | 紫 13 13.0")
        self.assertIn("添加歌曲", reply)
        self.assertEqual(len(plugin.store.manual.patches()), 0)

    def test_patch_requires_admin(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加谱面 Oshama Scramble! | dx 白 15 15.0",
                             sender_id="20002")
        self.assertIn("管理员", reply)
        self.assertEqual(len(plugin.store.manual.patches()), 0)

    def test_add_and_remove_alias_on_official_song(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 官方新别名")
        self.assertIn("已加别名", reply)
        self.assertIn("官方快照文件不动", reply)
        self.assertEqual(plugin.store.manual_song_count, 0)  # 没重复建档

        shown = self.command(plugin, "舞萌 官方新别名")
        self.assertIn("Oshama Scramble!", shown)
        self.assertIn("官方新别名", shown)
        self.assertIn("别名修正", shown)
        listing = self.command(plugin, "舞萌 手动列表")
        self.assertIn("官方曲目的别名修正", listing)
        self.assertIn("官方新别名", listing)

        reply = self.command(plugin, "舞萌 删除别名 Oshama Scramble! | 官方新别名")
        self.assertIn("已删除别名", reply)
        self.assertNotIn("Oshama Scramble!", self.command(plugin, "舞萌 官方新别名"))

    def test_official_alias_scope_filters_dx_and_standard(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 官方DX名 | dx")
        self.assertIn("DX 谱面专属", reply)

        shown = self.command(plugin, "舞萌 官方DX名")
        self.assertIn("Oshama Scramble!", shown)
        self.assertIn("13.6", shown)
        self.assertNotIn("14.5", shown)
        self.assertIn("DX 谱面专属别名", shown)
        self.assertIn("别名（DX 谱面）", self.command(plugin, "舞萌 Oshama Scramble!"))

        # 同一个官方自带别名也能改归属；不带类型 = 改回通用
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 标奶 | 标准")
        self.assertIn("标准谱面专属", reply)
        shown = self.command(plugin, "舞萌 标奶")
        self.assertIn("14.5", shown)
        self.assertNotIn("13.6", shown)
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 标奶")
        self.assertIn("通用别名", reply)
        both = self.command(plugin, "舞萌 标奶")
        self.assertIn("14.5", both)
        self.assertIn("13.6", both)

    def test_edit_chart_metadata_on_official_song(self):
        plugin = self.make_plugin({"admin_qq": "10001", "show_notes": True})
        reply = self.command(
            plugin,
            "舞萌 改谱面信息 Oshama Scramble! | dx 紫 | 谱师=测试谱师 | 标签=测试标签,底力谱 | 音符=1234")
        self.assertIn("DX MASTER", reply)

        shown = self.command(plugin, "舞萌 Oshama Scramble! dx 紫")
        self.assertIn("谱师 测试谱师", shown)
        self.assertIn("测试标签", shown)
        self.assertIn("1234 音符", shown)
        self.assertIn("📝 手动修正", shown)

        current = self.command(plugin, "舞萌 改谱面信息 Oshama Scramble! | dx 紫")
        self.assertIn("测试谱师", current)
        self.assertIn("1234", current)

        # 只改等级/定数，谱师/标签/音符保留
        self.command(plugin, "舞萌 加谱面 Oshama Scramble! | dx 紫 13+ 13.8")
        shown = self.command(plugin, "舞萌 Oshama Scramble! dx 紫")
        self.assertIn("谱师 测试谱师", shown)
        self.assertIn("13.8", shown)

        # 撤销补丁，恢复官方谱师/标签
        self.command(plugin, "舞萌 删除谱面 Oshama Scramble! | dx 紫")
        shown = self.command(plugin, "舞萌 Oshama Scramble! dx 紫")
        self.assertIn("谱师 Jack", shown)
        self.assertNotIn("测试谱师", shown)

    def test_edit_chart_metadata_rejects_unknown_field(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(
            plugin, "舞萌 改谱面信息 Oshama Scramble! | dx 紫 | 不存在的字段=x")
        self.assertIn("没看懂字段", reply)
        self.assertEqual(len(plugin.store.manual.patches()), 0)

    def test_remove_official_builtin_alias_and_restore(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 删除别名 Oshama Scramble! | 标奶")
        self.assertIn("已删除别名", reply)
        self.assertNotIn("Oshama Scramble!", self.command(plugin, "舞萌 标奶"))
        # 再加回来，别名恢复
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 标奶")
        self.assertIn("已加别名", reply)
        self.assertIn("Oshama Scramble!", self.command(plugin, "舞萌 标奶"))

    def test_official_alias_requires_admin(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加别名 Oshama Scramble! | 越权别名",
                             sender_id="20002")
        self.assertIn("管理员", reply)
        self.assertEqual(len(plugin.store.manual.alias_records()), 0)

    def test_official_alias_scope_remove_checks_type(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 加别名 Oshama Scramble! | 标准名 | 标准")
        reply = self.command(plugin, "舞萌 删除别名 Oshama Scramble! | 标准名 | dx")
        self.assertIn("没有", reply)
        self.assertIn("Oshama Scramble!", self.command(plugin, "舞萌 标准名"))
        reply = self.command(plugin, "舞萌 删除别名 Oshama Scramble! | 标准名 | 标准")
        self.assertIn("已删除别名", reply)

    def test_alias_requires_admin(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加别名 谁都能改的曲 | 甲", sender_id="20002")
        self.assertIn("管理员", reply)

    def test_guided_flow_accepts_alias_line(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲")
        reply, _ = self.session_line(plugin, "会话别名曲 | 艺术家G | 舞萌 | 手动录入 | 起手别名")
        self.assertIn("已建档", reply)
        reply, _ = self.session_line(plugin, "别名 中途别名, 第三个")
        self.assertIn("已加别名", reply)
        reply, _ = self.session_line(plugin, "紫 13+ 13.8")
        self.assertIn("MASTER", reply)
        self.session_line(plugin, "完成")

        self.assertIn("会话别名曲", self.command(plugin, "舞萌 起手别名"))
        self.assertIn("会话别名曲", self.command(plugin, "舞萌 中途别名"))
        self.assertIn("会话别名曲", self.command(plugin, "舞萌 第三个"))

    def test_guided_flow_scoped_alias_line(self):
        """引导里「别名 甲,乙 dx」：这类别名只对 DX 谱面生效。"""
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲")
        reply, _ = self.session_line(plugin, "引导分类型曲 | 艺术家J")
        self.assertIn("已建档", reply)
        reply, _ = self.session_line(plugin, "标准 紫 13+ 13.8")
        self.assertIn("标准", reply)
        reply, _ = self.session_line(plugin, "紫 14 14.3")
        self.assertIn("DX", reply)
        reply, _ = self.session_line(plugin, "别名 引导DX名 dx")
        self.assertIn("DX 谱面专属", reply)
        self.session_line(plugin, "完成")

        shown = self.command(plugin, "舞萌 引导DX名")
        self.assertIn("14.3", shown)
        self.assertNotIn("13.8", shown)
        self.assertIn("DX 谱面专属别名", shown)
        self.assertIn("别名（DX 谱面）", self.command(plugin, "舞萌 引导分类型曲"))

    def test_chart_rejects_inconsistent_constant(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲 定数校验曲 | 艺术家B")
        reply = self.command(plugin, "舞萌 加谱面 定数校验曲 | 紫 | 14 | 14.9")
        self.assertIn("14+", reply)
        self.assertIn("不一致", reply)

    def test_add_chart_unknown_song(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 加谱面 不存在的曲 | 紫 | 13 | 13.0")
        self.assertIn("添加歌曲", reply)

    def test_delete_song(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲 待删曲 | 艺术家C")
        self.command(plugin, "舞萌 加谱面 待删曲 | 紫 | 13 | 13.0")
        reply = self.command(plugin, "舞萌 删除歌曲 待删曲")
        self.assertIn("已删除", reply)
        self.assertEqual(plugin.store.manual_song_count, 0)
        self.assertIn("没有找到", self.command(plugin, "舞萌 待删曲"))

    # -------------------------------------------------- 引导流程

    def test_guided_flow_asks_then_saves(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        prompt = self.command(plugin, "舞萌 添加歌曲")
        self.assertIn("曲名 | 艺术家", prompt)

        reply, event = self.session_line(plugin, "引导曲 | 艺术家D | 其他游戏 | 手动录入")
        self.assertIn("已建档", reply)
        self.assertTrue(event.stopped, "引导消息应被会话处理器消费")

        reply, _ = self.session_line(plugin, "紫 14+ 14.9")
        self.assertIn("MASTER", reply)
        reply, _ = self.session_line(plugin, "红 12 12.2")
        self.assertIn("EXPERT", reply)
        reply, _ = self.session_line(plugin, "完成")
        self.assertIn("共 2 张谱面", reply)

        shown = self.command(plugin, "舞萌 引导曲")
        self.assertIn("14.9", shown)
        self.assertIn("12.2", shown)

    def test_guided_flow_cancel(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲")
        reply, _ = self.session_line(plugin, "取消")
        self.assertIn("已退出", reply)
        prompt, event = self.session_line(plugin, "引导曲 | 艺术家D")
        self.assertEqual(prompt, "")
        self.assertFalse(event.stopped)

    def test_session_ignores_commands(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 添加歌曲")
        _, event = self.session_line(plugin, "舞萌 帮助")
        self.assertFalse(event.stopped)
        self.assertTrue(plugin.sessions, "会话不应被指令消息清掉")

    # -------------------------------------------------- 审核流

    def test_submit_review_approve_flow(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 提交 审核曲 | 提交者 | 紫 | 13+ | 13.8",
                             sender_id="20002")
        self.assertIn("审核", reply)

        queue = self.command(plugin, "舞萌 待审核", sender_id="10001")
        self.assertIn("审核曲", queue)
        self.assertIn("提交者", queue)

        entry_id = plugin.store.manual.pending()[0]["id"]
        approved = self.command(plugin, f"舞萌 通过 {entry_id}", sender_id="10001")
        self.assertIn("已通过", approved)
        self.assertIn("13+", self.command(plugin, "舞萌 审核曲"))

        self.assertIn("空的", self.command(plugin, "舞萌 待审核", sender_id="10001"))

    def test_reject_flow(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        self.command(plugin, "舞萌 提交 驳回曲 | 提交者 | 紫 | 13", sender_id="20002")
        entry_id = plugin.store.manual.pending()[0]["id"]
        reply = self.command(plugin, f"舞萌 驳回 {entry_id}", sender_id="10001")
        self.assertIn("已驳回", reply)
        self.assertEqual(plugin.store.manual.pending(), [])

    def test_pending_is_admin_only(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        reply = self.command(plugin, "舞萌 待审核", sender_id="20002")
        self.assertIn("管理员", reply)

    # -------------------------------------------------- 帮助

    def test_help_mentions_manual_commands(self):
        plugin = self.make_plugin({"admin_qq": "10001"})
        help_text = self.command(plugin, "舞萌 帮助")
        self.assertIn("添加歌曲", help_text)
        self.assertIn("dx/标准", help_text)
        self.assertIn("提交", help_text)


if __name__ == "__main__":
    unittest.main()
