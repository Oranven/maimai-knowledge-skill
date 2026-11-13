# 🎵 舞萌DX歌曲知识库

查询国服歌曲、别名、显示等级、定数和谱面特征，并通过现有工具查 B50、封面和拟合难度。

当前全量快照：**CN1.56-F**（国服源更新于 2026-11-13），**1306 条歌曲记录、1305 个唯一标题、5572 张常规谱面、6 个分类**。定数与显示等级已按 [OneCat 官方谱面站](https://dw.moant.cn:34225/onecat/#/official) 刷新（2026-11-13）：5572 张谱面全部有定数，无 `null`。两首 `Link` 按艺术家区分，不能只按标题去重。

## 文件结构

| 文件 | 用途 |
| --- | --- |
| `SKILL.md` | AstrBot / OpenCode 的查询与工具说明 |
| `songs.json` | 完整国服歌曲快照，含标准/DX ID、显示等级、精确定数、别名及保留标签 |
| `level_index.json` | 按精确显示等级分组的谱面索引，如 `12`、`12+` |
| `knowledge_base/INDEX.md` | 自动生成的分类、版本与标签统计 |
| `knowledge_base/*.md` | 六个分类的歌曲查询文档 |
| `scripts/update_all.py` | **版本更新一条命令**：备份 → 抓取 → 定数 → 校验 → 写入 → 测试 |
| `scripts/update_knowledge_base.py` | 全量同步、详情补缺、校验与生成的底层入口 |
| `scripts/sync_onecat.py` | 只刷新定数与显示等级（含显示等级换算） |
| `snapshot_meta.json` | 快照版本号、国服源日期与统计，由脚本写入 |
| `scripts/generate_kb.py` | 从已提交快照离线重建的兼容入口 |
| `scripts/maimai_lookup.py` | 现有 Developer-Token 查分工具 |
| `scripts/maimai_utils.py` | 封面与拟合难度工具 |
| `plugin/astrbot_plugin_maimai_kb/` | **AstrBot 插件**：用同一份快照做离线指令 + LLM 工具查询 |
| `scripts/publish_plugin_repo.py` | 把插件同步成「仓库根即插件」的发布仓库并推送（AstrBot 从仓库更新用） |
| `dist/astrbot_plugin_maimai_kb.zip` | 可直接上传到 AstrBot 插件页的安装包 |
| `dist/maimai-knowledge.zip` | Skills 包（给 AstrBot「技能」页 / OpenCode 用，不是插件） |

## AstrBot 插件：从仓库安装与更新

插件单独发布在 **[Oranven/astrbot_plugin_maimai_kb](https://github.com/Oranven/astrbot_plugin_maimai_kb)**，仓库根目录就是插件本体（`metadata.yaml` / `main.py` / `core/` / `data/`），符合 AstrBot「从仓库安装」的布局要求。

在 AstrBot 面板「插件 → 安装 → 从仓库安装」粘贴：

```
https://github.com/Oranven/astrbot_plugin_maimai_kb
```

之后面板里的「检查更新」会拉取该仓库、读根目录 `metadata.yaml` 的 `version` 并与已装版本比较；升级只替换代码与官方快照，`data/plugin_data/astrbot_plugin_maimai_kb/` 里的手动数据（`manual_songs.json`、`manual_pending.json`、`manual_charts.json`、`official_aliases.json`）不受影响。

也可以继续上传 `dist/astrbot_plugin_maimai_kb.zip` 手动安装。

发布新版本（本仓库改完后同步过去）：

```bash
python scripts/publish_plugin_repo.py \
  --repo-dir ../astrbot_plugin_maimai_kb \
  --remote https://github.com/Oranven/astrbot_plugin_maimai_kb.git
```

脚本做的事：按插件目录重建仓库内容（排除 `__pycache__` 与运行时数据）→ 带上 `plugin/README.md`、`plugin/COMMANDS.md` → 把 `metadata.repo` 改写成发布仓库地址 → 按版本号提交并推送。

## 安装与查询

```bash
git clone https://github.com/Oranven/maimai-knowledge-skill.git
cd maimai-knowledge-skill
pip install requests maimai-py
```

将仓库放到 AstrBot 的 skills 目录并重新加载（装成「技能」）；想要不依赖模型的指令查询，用下面的 AstrBot 插件。OpenCode 可按其技能目录配置使用。静态歌曲查询不需要 Token，也不需要访问网络。

```bash
python scripts/maimai_lookup.py YOUR_TOKEN qq 114514
python scripts/maimai_lookup.py YOUR_TOKEN username example_user
python scripts/maimai_utils.py --help
```

**Developer-Token 将于 2027-01-01 00:00（UTC+8）失效。** 本次保留查分逻辑，只注明失效时间；OAuth 迁移后续另行处理。

## AstrBot 插件（推荐用法）

`plugin/astrbot_plugin_maimai_kb/` 把这份快照包成了真正的 AstrBot 插件：离线、纯标准库、不调模型，定数不会被大模型编造。

```bash
# 上传 dist/astrbot_plugin_maimai_kb.zip 到 插件 → 安装 → 上传文件
# 或解压到 <AstrBot>/data/plugins/，目录内必须有 metadata.yaml
```

| 指令 | 说明 |
| --- | --- |
| `舞萌 Oshama Scramble!` | 谱面、定数、谱师、别名 |
| `舞萌 牛乳` | 别名/外号 |
| `舞萌 定数 <曲名> [难度]` | 只看定数 |
| `舞萌 13+ dx master` | 按等级筛选 |
| `舞萌 定数 14.5-15.0` | 按定数区间筛选 |
| `舞萌 统计` / `舞萌 帮助` | 快照信息 / 用法 |
| `舞萌 添加歌曲 曲名 \| 艺术家 \| 分类 \| 版本 \| 别名 [\| dx/标准]` | **聊天里手动补歌**（管理员，缺字段会追问；别名用逗号隔开，末段填 `dx`/`标准` 表示该别名只对那类谱面生效） |
| `舞萌 加谱面 曲名 \| dx 白 15 15.0` | **给官方已有的歌补/改谱面**（管理员；写成 `manual_charts.json` 补丁，官方快照不动，`舞萌 删除谱面 曲名 \| dx 白` 撤销） |
| `舞萌 改谱面信息 曲名 \| dx 紫 \| 谱师=某人 \| 标签=a,b \| 音符=1234` | **改官方谱面的谱师 / 标签 / 音符数**（管理员；不动等级定数，撤销补丁即恢复官方值） |
| `舞萌 加别名 曲名 \| 别名 \| dx` | **给官方已有的歌改别名 / 分标准·DX 归属**（管理员；写成 `official_aliases.json` 补丁，官方快照不动，别名查询自动只显示对应类型谱面） |
| `舞萌 提交 曲名 \| 艺术家 \| 紫 \| 14+ \| 14.9` | 普通用户提交，管理员用 `舞萌 待审核` / `舞萌 通过 <编号>` 审核 |

手动录入的数据存在 AstrBot 的 `data/plugin_data/astrbot_plugin_maimai_kb/`，与官方快照分开：`update_all.py` 刷新曲库、覆盖安装新 zip 都不会丢。

完整指令目录（全部指令别名、筛选词、权限、引导流程、常见报错）：[plugin/COMMANDS.md](plugin/COMMANDS.md)。

同时注册 `maimai_lookup` LLM 工具，并在对话提到曲名时把定数摘要注入 `system_prompt`。细节见 [`plugin/README.md`](plugin/README.md)。

> 插件包（`metadata.yaml` 在 zip 顶层文件夹内）和技能包（只有 `SKILL.md`）是两种东西：前者走「插件 → 安装」，后者走「插件 → 技能」。用错入口就会得到 `未找到 metadata.yaml 或 metadata.yml`。

## 数据与优先级

1. [国服曲库](https://github.com/CrazyKidCN/maimaiDX-CN-songs-database)：决定收录范围、标题、艺术家、分类与版本。同步目标为常规 SD/DX 谱面，不收录宴谱。
2. [OneCat 官方谱面站](https://dw.moant.cn:34225/onecat/#/official)（`/api/getMusicData`）：决定**精确定数 `ds` 与显示等级**。显示等级由定数按官方边界换算（7 级及以上：定数 x.6-x.9 为 `x+`，x.0-x.5 为 `x`；1-6 级只有整数档），保证 `value` 与 `ds` 永远一致。
3. [水鱼 music_data](https://www.diving-fish.com/api/maimaidxprober/music_data)：补充谱面 ID、谱师与音符数，并作为定数交叉校验源，无需 Developer-Token。
4. [备用谱面 CSV](https://github.com/Choimoe/dxdataViewer/blob/main/data/csv/merged/sheets.csv)：水鱼不可用或缺少曲目时补缺。
5. [别名 API](https://www.yuzuchan.moe/api/maimaidx/maimaidxalias)：合并在线和已有别名；失败时保留已有别名。

本快照全部 5572 张谱面已匹配 ID；5556 张的 `ds` 来自 OneCat，4 首（ローリンガール、One Step Ahead、Endless, Sleepless Night、LANCE）的谱面 OneCat 未收录，保留原水鱼定数。`ds_source` 和 `detail_source` 分别记录定数与谱面详情来源；不要把空定数解释为 0。

保留原有 926 首含标签歌曲。旧 Markdown 标签未区分 SD/DX，因此 `songs.json.chart_tags` 为歌曲层的历史参考；谱面查询应优先使用 `level_index.json.chart_tags`。新曲不凭空生成配置标签，历史标签不保证仍适合新谱面。

## 更新与校验

从任意工作目录调用（路径以脚本所在仓库为准）。

版本更新只需两条命令（先看差异，再落盘）：

```bash
python scripts/update_all.py --dry-run     # 抓取全部源并报告差异，不写文件
python scripts/update_all.py               # 备份 → 更新 → 重建文档 → 跑测试
```

`update_all.py` 会：备份 `songs.json` / `level_index.json` 到 `.backups/<时间戳>/` → 抓国服库、水鱼、别名 → 用 OneCat 刷新定数与显示等级 → 校验 → 写快照与 `snapshot_meta.json` → 同步 README/SKILL 里的版本号统计 → 运行单元测试。常用开关：

| 开关 | 作用 |
| --- | --- |
| `--add-missing-charts` | 补上 OneCat 已有、快照缺失的谱面（典型：国服未收录的新增 Re:MASTER） |
| `--no-backup` / `--no-docs` / `--skip-tests` | 跳过备份 / 文档同步 / 单元测试 |
| `--version CN1.57` | 手动指定版本号（默认读国服源 README） |
| `--force` | 新快照歌曲数比上一版少 20% 时仍写入（源异常保护默认中止） |
| `--offline --cn-file … --details-file … --onecat-file …` | 完全离线复现 |
| `--report out.json` | 导出新曲/新谱面/定数变化明细 |

底层命令仍可单独使用：

```bash
python scripts/update_knowledge_base.py --dry-run
python scripts/update_knowledge_base.py
python scripts/sync_onecat.py --dry-run
python scripts/sync_onecat.py
python scripts/update_knowledge_base.py --validate-only
python scripts/update_knowledge_base.py --render-only
python -m unittest discover -s tests
git diff --check
```

首次命令抓取并验证，但不写文件。正式同步先完成抓取、匹配与校验，再更新歌曲快照、等级索引和 Markdown。校验空源、重复身份、谱面完整性、等级/定数一致性、ID 误配和音符数；失败时退出，不发布未经校验的结果。

全量同步会顺带拉取 OneCat 定数；只想刷新定数与显示等级时用 `scripts/sync_onecat.py`，它按 `(类型, 曲目ID)` 匹配、跳过宴谱，只改 `ds` / `ds_source` / `value`，别名、谱师、音符数和标签保持不变，`--report out.json` 可导出逐条变更。

支持本地源复现，避免测试依赖实时接口：

```bash
python scripts/update_knowledge_base.py --cn-file /path/maidata.json \
  --details-file /path/music_data.json --fallback-file /path/sheets.csv \
  --aliases-file /path/aliases.json --onecat-file /path/getMusicData.json --dry-run
python scripts/sync_onecat.py --input /path/getMusicData.json --dry-run
```

`--details-file` 也支持备用 CSV。别名文件为 `[]` 时保留本地别名。离线重建不更新网络源；新增全量同步时应同时核对国服源 README 的版本，更新本文的快照标识和统计。

旧 `match_ids.py`、`convert_maidata.py`、`integrate_alias.py`、`integrate_tags.py` 保留为历史工具，不再作为更新流水线；它们依赖仓库未附带的旧中间文件。`generate_kb.py` 已接入新快照。

## AstrBot 插件（可选导出）

同一份快照可以打成 AstrBot 插件，直接在机器人里用 `舞萌 <曲名>`、`舞萌 13+`、`舞萌 定数 13.5-13.9` 查询（离线、不经过模型，定数不会被编造）：

```bash
python scripts/build_astrbot_plugin.py     # 同步 data/ → 打包 → 用 AstrBot 门禁校验
# 产出 dist/astrbot_plugin_maimai_kb.zip，面板「插件 → 安装 → 上传文件」即可
```

源码在 `plugin/astrbot_plugin_maimai_kb/`，结构与测试说明见 [plugin/README.md](plugin/README.md)。曲库更新后跑 `python plugin/update_and_pack.py` 一键更新并重打包，再上传新 zip 即可。

## 许可证

本仓库仅供学习和个人使用。上游曲目数据、别名和社区标签保留各自来源与权利归属。
