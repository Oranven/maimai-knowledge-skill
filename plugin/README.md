# AstrBot 插件：舞萌DX知识库

把本仓库的谱面数据包成 AstrBot 插件，在 QQ / Telegram 等平台里查询舞萌DX歌曲的**显示等级、精确定数、别名、谱师、音符数与谱面特征**。完全离线、纯标准库，不调用任何模型，所以不会编造定数。

- 收录：1294 首歌曲 / 5520 张常规谱面（快照 CN1.56-E）
- 定数来源：OneCat 官方谱面站（`https://dw.moant.cn:34225/api/getMusicData`）
- 范围/分类/版本：国服曲库（CrazyKidCN/maimaiDX-CN-songs-database）
- 谱师/音符数：水鱼查分器

## 安装

**方式一：WebUI 上传（推荐）**

1. 插件 → 安装 → 上传文件
2. 选择 `dist/astrbot_plugin_maimai_kb.zip`（0.83 MB）
3. 重载插件，看到日志 `[maimai_kb] 已加载 1294 首歌曲 / 5520 张谱面` 即成功

**方式二：解压到 data/plugins**

```bash
unzip dist/astrbot_plugin_maimai_kb.zip -d <AstrBot>/data/plugins/
```

目录结构必须是 `<AstrBot>/data/plugins/astrbot_plugin_maimai_kb/metadata.yaml`。

> ⚠️ 这个 zip 里 `metadata.yaml` 在顶层文件夹内，是 AstrBot 插件包；本仓库根目录打出来的「Skills 包」（只有 `SKILL.md`）**不能**用插件上传接口安装。

## 指令

| 指令 | 说明 |
| --- | --- |
| `舞萌 <曲名>` | 谱面、定数、谱师、别名 |
| `舞萌 牛乳` | 支持别名/外号查询 |
| `舞萌 定数 <曲名> [难度]` | 只看定数；难度可写 绿/黄/红/紫/白 或 bas/adv/exp/mas/re |
| `舞萌 13+` | 按显示等级列出谱面（按定数降序） |
| `舞萌 13+ dx master` | 等级 + 类型 + 难度筛选 |
| `舞萌 定数 14.5-15.0` | 按定数区间筛选 |
| `舞萌 统计` | 数据快照版本与统计 |
| `舞萌 帮助` | 用法说明 |

别名：`maimai` / `mai` / `查歌`。**完整指令目录（含全部别名、筛选词、权限、常见报错）见 [COMMANDS.md](COMMANDS.md)。**

示例：

```
> 舞萌 Oshama Scramble!
🎵 Oshama Scramble!
艺术家｜t+pazolite
分类｜舞萌　版本｜ORANGE PLUS
──────────────
标准 谱面（#363）
  BASIC     Lv.6   定数 6.0
  ADVANCED  Lv.8+  定数 8.6
  EXPERT    Lv.11+ 定数 11.9｜谱师 Techno Kitchen
  MASTER    Lv.14  定数 14.5｜谱师 Jack｜底力谱 体力谱 绝赞段 …
──────────────
DX 谱面（#10363）
  BASIC     Lv.4   定数 4.0
  ADVANCED  Lv.8+  定数 8.7
  EXPERT    Lv.11  定数 11.4｜谱师 はっぴー
  MASTER    Lv.13+ 定数 13.6｜谱师 Jack｜底力谱 体力谱 绝赞段 …
──────────────
别名｜oshama scramble!、标奶、女同15、猫娘贴贴、牛乳 …
```

## 手动录歌（聊天里添加歌曲）

官方快照里还没有的曲子（新曲、联动曲、自制谱等）可以直接在聊天里补，不用改 JSON、不用重打包。

