# CHANGELOG

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
