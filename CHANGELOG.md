# CHANGELOG

## v6.8.0 (2026-08-10)

### 章节衔接工艺（新增功能，章间无缝连接）
把「上一章结尾 + 下一章开头」当作一个独立设计单位（**咬合面**），系统化消除章间割裂感：

- 新增 `craft/chapter-junction.md`：章间因果链（直接/延迟/并列三型 + 因果链三问 + 前情触发补环）、
  四类过渡元素（悬念延续 / 线索承接 / 场景自然转换 / 情绪过渡）、章间四拍对位（章 N 钩子 =
  章 N+1 承接的引信；结算残账做天然衔接）、动机连贯（第一动作定律 / 动机断点检测）、
  呼应前文与预示后续（章首回声 / 细节回扣密度）、割裂感五病诊断（重新定位 / 时间线断裂 /
  情绪断崖 / 因果缺环 / 动机突转）+ 衔接自检 9 条。
- `workflow/chapter-loop.md`：Step 4 结构四拍挂接衔接工艺；Step 6 检查清单新增章间衔接项
  （15-19：钩子兑现时效 / 线索簿三查与场景转换三问 / 情绪过渡 / 动机链 / 呼应预示）；
  Step 7 章节摘要「承上/启下」两栏改为**必填**（衔接设计记录 + 断更恢复依据）。
- `craft/hooks.md`：章首纪律挂接衔接工艺（钩子招式库 ↔ 咬合面方法论）。
- `craft/chapter-meta.md`：causal_chain 的 `from_previous`/`to_next` 挂接衔接工艺，与摘要「承上/启下」一致。
- SKILL.md 文件地图新增「章间衔接」行，能力清单同步。
- 版本号统一升级至 6.8.0。

### 测试
- 仅文档工艺新增 + 流程集成，无脚本改动；version_sync 四文件版本一致。

---

## v6.7.0 (2026-08-09)

### 长篇单章字数联网核验修正（数据校正）
联网核验 2025-2026 主流平台单章字数现实，修正 skill 内陈旧/不合理的单章字数约束：

- `craft/corpus-baseline.md`：**起点中文网单章 3000-4000 字 → 2000-3000 字**（签约下限 2000、平均约 2500，原数据偏长）；同步修正 check_text 门禁示例、档位表、爽点密度引用、快速对照表（起点 2000-3000 ±200，警告 <1800 或 >3200）。新增飞卢行（上架前 1500-2000 / 上架后 2000-5000）。
- `workflow/book-scaling.md`：单章字数范围 **2500-4500 → 2000-4500**（默认 3000 不变），并修正规模参数互锁（每卷章数 60→100、总卷数 8→10、总章数 800→1000，满足「每卷字数 = 每卷章数 × 单章字数」）。
- `platforms/platform-guide.md`：番茄单章 2000-3000 → 2000-2500，起点 2000-4000 → 2000-3000（大章 4000）；新增飞卢平台要点（快更、分阶段章长）。
- `craft/commercial-core.md`：平台适配表章长列同步。
- `scripts/config.py`：短篇默认区间 3000-15000 → **4000-30000**，与 v6.5 文档闸口对齐（原为过时遗留值）。
- 机器闸口 `hooks.py` / `novel_flow.py` 单章下限 2000 维持不变（与各平台签约/推荐下限一致）。

### 测试
- 实际运行 189/189 通过

---

## v6.6.0 (2026-08-08)

### 敏感词替换表（新增功能，长篇开书必建）
长篇开书流程新增敏感词处理文档：正文写作前（世界观/人物卡建立后）建 `设定/敏感词替换表.md`，
把真实地名/机构/人物/事件 → 全书统一虚构代称。三件套：**地名代称系统**（真实地名→代称一行一映射）、
**别称置换规则**（机构/职务/群体→固定置换词）、**地名脱敏处理方法**（模糊化/架空化/时间脱敏）。

- 新增 `templates/sensitive-word-replacement.md`：每书一张表的母版（五节：地名代称/别称置换/脱敏处理/题材敏感点/平台红线备忘）
- 新增 `craft/sensitive-word-replacement.md`：方法论（八条造代称纪律 + 写作期执行 + 机器核对 + 与禁用词.txt 分工）
- `init_book.py` 开书自动拷贝骨架表；`book-init.md` Step 2 与世界观同步建表；`chapter-loop.md` 写前检索 + 写中约束 + 自查清单第 14 项
- 必禁真实专名并入 `设定/禁用词.txt` 可由 `check_text.py` 机器拦截（与去 AI 腔禁用词分开管理）
- 涉及文件：`SKILL.md`、`README.md`、`skill.json`、`scripts/init_book.py`、`scripts/config.py`、`assets/templates/book-structure.md`、`workflow/book-init.md`、`workflow/chapter-loop.md`、`workflow/commands.md`
- Demo 项目补 `设定/敏感词替换表.md` 实测样例
- 版本号统一升级至 6.6.0