| 指令 | 谁能用 | 说明 |
| --- | --- | --- |
| `舞萌 添加歌曲 曲名 \| 艺术家 [\| 分类] [\| 版本] [\| 别名] [\| dx/标准]` | 管理员 | 建档；只发 `舞萌 添加歌曲` 会进入引导。别名用逗号/顿号隔开：`... \| 葱歌、千本桜`；第 6 段填 `dx`/`标准` 表示这些别名只属于那类谱面 |
| `舞萌 加别名 曲名 \| 别名1, 别名2 [\| dx 或 标准]` | 管理员 | 追加别名；**官方快照里的歌也能改**；末段 `dx`/`标准` = 该类型专属别名，对已有别名再发一次带类型就是改归属（也可在引导里发 `别名 xxx, yyy` / `别名 xxx dx`） |
| `舞萌 删除别名 曲名 \| 别名1 [\| dx 或 标准]` | 管理员 | 删除别名（曲名本身不能删）；带类型就只在该类型别名里找；官方自带别名也能隐藏，再加回来即恢复 |
| 引导中逐行发 `紫 14+ 14.9` | 管理员 | 难度 等级 定数；定数可省（显示为 —），难度也认 bas/adv/exp/mas/re 与 绿/黄/红/紫/白，前面可加 `dx` / `标准` |
| `舞萌 加谱面 曲名 \| 紫 \| 14+ \| 14.9` | 管理员 | 事后补/改谱面；写成 `曲名 \| 标准 \| 紫 \| 14 \| 14.2` 就是标准谱面。手动库没有这首歌时自动去官方快照匹配并打「谱面补丁」（同名曲用 `曲名@艺术家` 指定） |
| `舞萌 改谱面信息 曲名 \| dx 紫 \| 谱师=某人 \| 标签=a,b \| 音符=1234` | 管理员 | 改官方谱面的谱师 / 标签 / 音符数（不动等级、定数）；不写字段就查看当前值。只改等级/定数时这些字段会保留 |
| `舞萌 删除歌曲 曲名` / `舞萌 删除谱面 曲名 \| 紫` | 管理员 | 删除手动条目 / 单张手动谱面；官方曲目则是撤销该张谱面补丁 |
| `舞萌 手动列表` | 管理员 | 手动库里有什么 |
| `舞萌 提交 曲名 \| 艺术家 \| 紫 \| 14+ \| 14.9` | 所有人 | 进待审核队列 |
| `舞萌 待审核` / `舞萌 通过 <编号>` / `舞萌 驳回 <编号>` | 管理员 | 审核普通用户的提交 |
| `舞萌 取消` | 管理员 | 退出引导 |

示例（管理员在群里）：

```
> 舞萌 添加歌曲
🎙 手动录歌开始。
请发一条：曲名 | 艺术家 | 分类(可空) | 版本(可空) | 别名(可空) | 别名归属(可空)
例如：千本樱 | 黒うさP | 流行&动漫 | 手动录入 | 葱歌、千本桜
别名归属填 dx 或 标准，表示这些别名只对那类谱面生效；不填就是通用别名。
随时发「取消」退出。
> 千本樱 | 黒うさP | 流行&动漫 | 手动录入 | 葱歌、千本桜
已建档「千本樱」（黒うさP｜流行&动漫｜手动录入），接着加谱面：难度 等级 定数
> 紫 14+ 14.9
「千本樱」已写入 DX MASTER Lv.14+
> 别名 千本樱(初音)、初音葱曲
「千本樱」已加别名：千本樱(初音)、初音葱曲（共 4 个）
> 红 12 12.2
「千本樱」已写入 DX EXPERT Lv.12
> 完成
✅ 「千本樱」已保存，共 2 张谱面。

> 舞萌 葱歌
🎵 千本樱
...
别名｜葱歌、千本桜、千本樱(初音)、初音葱曲
```

同一首歌同时有标准谱面和 DX 谱面、且两类外号不同时：

```
> 舞萌 添加歌曲 双谱面曲 | 某P | 舞萌 | 手动录入 | 双谱面曲DX名 | dx
已建档「双谱面曲」（某P｜舞萌｜手动录入）
> 标准 紫 14 14.2
「双谱面曲」已写入 标准 MASTER Lv.14
> 紫 14+ 14.8
「双谱面曲」已写入 DX MASTER Lv.14+
> 别名 双谱面曲标准名 标准
「双谱面曲」已加别名（标准谱面专属）：双谱面曲标准名（共 3 个）
> 完成

> 舞萌 双谱面曲DX名
🎵 双谱面曲
DX 谱面（手动）
  MASTER    Lv.14+ 定数 14.8
别名（DX 谱面）｜双谱面曲DX名
ℹ️「双谱面曲DX名」是 DX 谱面专属别名，只显示了 DX 谱面；看另一类型就发「舞萌 双谱面曲DX名 标准」。

> 舞萌 双谱面曲            ← 用曲名查，两组谱面都在
标准谱面（手动）  MASTER Lv.14 定数 14.2
DX 谱面（手动）    MASTER Lv.14+ 定数 14.8
别名（标准谱面）｜双谱面曲标准名
别名（DX 谱面）｜双谱面曲DX名
```