### 测试
- 189/189 测试通过

---

## v6.5.0 (2026-08-08)

### 短篇字数区间检查（新增功能）
联网核验 2025-2026 平台投稿现状，修正三平台短篇字数约束（旧数据已过时）：

| 平台 | 旧值 | 新值（联网核验） |
|---|---|---|
| 知乎盐言 | 1–3 万字 | 8000 字起投，1–2 万字最佳 |
| 番茄短篇 | 3000–1 万字 | 6000 字起（签约门槛），1–3 万字，1.5 万–3 万最易过签 |
| 七猫短篇 | 5000–2 万字 | 4000 字起（后台满 4000 可签），投稿 1–3 万字 |

- 通用短篇区间：5000–20000 → **4000–30000 字**；`short-story-loop.md` Step 6 闸口命令同步（`--min-chars 4000 --max-chars 30000`）
- Step 6 精修新增第 3 项检查：「字数是否在目标平台范围内」，超出区间按五段式比例删
- 涉及文件：`workflow/short-story-loop.md`、`platforms/platform-guide.md`、`platforms/short-submission.md`、`workflow/commands.md`
- 版本号统一升级至 6.5.0

### 测试
- 189/189 测试通过

---

## v6.4.0 (2026-08-03)

### 短篇结尾句工艺（新增功能）
- 新增 `craft/short-story-ending.md`：三类结尾句创作方法论——点睛句（正文最后一行，情绪最后一击）、彩蛋句（正文外一句隐藏信息）、碎碎念（作者文后话）
- **结尾句为短篇默认必加步骤**，且要求简短：点睛句 ≤1 句（30 字内）、彩蛋句 1 句、碎碎念默认 1 句最多 2 句
- `short-story-loop.md` 新增 Step 7（默认必做），与「结尾不升华」铁律协调（点睛句不是总结句）
- `commands.md` 新增「写短篇」「结尾句」命令入口
- SKILL.md/skill.json 触发词补充：结尾句/点睛句/彩蛋/碎碎念
- 版本号统一升级至 6.4.0

### 测试
- 189/189 测试通过

---

## v6.3.0 (2026-07-30)

### 架构优化
- **统一检索系统**：合并 `entity_index.py` + `rag_retriever.py` → `retrieval.py`，消除 ~400 行重复 BM25 代码，统一索引文件
- **统一事件系统**：合并 `rhythm_guard.py` + `event_matrix.py` → `event_system.py`，事件类型+冷却值单一定义，消除两处硬编码
- **版本号统一**：skill.json/SKILL.md/README.md/config.py 全部同步至 6.3.0
- **AI 阈值修复**：check_text.py 从 config.py 导入 `AI_SCORE_THRESHOLDS`，消除硬编码不同步 bug
- **CLI 增强**：novel-cli.py 新增 10 个子命令（prepare/track/daily/report/revise/rollback/unlock/snapshots/retrieval/event）
- **version_sync.py**：CI 用版本号一致性检查
- **.gitignore**：排除 `__pycache__/`, `*.pyc`

### 消除冗余
- 脚本数：33→31（合并 4→2，增 1）
- MCP tool 预计：26→24
- 删除 `mcp_server/__pycache__/` 已提交产物

### 测试
- 189/189 测试通过，耗时 1.0s

---

## v6.2.0 (2026-07-30)
- 章节入口模式与人格推荐器（8 种入口 + 3 种人格）
- check_text.py v3.2：20 种 AI 写作模式检测
- anti_resolution_guard.py：6 种速决模式 + 冷却期
- content_expander.py v2.0：8 策略扩充
- ranking_crawler.py：3 平台 9 榜单爬虫
- CI/CD 自动化流水线（3 个 GitHub Actions）
- 真实 Demo 项目（5 章完整样例）
- 测试：CI 默认 189 例（10 核心脚本，5 Python 版本 × 3 平台验证），全量 744 例（20 脚本模块）

## v6.1.0 (2026-07-29)
- 跨平台支持：MCP Server 26 Tools、install.sh/install.ps1
- 工程增强：config.py 环境变量覆盖、novel_flow.py 幂等回滚
- 质量保障：static_check.py、benchmark.py、check_text.py v3.1
- 知识图谱：story_graph.py extract 命令
- 测试：109→189 例