要点：

- **数据放在插件之外的持久目录**：`<AstrBot>/data/plugin_data/astrbot_plugin_maimai_kb/manual_songs.json`（待审核 `manual_pending.json`，官方谱面补丁 `manual_charts.json`，官方别名补丁 `official_aliases.json`），不进 `songs.json`、也不进 zip。所以 `update_all.py` 刷新快照和覆盖安装新 zip 都不会丢；配置项 `manual_dir` 可以改这个目录。
- **定数必须和显示等级自洽**：写 `紫 14 14.9` 会被拒绝并提示「14.9 对应 14+」。不想填定数就留空，该谱面定数显示 —，插件不会编造数值。
- **手动条目参与全部查询**：曲名/别名、`舞萌 13+`、`舞萌 定数 14.5-15.0`、AI 对话注入都能命中，结果里带 `📝 手动录入` 和录入人。
- **权限**：`admin_qq` 白名单里的 QQ 号，或 AstrBot 判定的管理员 `event.is_admin()`；普通用户默认只能 `提交`，走审核。`allow_all_edit` 只建议调试时开。
- 手动条目没有官方 ID，谱面行显示「手动」而不是 `#曲目ID`。
- **别名规则**：逗号/顿号/分号/斜杠分隔，最多 20 个；空格只有在整串不是已知曲名时才当分隔符（`HOT LIMIT` 这类带空格的曲名不会被拆）。别名不能等于**另一首歌的曲名**，否则查询会串台，会直接拒绝。
- **别名按谱面类型分开**：别名分「通用」「标准谱面专属」「DX 谱面专属」三种，存在 `alias_scopes` 里。用类型专属别名查询时会**自动只显示该类型谱面**，并给出提示；用曲名或通用别名查询则两类谱面都显示。
- **同一首歌可同时有标准与 DX 谱面**：谱面按 `(类型, 难度)` 存，`加谱面` / 引导里加 `标准` 前缀即可写标准谱面，`difficulty.standard` 和 `difficulty.dx` 互不覆盖，定数也各自独立。
- **官方快照里的歌也能补谱面**：`舞萌 加谱面 Oshama Scramble! | dx 白 15 15.0` 会写成 `manual_charts.json` 里的谱面补丁（同名曲用 `曲名@艺术家` 定位），只改那一张、带 📝 标记、进入等级/定数区间检索；`舞萌 删除谱面 曲名 | dx 白` 撤销后恢复官方数据。官方 `songs.json` 不会被改。
- **谱面属性也能改**：`舞萌 改谱面信息 Oshama Scramble! | dx 紫 | 谱师=Jack | 标签=底力谱,体力谱 | 音符=1234`，只改谱师/标签/音符，不动等级和定数；只改等级/定数时原有属性会保留。
- **官方快照里的歌也能改别名**：`舞萌 加别名 Oshama Scramble! | 别名 | dx` 写成 `official_aliases.json` 里的别名补丁；追加、隐藏官方自带别名、把别名改成标准 / DX 专属都行，查询时类型专属别名会自动只显示该类型谱面。官方 `songs.json` 不会被改。

## AI 对话

插件注册了 LLM 工具 `maimai_lookup`，并在 `on_llm_request` 里做两件事：

1. 用户在对话中提到曲名（含别名，忽略标点）时，把该曲的定数摘要注入 `system_prompt`
2. 提示模型「资料不足就调用 `maimai_lookup`，不要凭记忆编造定数」

配置项里 `inject_enabled` 可以关掉自动注入。

## 配置（`_conf_schema.json`）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `max_list` | 15 | 等级/区间查询列出的条数 |
| `alias_limit` | 10 | 曲目信息显示的别名个数 |
| `show_charter` | true | 显示谱师 |
| `show_notes` | false | 显示音符总数 |
| `show_tags` | true | 显示谱面特征标签 |
| `inject_enabled` | true | 对话中自动注入谱面资料 |
| `inject_max_songs` | 1 | 每次最多注入几首歌 |
| `max_message_chars` | 3000 | 单条回复字数上限 |
| `manual_enabled` | true | 允许聊天内手动录入（关掉后写入命令全部拒绝） |
| `admin_qq` | 空 | 可写入的 QQ 号，逗号分隔；留空只认 AstrBot 管理员 |
| `user_submit` | true | 允许普通用户提交待审核条目 |
| `allow_all_edit` | false | 所有人可写（仅调试） |
| `manual_max` | 200 | 手动库 / 待审核队列上限 |
| `manual_session_ttl` | 300 | 引导会话等待秒数，超时自动退出 |
| `manual_dir` | 空 | 手动库目录；留空用 `data/plugin_data/<插件名>` |

## 数据更新

数据跟着仓库走，不要在插件目录里手改。最省事的是插件目录下的一键脚本：

```bash
python plugin/update_and_pack.py             # 更新曲库 → 同步 data/ → 重打 zip → 门禁校验
python plugin/update_and_pack.py --dry-run   # 只看差异，不写文件、不打包
python plugin/update_and_pack.py --pack-only # 不联网，只同步 data/ 并重新打包
python plugin/update_and_pack.py --skip-tests # 跳过测试（快，但没验证就打包）
```

它把参数原样转给 `scripts/update_all.py`，所以 `--offline`、`--cn-file`、`--force` 等都能用；测试通过后才打包，失败会停下并提示用 `.backups` 回滚。

也可以分层手动跑：

```bash
python scripts/update_all.py            # 刷新快照并自动同步插件 data/ 与 zip
python scripts/update_all.py --no-plugin # 只更新知识库，不动插件
python scripts/build_astrbot_plugin.py  # 只重新打包 + 门禁校验
```

`sync_plugin()` 会把 `songs.json` / `level_index.json` / `snapshot_meta.json` 复制到 `plugin/astrbot_plugin_maimai_kb/data/`，再重打 `dist/astrbot_plugin_maimai_kb.zip`，上传新 zip 即可完成版本更新。

## 打包

```bash
python scripts/build_astrbot_plugin.py           # 同步快照到 data/ → 打包 → 门禁校验
python scripts/build_astrbot_plugin.py --check   # 只校验已存在的 dist/astrbot_plugin_maimai_kb.zip
```

脚本直接调用 AstrBot 的 `_PluginUpdater.inspect_plugin_archive` 校验产物（没装 astrbot 时按同一规则复刻）。zip 顶层只有一个 `astrbot_plugin_maimai_kb/` 目录，`tests/`、`__pycache__` 不进包。

## 开发与测试

```bash
# 纯查询逻辑（不需要 astrbot）
python -m unittest discover -s plugin/tests

# 安装态测试（需要 astrbot，验证 handler / llm_tool 注册）
python -m unittest discover -s plugin/tests   # 装了解释器里就有 astrbot 时自动执行
```

已在 `astrbot 4.29.1 / Python 3.12` 与 `astrbot 4.14.6 / Python 3.11` 上通过核心 + handler 全套测试。

插件包能否被安装，可以用 AstrBot 自己的门禁函数验证：

```python
from astrbot.core.star.updater import _PluginUpdater
_PluginUpdater.inspect_plugin_archive("dist/astrbot_plugin_maimai_kb.zip")
```

## 结构

```
plugin/
├── astrbot_plugin_maimai_kb/
│   ├── metadata.yaml          # 插件元信息（安装门禁要求）
│   ├── _conf_schema.json      # WebUI 配置项
│   ├── main.py                # 指令 / llm_tool / on_llm_request
│   ├── core/
│   │   ├── store.py           # 索引与查询（纯标准库）
│   │   ├── manual.py          # 手动库 / 谱面补丁 / 官方别名补丁
│   │   ├── render.py          # 中文文本渲染
│   │   └── answer.py          # 意图解析与注入文案
│   └── data/                  # songs.json + level_index.json + snapshot_meta.json
└── tests/
    ├── test_plugin.py         # handler 直调测试
    └── test_installed.py      # data/plugins 安装态测试
```
