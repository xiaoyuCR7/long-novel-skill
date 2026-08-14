# long-novel-skill

通用网文创作 agent skill（长篇 + 短篇），**v7.0.0**。核心只装通用写作工艺（工作流 + 模板 + 禁区清单），
题材规则（34 题材 + 九件事正文层规范）与平台规则（长篇番茄/起点/晋江/飞卢 + 短篇知乎盐言/番茄短篇/七猫短篇）
做成可插拔的参考文件，按需加载。

v6.1 在 v6.0 基础上新增跨平台支持体系：MCP Server 封装（24 个 Tools 支持任何 MCP 客户端）、
跨平台安装脚本（install.sh/install.ps1 支持 Claude Code/TRAE/Cursor/Codex/OpenCode/Gemini CLI/Antigravity）、
skill.json 跨平台技能定义文件、TRAE Agent 部署路径适配。一次封装，全平台通用。

v6.0 在 v5.0 基础上新增 Beat Sheet 生成器、章节合成器、门禁修复计划、编辑团队状态管理器、自动化 Hook 机制、
RAG 检索增强六大核心脚本，并补齐共享工具模块（common.py + config.py）与核心脚本测试套件（744 个单元测试，默认全量验证），
新增拆文产出结构化分目录规范工艺文件，题材卡扩展至 34 张，新增：
Beat Sheet 生成器（分镜表自动拆分+五维扩写+合成校验）、
章节合成器（Beat 拼接+过渡检测+质量校验+润色提示）、
门禁修复计划（失败原因分析+修复策略映射+最短修复路径）、
编辑团队状态管理（快照/审核记录/状态查询/人工介入检测）、
自动化 Hook 机制（5 个 Hook：session-start/guard-outline/check-prose/detect-gaps/pre-compact）、
RAG 检索增强（BM25 两级+增量索引+查询缓存+轻场景跳过+命中可解释+写前上下文建议）、
共享模块（common.py 工具函数+config.py 配置常量）、
核心脚本测试套件（744 个单元测试覆盖 20 个脚本模块）。

v5.0 在 v4.1 基础上新增智能内容扩充引擎、长篇上下文管理器、统一流程执行器、质量评分系统四大量化工具体系，
补齐身体细节替代情绪词、特殊题材处理、题材公式、全流程质量检查清单四类工艺文档，全面超越两个开源 skill，新增：
语义级节奏审查（四维度：档位判断+配额语义核查+悬念质量+隐性加速检测）、
知识图谱（节点+边+版本+级联标记+Mermaid导出+影响分析）、
联网调研（题材维度映射+缺口检测+关键词生成+结构化存储）、
门禁产物规范（gate_result.json schema + 跨Agent消费接口）、
对话精通（7种决策路由+冲突递进五级+节奏控制+微动作配合）、
悬念分级（5级体系+多线周期+期待接力+信息释放节奏）、
信息团概念（定义+递进+排版+三层信息差）、
长篇情绪引擎（因果链+正向发动机+负向护栏+情绪模块八大类）、
爆款语料基准（句长/逗号比/对话占比/爽点密度/情绪转换频率）、
仿写工作流（拆文→提取→选风格→开书→魔改五步）、
章节元数据侧车（per-chapter meta.json schema）、
风格库跨书复用（import/search/apply/delete）、
命令入口表（30个命令+新手/高级分层）、
story_graph.py（知识图谱脚本）、
research_agent.py（联网调研脚本）、
style_library.py（风格库管理脚本）。

## 跨平台安装（v6.1 新增）

long-novel-skill 支持在多个 AI 客户端平台使用：Claude Code、TRAE、Cursor、OpenCode、Codex、Gemini CLI、Antigravity，以及任何支持 MCP 协议的客户端。

### 一键安装

**Linux/macOS (Bash):**
```bash
bash install.sh --tool all
```

**Windows (PowerShell):**
```powershell
.\install.ps1 -Tool all
```

安装脚本会自动检测已安装的 AI 客户端，并将 skill 复制到对应的 skills 目录。支持 `--tool` 指定单个平台，或 `--tool all` 安装到所有检测到的平台。

### 手动安装

| 平台 | 安装路径 | 命令 |
|------|---------|------|
| Claude Code | `~/.claude/skills/` | `cp -R long-novel-skill ~/.claude/skills/` |
| TRAE | `~/.trae/skills/` 或项目级 `.trae/skills/` | `cp -R long-novel-skill ~/.trae/skills/` |
| Cursor | `~/.cursor/skills/` | `cp -R long-novel-skill ~/.cursor/skills/` |
| OpenCode | `~/.opencode/skills/` | `cp -R long-novel-skill ~/.opencode/skills/` |
| Codex | `~/.codex/skills/` | `cp -R long-novel-skill ~/.codex/skills/` |

### MCP Server 模式（推荐）

任何支持 MCP 的客户端都可以通过 MCP Server 调用全部 26 个工具：

```bash
cd mcp_server
pip install mcp
python server.py
```

配置示例（Claude Desktop）:
```json
{
  "mcpServers": {
    "long_novel_skill": {
      "command": "python",
      "args": ["/path/to/long-novel-skill/mcp_server/server.py"]
    }
  }
}
```

详见 `mcp_server/README.md`。

### Agent 部署

编辑团队（策划主编/写作特工/反AI编辑/连载核实官）的 Agent 定义文件在 `assets/agents/`：

```bash
# Claude Code / OpenCode
cp assets/agents/*.md {书籍工程根}/.claude/agents/

# TRAE
cp assets/agents/*.md {书籍工程根}/.trae/agents/

# Codex（需转成 .toml 或内联扮演）
```

## 结构

```
long-novel-skill/
├── SKILL.md                  # 核心入口：触发条件、工作流总览、Iron Law、题材/平台加载协议
├── references/
│   ├── workflow/             # 工作流（v6.0 共 24 个）
│   │   ├── book-init.md          # 开书流程（长篇，对接 init_book.py）
│   │   ├── chapter-loop.md       # 单章写作循环
│   │   ├── outline-system.md     # 三级大纲 + 大纲锚点配额
│   │   ├── short-story-loop.md   # 短篇写作循环（五段式）
│   │   ├── beat-pipeline.md      # Beat Sheet 多步流水线
│   │   ├── deconstruct.md        # 拆文学习对标（轻量四维）
│   │   ├── deconstruct-pipeline.md  # 拆文七阶段工业管道
│   │   ├── deconstruct-output-spec.md  # 拆文产出结构化分目录规范（v6.0 新增）
│   │   ├── market-scan.md        # 扫榜选题（方法论）
│   │   ├── market-scan-deep.md   # 扫榜深度选题（选题四步+读者画像+决策报告）
│   │   ├── import-book.md        # 导入旧稿接手（概述）
│   │   ├── import-deep.md        # 导入旧稿深度逆向工程（10步+角色状态反推）
│   │   ├── daily-batch.md        # 日更批量模式
│   │   ├── daily-failfast.md     # 日更 fail-fast 五类资料检查
│   │   ├── auto-write.md         # 全自动写书调度（plan/run/report+断点续写）
│   │   ├── ideation.md           # 交互式脑洞引导（5轮收敛+压力测试）
│   │   ├── editorial-spawn.md    # 编辑团队 8 步 spawn 协议
│   │   ├── cross-review.md       # 跨 Agent 审核协议（路由表+三维度报告+批处理）
│   │   ├── research.md           # 联网调研工作流（v4.0 新增）
│   │   ├── imitation.md          # 仿写工作流（对标书→新书五步）（v4.0 新增）
│   │   ├── style-library.md      # 风格库跨书复用（v4.0 新增）
│   │   ├── commands.md           # 命令入口表（30个命令+新手/高级分层）（v4.0 新增）
│   │   ├── revision.md           # 大修流程
│   │   └── book-scaling.md       # 百万字结构展开
│   ├── craft/                # 通用写作工艺（v5.0 共 40 个；v6.3 增 short-story-ending.md → 44 个；v6.6 增 sensitive-word-replacement.md → 45 个）
│   │   ├── iron-law.md           # 七条铁律
│   │   ├── anti-ai-style.md      # 7 Gate 去AI腔（判定标准）
│   │   ├── deslop-engineering.md  # 去AI味工程化（量化分级+删除优先+比例上限+白名单+收敛终止）
│   │   ├── sensitive-word-replacement.md  # 敏感词替换（地名代称/别称置换/地名脱敏）
│   │   ├── pacing-and-hooks.md   # 节奏三档制 + A/B/C 配额
│   │   ├── pacing-review.md      # 语义级节奏审查（四维度）（v4.0 新增）
│   │   ├── reverse-brake.md      # 反向刹车 + 事件冷却
│   │   ├── reader-contract.md    # 读者契约（执行模板）
│   │   ├── reader-contract-deep.md  # 读者契约深度理论（因果权+结算权+终局储备+透支两问）
│   │   ├── emotional-arc.md      # 情绪弧线操作手册（六种弧线+情绪引擎+情绪模块八大类+长篇情绪引擎）
│   │   ├── character-design.md   # 角色设计操作手册（三层标签反差+九维人设）
│   │   ├── commercial-core.md    # 商业创作核心方法（卖点论+金手指原理+留存四支柱）
│   │   ├── outline-safety.md     # 大纲安全七检 + 可证伪降级检查
│   │   ├── plot-budget.md        # 情节点预算制（密/疏+字数求和校验）
│   │   ├── outline-structure-theory.md  # 深度结构理论（三级结构+五幕因果链+对标节奏迁移）
│   │   ├── style-fingerprint.md  # 文风指纹六维量化
│   │   ├── style-profile.md      # 文风协议（整书级视图+锚点片段+分层模仿+confidence）
│   │   ├── editorial-team.md    # 编辑团队协作（对接 assets/agents/）
│   │   ├── review-rubric.md      # 多视角盲评
│   │   ├── gate-artifacts-spec.md  # 门禁产物规范（schema + 跨Agent消费接口）（v4.0 新增）
│   │   ├── suspense-grading.md   # 悬念分级（5级体系+多线周期+期待接力）（v4.0 新增）
│   │   ├── information-cluster.md  # 信息团概念（定义+递进+排版+三层信息差）（v4.0 新增）
│   │   ├── corpus-baseline.md    # 爆款语料基准（句长/逗号比/对话占比/爽点密度）（v4.0 新增）
│   │   ├── chapter-meta.md       # 章节元数据侧车（per-chapter meta.json schema）（v4.0 新增）
│   │   ├── narrative-modules.md  # 叙事元素卡+结构技法卡+情绪模块公式（v4.1 新增）
│   │   ├── wit-battle.md         # 智斗构型三步两线法（v4.1 新增）
│   │   ├── adaptation-method.md  # 改编法+三重重复循环检测（v4.1 新增）
│   │   ├── writing-craft-extras.md  # 身体细节替代情绪词+ recurring props + 三维场景 + 开篇密度（v5.0 新增）
│   │   ├── plot-special-topics.md   # 特殊题材处理（时间跳越/多POV/群戏/闪回/蒙太奇）（v5.0 新增）
│   │   ├── genre-formulas.md        # 题材写作公式（打脸/升级/拉情绪/悬疑揭秘/日常装逼）（v5.0 新增）
│   │   └── quality-checklist.md     # 全流程质量检查清单（开书前/大纲/写前/写后/卷末/发布前）（v5.0 新增）
│   ├── genres/               # 题材包（可插拔，34 题材 + 九件事正文层规范）
│   │   ├── INDEX.md               # 路由 + 别名表 + 九件事说明
│   │   ├── GENRE-PROSE-SPEC.md   # 题材卡九件事正文层规范（v3.0 新增）
│   │   └── {题材}.md × 34          # 每题材一张卡（12栏目+九件事，逐步补齐）
│   └── platforms/            # 平台基线：长篇 + 短篇
├── assets/
│   ├── templates/            # 书籍工程模板（17 个）
│   ├── agents/               # 编辑团队可部署资产（4 个角色 + README）
│   └── style_library/        # 风格库（跨书复用）（v4.0 新增）
│       └── index.json         # 风格库索引
└── scripts/                  # 机械闸口与量化工具（纯标准库，无第三方依赖，共 39 个）
    ├── common.py                 # 共享工具函数（文件I/O+文本处理+章节解析）（v6.0 新增）
    ├── config.py                 # 全局配置常量（目录结构+文件名+BM25参数）（v6.0 新增）
    ├── check_text.py             # 7 Gate + 字数 + 禁用词 + 毒句式 + 伏笔超期 + 量化打分 + 7类AI模式检测 + --deslop分级 + --whitelist
    ├── style_fingerprint.py      # 文风指纹六维提取 + 漂移检测
    ├── rhythm_guard.py           # 节奏配额检查（A/B/C + 5+1类事件矩阵 + recommend/record）
    ├── event_matrix.py           # 事件矩阵调度器（5+1类+独立冷却+gentle_window）
    ├── entity_index.py           # BM25两级语义检索 + 实体索引 + 缓存 + 触发判定
    ├── deconstruct.py            # 拆文辅助（量化/结构/节奏/文风）
    ├── normalize_punct.py        # 标点归一化
    ├── init_book.py              # 一键初始化书籍工程骨架
    ├── resume.py                 # 会话恢复报告（欠账门机器查验）
    ├── validate_tracking.py      # 追踪文件格式校验
    ├── outline_anchor.py         # 大纲锚点动态约束注入 + 配额兼容检查
    ├── story_graph.py            # 知识图谱（节点+边+版本+级联标记+Mermaid导出）（v4.0 新增）
    ├── research_agent.py         # 联网调研（缺口检测+关键词生成+结构化存储）（v4.0 新增）
    ├── style_library.py          # 风格库管理（import/search/apply/delete）（v4.0 新增）
    ├── content_expander.py       # 智能内容扩充引擎（场景/对话/心理/动作/过渡五维策略）（v5.0 新增）
    ├── context_manager.py        # 长篇上下文管理器（最小上下文选取+预算分配+压缩）（v5.0 新增）
    ├── novel_flow.py             # 统一流程执行器（status/prepare/write/daily/revise/report）（v5.0 新增）
    ├── quality_score.py          # 质量评分系统（七维加权+趋势分析）（v5.0 新增）
    ├── beat_sheet_generator.py   # Beat Sheet分镜表生成器（generate/expand/validate）（v6.0 新增）
    ├── chapter_synthesizer.py    # 章节合成器（synthesize/check/polish）（v6.0 新增）
    ├── gate_repair.py            # 门禁修复计划生成器（失败原因分析+最短修复路径）（v6.0 新增）
    ├── editorial_manager.py      # 编辑团队状态管理器（snapshot/record-review/status/need-human）（v6.0 新增）
    ├── hooks.py                  # 自动化Hook机制（5个Hook）（v6.0 新增）
    ├── rag_retriever.py          # RAG检索增强（build/query/status）（v6.0 新增）
    └── tests/                    # 单元测试套件（744 测试覆盖 20 个模块，v7.0 起默认全量运行）（v6.0 新增，v6.2/v6.3 扩展）
        ├── run_tests.py              # 测试运行器
        ├── test_common.py            # common.py（36）
        ├── test_config.py            # config.py（14）
        ├── test_check_text.py        # check_text.py（23）
        ├── test_novel_flow.py        # novel_flow.py（16）
        ├── test_context_manager.py   # context_manager.py（15）
        ├── test_static_check.py      # static_check.py（19）
        ├── test_benchmark.py         # benchmark.py（16）
        ├── test_rhythm_guard.py      # rhythm_guard.py（18）
        ├── test_entity_index.py      # entity_index.py（16）
        └── test_outline_anchor.py    # outline_anchor.py（16）
```

## 核心能力（v6.1）

| 能力 | 一句话 | 依据 |
|---|---|---|
| 三级大纲 + 大纲锚点配额 | 总纲/卷纲/章纲三级，锚点配额防注水 | `workflow/outline-system.md` |
| 大纲安全七检 + 可证伪降级检查 | 七项定性检查 + 两项可证伪检查，大纲写完必审 | `craft/outline-safety.md` |
| 深度结构理论 | 三级结构选择 + 五幕因果链 + 对标节奏迁移1/4·中点·3/4 | `craft/outline-structure-theory.md` |
| 情节点预算制 | 密/疏三级 + 字数预算求和校验，防注水防过场 | `craft/plot-budget.md` |
| 单章写作循环 + 7 Gate 去AI腔 | 读上下文→写→闸口→追踪，7 道闸口去 AI 腔 | `workflow/chapter-loop.md`、`craft/anti-ai-style.md` |
| 去AI味工程化 | 量化六级分级 + 删除优先 + 比例上限 + 白名单 + 收敛终止 + 三遍法 | `craft/deslop-engineering.md` |
| **敏感词替换表**（v6.6 新增） | 开书必建：真实地名/机构/人物 → 全书代称，地名代称系统 + 别称置换规则 + 地名脱敏处理；必禁专名并入禁用词.txt 机器拦截 | `craft/sensitive-word-replacement.md`、`templates/sensitive-word-replacement.md` |
| Beat Sheet 多步流水线 | 一章拆 4–8 个 Beat 分镜写，末尾节奏预检 | `workflow/beat-pipeline.md`、`templates/beat-sheet.md` |
| 短篇五段式 | 短篇单篇情绪闭环结构 | `workflow/short-story-loop.md` |
| **短篇结尾句工艺** | 短篇默认必加：点睛句（正文最后一行，一句话）/ 彩蛋句（一句隐藏信息）/ 碎碎念（默认一句），一律简短 | `craft/short-story-ending.md`、`workflow/short-story-loop.md` Step 7 |
| 节奏三档制 + A/B/C 配额 + 事件矩阵5+1类 | 慢/中/快三档，6类事件独立冷却+gentle_window+recommend/record | `craft/pacing-and-hooks.md`、`craft/reverse-brake.md`、`scripts/event_matrix.py` |
| **语义级节奏审查**（v4.0 新增） | 四维度：档位判断+配额语义核查+悬念质量+隐性加速检测，脚本检测不到的由Claude兜底 | `craft/pacing-review.md` |
| 反向刹车 | 非终局章禁止解决主线核心矛盾 | `craft/reverse-brake.md` |
| 读者契约（执行模板 + 深度理论） | 因果权+结算权+终局储备+透支两问+风险三级 | `craft/reader-contract.md`、`craft/reader-contract-deep.md` |
| 情绪弧线操作手册（v4.0 升级） | 六种弧线 + 情绪引擎四冲程 + 情绪模块八大类 + 长篇情绪引擎因果链 | `craft/emotional-arc.md` |
| 角色设计操作手册 | 三层标签反差 + 九维人设 + 金手指绑架人设 | `craft/character-design.md` |
| 商业创作核心方法 | 卖点论 + 金手指原理 + 留存四支柱 + 崩盘预警 | `craft/commercial-core.md` |
| 文风指纹（六维量化）+ 文风协议（整书级视图） | 六维量化 + 锚点片段 + 分层模仿 + confidence | `craft/style-fingerprint.md`、`craft/style-profile.md` |
| **风格库跨书复用**（v4.0 新增） | import/search/apply/delete，多书写作时跨项目迁移风格 | `workflow/style-library.md`、`scripts/style_library.py` |
| 编辑团队协作（8步spawn协议） | 策划主编/写作特工/反AI编辑/连载核实官 + 完整生命周期 | `craft/editorial-team.md`、`workflow/editorial-spawn.md` |
| 多视角盲评 + 跨Agent审核 | 四视角盲评 + 路由表 + 三维度报告 + P0/P1/P2 + 批处理 + 防死循环 | `craft/review-rubric.md`、`workflow/cross-review.md` |
| 拆文（轻量四维 + 七阶段工业管道） | 四维统计 + 情绪模块卡 + 节奏权威索引 + 质量阈值 + 恢复机制 | `workflow/deconstruct.md`、`workflow/deconstruct-pipeline.md` |
| **仿写工作流**（v4.0 新增） | 对标书→拆文→提取→选风格→开书→魔改五步 | `workflow/imitation.md` |
| 扫榜选题（方法论 + 深度执行） | 选题四步 + 读者画像 + 选题决策报告 | `workflow/market-scan.md`、`workflow/market-scan-deep.md` |
| 导入旧稿（概述 + 深度10步） | 角色状态反推 + 增量导入 + 卷划分用户确认制 | `workflow/import-book.md`、`workflow/import-deep.md` |
| **联网调研**（v4.0 新增） | 题材维度映射+缺口检测+关键词生成+结构化存储 | `workflow/research.md`、`scripts/research_agent.py` |
| 全自动写书调度 | plan/run/report + 断点续写 + 自动暂停 | `workflow/auto-write.md` |
| 交互式脑洞引导 | 5轮收敛 + 压力测试 | `workflow/ideation.md` |
| 日更 fail-fast 五类资料检查 | 缺失必读资料即停止，输出修复动作 | `workflow/daily-failfast.md` |
| BM25两级语义检索 | 粗筛BM25 + 精排TF-IDF + 缓存 + 触发判定 + 命中可解释 | `scripts/entity_index.py` |
| **知识图谱**（v4.0 新增） | 节点+边+版本+级联标记+Mermaid导出+影响分析 | `scripts/story_graph.py` |
| **章节元数据侧车**（v4.0 新增） | per-chapter meta.json，统一消费方接口 | `craft/chapter-meta.md` |
| **门禁产物规范**（v4.0 新增） | gate_result.json schema + 跨Agent消费接口 | `craft/gate-artifacts-spec.md` |
| **对话精通**（v4.0 升级） | 7种决策路由+冲突递进五级+节奏控制+微动作配合 | `craft/dialogue.md` |
| **悬念分级**（v4.0 新增） | 5级体系+多线周期+期待接力+信息释放节奏 | `craft/suspense-grading.md` |
| **信息团概念**（v4.0 新增） | 定义+递进+排版+三层信息差 | `craft/information-cluster.md` |
| **爆款语料基准**（v4.0 新增） | 句长/逗号比/对话占比/爽点密度/情绪转换频率 | `craft/corpus-baseline.md` |
| **命令入口表**（v4.0 新增） | 30个命令+新手/高级分层 | `workflow/commands.md` |
| **叙事元素卡+结构技法卡+情绪模块公式**（v4.1 新增） | 10种叙事元素+9种结构技法+11个情绪公式 | `craft/narrative-modules.md` |
| **智斗构型三步两线法**（v4.1 新增） | 4种构型+三步构建+两线并行 | `craft/wit-battle.md` |
| **升级循环与多角度强化**（v4.1 新增） | 三级循环+五种强化角度+疲劳防护 | `workflow/book-scaling.md`（升级循环+多角度强章节） |
| **改编法+三重重复循环检测**（v4.1 新增） | 四步改编+情节/对话/情绪三重检测 | `craft/adaptation-method.md` |
| **智能内容扩充引擎**（v5.0 新增） | 场景/对话/心理/动作/过渡五维扩充策略+预算分配+压缩算法，解决章节过短问题 | `scripts/content_expander.py` |
| **长篇上下文管理器**（v5.0 新增） | 最小上下文选取+预算分配+压缩+组件化，解决百万字上下文爆炸 | `scripts/context_manager.py` |
| **统一流程执行器**（v5.0 新增） | status/prepare/write/daily/revise/report 六命令编排，串起分散工作流 | `scripts/novel_flow.py` |
| **质量评分系统**（v5.0 新增） | 七维加权评分（AI腔/节奏/文风/情感/结构/对话/可读性）+趋势分析 | `scripts/quality_score.py` |
| **全流程质量检查清单**（v5.0 新增） | 开书前/大纲/写前/写后/卷末/发布前六阶段检查清单 | `craft/quality-checklist.md` |
| **题材写作公式**（v5.0 新增） | 打脸/升级/拉情绪/悬疑揭秘/日常装逼五大题材公式 | `craft/genre-formulas.md` |
| **特殊题材处理**（v5.0 新增） | 时间跳越/多POV切换/群戏/闪回/蒙太奇五类特殊场景 | `craft/plot-special-topics.md` |
| **Beat Sheet 生成器**（v6.0 新增） | 分镜表自动拆分（3-7 Beat）+五维扩写提示+合成稿校验 | `scripts/beat_sheet_generator.py` |
| **章节合成器**（v6.0 新增） | Beat 拼接+过渡检测+字数/覆盖度/衔接/钩子/格式五维校验+润色提示 | `scripts/chapter_synthesizer.py` |
| **门禁修复计划**（v6.0 新增） | 失败原因分析+修复策略映射（禁用词替换+毒句式改写）+最短修复路径 | `scripts/gate_repair.py` |
| **编辑团队状态管理**（v6.0 新增） | 快照/审核记录/状态查询/人工介入检测（防死循环） | `scripts/editorial_manager.py` |
| **自动化 Hook 机制**（v6.0 新增） | 5 个 Hook：session-start/guard-outline/check-prose/detect-gaps/pre-compact | `scripts/hooks.py` |
| **RAG 检索增强**（v6.0 新增） | BM25 两级+增量索引+查询缓存+轻场景跳过+命中可解释+写前上下文建议 | `scripts/rag_retriever.py` |
| **共享模块**（v6.0 新增） | common.py 工具函数（I/O+文本+章节）+config.py 配置常量（目录+文件名+参数） | `scripts/common.py`、`scripts/config.py` |
| **核心脚本测试套件**（v6.0 新增，v6.2/v6.3 扩展） | 744 个单元测试覆盖 20 个脚本模块（默认全量运行） | `scripts/tests/run_tests.py` |
| 题材包可插拔（34题材 + 九件事） | 12栏目设定层 + 九件事正文层 | `genres/INDEX.md`、`genres/GENRE-PROSE-SPEC.md` |
| 平台适配（长篇+短篇） | 长篇番茄/起点/晋江/飞卢 + 短篇知乎盐言/番茄短篇/七猫短篇 | `platforms/platform-guide.md` |
| 一键开书骨架 | 一条命令建书籍工程目录 + 拷贝模板 | `scripts/init_book.py` |
| 会话恢复 / 欠账门 | 开工先跑一次，把「写到哪/欠什么账/下一章是什么」说清 | `scripts/resume.py` |
| 追踪格式校验 | 五个追踪文件的格式 schema 校验 | `scripts/validate_tracking.py` |
| 标点归一化 | 清理省略号/破折号/感叹堆叠等非功能性标点 | `scripts/normalize_punct.py` |
| 大纲锚点约束注入 | 每章写前生成「禁止揭露/必须达成/阶段定位」约束 | `scripts/outline_anchor.py` |
| 百万字结构展开 | 从一句话脑洞到 200-500 万字的可执行结构 | `workflow/book-scaling.md` |
| 日更批量模式 | 每次会话串行写 2-3 章，含退化防护与中途快照 | `workflow/daily-batch.md` |
| 格式排版硬约束 | 8 条绝对禁止 + 语气标点谱系 + 对话格式 + 平台差异表 | `craft/format-and-structure.md` |
| 跨书召回防污染 | 主一辅多 + 三道防线 + 预算控制 | `craft/cross-book-recall.md` |
| 异源审核降级 | L1 多模型/L2 多会话/L3 同会话三级降级 + 防死循环 | `craft/review-rubric.md` |
| 正文隔离 P0 触发器 | 6 类机器检测标记自动判定正文隔离违规 | `craft/editorial-team.md` |

## 安装

把本目录拷入你所用工具的 skills 目录，例如：

```bash
# Claude Code（用户级）
cp -R long-novel-skill ~/.claude/skills/

# Codex CLI / 通用路径
cp -R long-novel-skill ~/.agents/skills/
```

然后在对话中直接说「开书」「写第 X 章」「写一篇番茄短篇」等即可触发（skill 描述里带触发关键词）。

## 用法速览

1. **开书**：「开书：男频玄幻，发番茄」→
   先 `python scripts/init_book.py "{书名}" --genre 玄幻 --platform 番茄` 建骨架，
   再按 `workflow/book-init.md` 走完定位/契约/人物/**敏感词替换表（与世界观同步建，真实地名/机构/人物 → 全书代称）**/总纲/卷纲/章纲，
   落定读者契约与文风锚。
2. **写章**：「写第 37 章」→ 按 `workflow/chapter-loop.md` 走：
   先跑 `resume.py` 查欠账 → 读章纲 → 节奏预检 → 检索上下文（必要时 `entity_index.py query` / `context_manager.py select`） → 写正文 →
   内容扩充（必要时 `content_expander.py analyze`） → 标点归一化 → 三条机器闸口 → 质量评分（`quality_score.py score`） →
   自查清单 → 更新追踪五文件 → 跑 `validate_tracking.py` 复核 → 重建实体索引。
3. **写短篇**：「写一篇番茄短篇」→ 按 `workflow/short-story-loop.md` 走短篇五段式，
   定稿后**默认加结尾句**（简短，一句顶满），按 `craft/short-story-ending.md` 写点睛句/彩蛋句/碎碎念。
4. **拆文**：「拆解这本对标书」→ 按 `workflow/deconstruct.md` 走，产出存入 `对标/{书名}/`。
5. **扫榜**：「帮我扫榜看趋势」→ 按 `workflow/market-scan.md` 走，产出存入 `参考资料/扫榜报告.md`。
6. **带旧稿接手**：「我有几十章旧稿」→ `workflow/import-book.md`。
7. **查平台规则**：题材卡「平台适配要点」节 + `platforms/platform-guide.md`。

> Windows 提示：若系统里 `python3` 指向微软商店占位 stub（运行无输出），改用 `python` 调用脚本。

## 脚本说明

二十六个脚本均为纯标准库实现，无第三方依赖，Windows 兼容。退出码统一：0 通过 / 1 有命中或违规 / 2 参数错误。
脚本通过文件名约定与 `追踪/门禁/gate_chN.json`、`追踪/entity_index.json` 等约定路径互相协作，
不依赖任何 agent，是质量底线。

### 1. check_text.py — 7 Gate 机械闸口（v3.0 升级）

```bash
# 7 Gate 检测 + 字数 + 禁用词 + 毒句式 + 伏笔超期 + 量化打分 + 7类AI模式检测
python scripts/check_text.py "正文/第037章_标题.md" \
  --min-chars 2000 --max-chars 3500 \
  --ledger "追踪/伏笔台账.md" --current-chapter 37 --gate-report

# v3.0 新增：去AI味量化分级（六级打分 → 轻/中/重建议）
python scripts/check_text.py "正文/第037章_标题.md" --deslop

# v3.0 新增：白名单豁免词（设定/禁用词.txt 中 ! 前缀的词不检测）
python scripts/check_text.py "正文/第037章_标题.md" --whitelist "设定/禁用词.txt"
```

v3.0 新增 7 类段落级 AI 模式检测：微动作复读、抽象总结复读、套词密度、解释链密度、监控动作清单、引号强调滥用、工程词泄漏。

### 2. style_fingerprint.py — 文风指纹提取与漂移检测

```bash
# 从样章提取六维文风锚
python scripts/style_fingerprint.py extract "正文/第001章.md" "正文/第002章.md" \
  --output "设定/文风锚.md"

# 对比当前章节与文风锚
python scripts/style_fingerprint.py compare "正文/第037章.md" "设定/文风锚.md"
```

### 3. rhythm_guard.py — 节奏配额检查（v3.0 升级）

```bash
# 检查本章是否越界（A/B/C 配额 + 5+1类事件矩阵 + 事件冷却 + 档位分布）
python scripts/rhythm_guard.py \
  --chapter-file "正文/第037章.md" --quota "追踪/节奏配额.md"

# v3.0 新增：为下一章推荐事件类型
python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" --recommend "快"

# v3.0 新增：记录本章事件
python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" --record "conflict"

# 写章前预检声明
python scripts/rhythm_guard.py --quota "追踪/节奏配额.md" --declare "A,conflict,快"
```

v3.0 将事件类型从 A/B/C 三类扩展为 5+1 类：conflict(冲突爽点)/bond(人物羁绊)/faction(势力经营)/world(风土人情)/crisis(危机升级)/revelation(核心秘密)，每类有独立冷却章数和连续上限，新增 gentle_window（每5章至少1次bond或world）。A/B/C 配额向后兼容。

### 4. event_matrix.py — 事件矩阵调度器（v3.0 新增）

```bash
# 为下一章推荐事件类型分配（按档位推荐）
python scripts/event_matrix.py recommend "{书名目录}" --gear 快

# 记录本章事件类型，更新冷却状态
python scripts/event_matrix.py record "{书名目录}" --chapter 37 --event conflict

# 查看当前冷却状态和 gentle_window 进度
python scripts/event_matrix.py status "{书名目录}"
```

独立的事件矩阵调度器，数据持久化到 `追踪/event_matrix.json`。与 rhythm_guard.py 双向兼容。

### 5. entity_index.py — BM25 两级语义检索（v3.0 升级）

```bash
# 每章更新摘要后重建索引（或批量补建）
python scripts/entity_index.py build "{书名目录}"

# 写前检索某个实体出现在哪几章
python scripts/entity_index.py query "{书名目录}" 林雷 盘龙戒指

# v3.0 升级：BM25 两级语义检索（粗筛BM25取top-8 + 精排TF-IDF取top-4 + 缓存 + 命中可解释）
python scripts/entity_index.py semantic "{书名目录}" "林雷的战斗场景" "魔法试炼"
python scripts/entity_index.py semantic "{书名目录}" "与盘龙戒指有关的秘密" --top 5

# 顺带在正文里抓原文行
python scripts/entity_index.py query "{书名目录}" 林雷 --grep
```

v3.0 升级为 BM25 两级检索：粗筛用 BM25 评分（k1=1.5, b=0.75）取 top-8 candidate，精排用片段级 TF-IDF 取 top-4。新增查询缓存（`追踪/query_cache.json`）、轻场景触发判定（过场/赶路自动跳过全量检索）、命中原因可解释（输出匹配关键词和得分）、章节元数据读取（`追踪/chapter_meta/第XXX章.meta.json`）。

### 6. deconstruct.py — 拆文辅助

```bash
# 量化统计
python scripts/deconstruct.py stats "对标书/第1章.md" ... --output "对标/量化统计.md"

# 结构分析（钩子/对话/段落）
python scripts/deconstruct.py structure "对标书/第1章.md" ... --output "对标/结构分析.md"

# 节奏分析（快中慢档位 + 爽点位置）
python scripts/deconstruct.py rhythm "对标书/第1章.md" ... --output "对标/节奏分析.md"

# 文风指纹
python scripts/deconstruct.py fingerprint "对标书/第1章.md" ... --output "对标/文风指纹.md"
```

### 7. normalize_punct.py — 标点归一化

```bash
# 先 --check 看一眼，确认后去掉 --check 就地改写（写前自动留一份 .bak）
python scripts/normalize_punct.py "正文/第037章_标题.md" --check
python scripts/normalize_punct.py "正文/第037章_标题.md"

# 多文件批量预览
python scripts/normalize_punct.py a.md b.md --check
```

清理省略号 `……/…/。。。`、破折号 `——/—/--`、感叹/疑问堆叠 `!!!/???`、独立分隔线、
全角空格与行尾空白；引号字符本身不动（`「」`/`""` 原样保留）。让停顿用动作/短句/换行表达。

### 8. init_book.py — 一键初始化书籍工程

```bash
# 在当前目录下创建 {书名}/ 书籍工程骨架
python scripts/init_book.py "我的小说" --genre 玄幻 --platform 番茄

# 指定父目录；--force 重建缺失模板（不动 正文/ 与 大纲/）
python scripts/init_book.py "我的小说" --dir "D:/存放/小说" --force
```

按 `assets/templates/book-structure.md` 的布局创建 `大纲/ 正文/ 对标/ 参考资料/`、
`设定/`（含 `角色/`）、`追踪/`（含 `门禁/`），从 `assets/templates/` 拷贝五个追踪文件 +
三个设定文件模板，并轻量预填 `设定/题材定位.md`（书名/主题材/平台）。已有目录且非空时默认拒绝覆盖。

### 9. resume.py — 会话恢复 / 欠账门

```bash
# 每次开工先跑一次
python scripts/resume.py "{书名目录}"

# 机器可读（供编排工具消费）
python scripts/resume.py . --json
```

一次说清四件事：① 最新一章是第几章；② 该章门禁（`追踪/门禁/gate_chN.json`）是否通过、
正文过闸后是否被改动；③ 追踪文件是否同步（章节摘要/节奏配额有无该章条目、伏笔台账有无 🔴 超期）；
④ 下一章章纲是否就位。有欠账时退出码 1，报告里列出补账步骤。

### 10. validate_tracking.py — 追踪文件格式校验

```bash
# 校验整本书的五个追踪文件
python scripts/validate_tracking.py "{书名目录}"

# 只校验单个文件
python scripts/validate_tracking.py . --file "追踪/伏笔台账.md"
```

把五个追踪文件的约定格式变成可校验的 schema：伏笔台账四节齐备（🔴🟡🟢✅）+ ID 形如 `F1-03`；
节奏配额三节齐备（A/B/C 配额 / 事件冷却 / 档位）；章节摘要每个 `### 第N章` 含七个必填字段；
角色状态每个 `## 角色` 含四个必填字段；时间线表格列数 ≥4。每 10 章或新会话首次校验一次，
防止模型把格式写歪导致下游脚本静默漏检。

### 11. entity_index.py — BM25 两级语义检索 + 实体索引

（已在上文第 5 节详述）

### 12. outline_anchor.py — 大纲锚点动态约束注入

```bash
python scripts/outline_anchor.py inject "{书名目录}" --chapter 37
python scripts/outline_anchor.py check "{书名目录}" --chapter 37 --quota A
```

从章纲提取「禁止揭露/必须达成/阶段定位」三条约束，生成自然语言注入写前上下文；同时检查配额兼容性（本章声明的配额与近3章记录是否冲突）。

### 13. story_graph.py — 知识图谱（v4.0 新增）

```bash
python scripts/story_graph.py build "{书名目录}"
python scripts/story_graph.py query "{书名目录}" --node "主角" --depth 2
python scripts/story_graph.py cascade "{书名目录}" --from-chapter 50 --desc "改纲：加入新反派"
python scripts/story_graph.py update "{书名目录}" --chapter 37
```

从 `entity_index.json` + 章节摘要构建节点（角色/事件/地点/物品/势力），提取关系边，支持级联标记（改纲后标记受影响节点）。**v5.0 新增 `update` 子命令**：每章写完后增量更新（只从本章摘要提取新实体和关系追加到图谱），避免全量 rebuild 的代价。

### 14. research_agent.py — 联网调研（v4.0 新增）

```bash
python scripts/research_agent.py search "中世纪盔甲" --save "参考资料/盔甲调研.md"
python scripts/research_agent.py gap "参考资料/盔甲调研.md" --expected 5
```

调用搜索引擎做题材知识调研，输出结构化摘要、缺口检测报告、关键词生成。纯标准库实现（urllib + json）。

### 15. style_library.py — 风格库跨书复用（v4.0 新增）

```bash
python scripts/style_library.py import "{旧书目录}" --name "旧书A风格"
python scripts/style_library.py search --min-dialogue-ratio 30 --max-avg-sent 15
python scripts/style_library.py apply "{新书目录}" --style "旧书A风格"
python scripts/style_library.py delete --style "旧书A风格"
```

跨项目导入/搜索/应用/删除文风指纹，多书写作时迁移风格基线。

### 16. content_expander.py — 智能内容扩充引擎（v5.0 新增）

```bash
# 分析扩充潜力
python scripts/content_expander.py analyze "正文/第037章.md" --target 3500

# 生成扩充建议报告
python scripts/content_expander.py analyze "正文/第037章.md" --target 3500 --output "追踪/扩充建议_ch37.json"
```

五维扩充策略（场景扩充/对话丰富化/心理深化/动作细节/过渡平滑），智能分析文本各维度的扩充潜力，按优先级排序并估算可扩充字数。解决「章节过短」的量化扩充问题。

### 17. context_manager.py — 长篇上下文管理器（v5.0 新增）

```bash
# 选取目标章节的最小必读上下文
python scripts/context_manager.py select "{书名目录}" --chapter 37 --max-chars 4000

# 压缩多章摘要
python scripts/context_manager.py compress "{书名目录}" --from 30 --to 36 --max-chars 1000
```

组件化上下文选取（章纲/人物卡/近章摘要/伏笔台账/设定摘要），按预算比例分配各组件字数，解决百万字长篇的上下文爆炸问题。

### 18. novel_flow.py — 统一流程执行器（v5.0 新增）

```bash
# 诊断书籍工程状态
python scripts/novel_flow.py status "{书名目录}"

# 日更批量模式（串行执行 N 章）
python scripts/novel_flow.py daily "{书名目录}" --chapters 3

# 进度报告
python scripts/novel_flow.py report "{书名目录}"

# 改纲级联
python scripts/novel_flow.py revise "{书名目录}" --from-chapter 50 --desc "加入新反派"
```

编排分散工作流：status（诊断）→ prepare（写前准备）→ write（单章写作）→ daily（日更批量）→ revise（改纲级联）→ report（进度报告）。fail-fast 机制：检查不过不继续下一章。

### 19. quality_score.py — 质量评分系统（v5.0 新增）

```bash
# 评分单章（Markdown 报告）
python scripts/quality_score.py score "正文/第037章.md" --chapter 37 --book-dir "." --markdown

# 多章趋势分析
python scripts/quality_score.py trend --book-dir "." --from 30 --to 40 --markdown
```

七维加权评分（AI腔控制 20% / 节奏控制 15% / 文风一致性 15% / 情感冲击力 15% / 结构完整性 15% / 对话质量 10% / 可读性 10%），总分 0-100 分，A/B/C/D/F 五级。评分结果落盘 `追踪/质量评分/quality_ch{N}.json`，支持趋势分析。

### 20. beat_sheet_generator.py — Beat Sheet 分镜表生成器（v6.0 新增）

```bash
# 从章纲生成 Beat Sheet（按场景/情绪转折拆分为 3-7 个 Beat）
python scripts/beat_sheet_generator.py generate "{书名目录}" --chapter 37

# 为指定 Beat 生成五维扩写提示（角色/场景/情绪/动作/对话）
python scripts/beat_sheet_generator.py expand "{书名目录}" --chapter 37 --beat 2

# 校验合成稿（Beat 覆盖度/字数分布/情绪曲线连贯性）
python scripts/beat_sheet_generator.py validate "{书名目录}" --chapter 37 --manuscript "正文/第037章_标题.md"
```

将复杂章节拆解为多个 Beat（节拍），每个 Beat 是独立叙事单元。配合 `workflow/beat-pipeline.md` 工作流，解决 AI 单次生成长章节时压缩剧情、跳过细节的问题。Beat Sheet 产出存入 `追踪/beat_sheets/beat_ch{N}.json`；expand 产出五维扩写提示直接输出到终端；validate 产出校验报告并更新 Beat Sheet 的 validation 字段。

### 21. chapter_synthesizer.py — 章节合成器（v6.0 新增）

```bash
# 拼接 Beat 片段为完整章节，检测衔接
python scripts/chapter_synthesizer.py synthesize "{书名目录}" --chapter 37

# 合成稿五维校验（字数/覆盖度/衔接/钩子/格式）
python scripts/chapter_synthesizer.py check "{书名目录}" --chapter 37 --manuscript "正文/第037章_标题.md"

# 生成 Beat 边界过渡润色提示
python scripts/chapter_synthesizer.py polish "{书名目录}" --chapter 37
```

将 Beat Sheet 流水线产出的多个 Beat 片段合成为完整章节，对应 `workflow/beat-pipeline.md` 的 Step 4。synthesize 按序拼接并检测 Beat 间衔接；check 做字数/覆盖度/衔接/钩子/格式五维校验输出报告 JSON；polish 识别 Beat 边界生成过渡润色提示（Markdown）。

### 22. gate_repair.py — 门禁修复计划生成器（v6.0 新增）

```bash
# 读取门禁报告生成最短修复路径
python scripts/gate_repair.py "{书名目录}" --chapter 37

# 指定门禁报告路径
python scripts/gate_repair.py "{书名目录}" --chapter 37 --gate-report "追踪/门禁/gate_ch37.json"

# 输出 Markdown 修复计划
python scripts/gate_repair.py "{书名目录}" --chapter 37 --markdown
```

当章节门禁检查失败时，自动分析失败原因并生成最短修复路径：读取门禁报告 → 按严重度分类（blocking/advisory）→ 为每个 blocking 问题生成修复建议（内置禁用词替换表 + 毒句式改写方向）→ 生成最短修复路径（优先修复高影响问题，合并相关问题）→ 输出 `追踪/门禁/repair_plan_ch{N}.md`。

### 23. editorial_manager.py — 编辑团队状态管理器（v6.0 新增）

```bash
# 生成上下文快照 JSON（供编辑团队启动）
python scripts/editorial_manager.py snapshot "{书名目录}" --chapter 37

# 记录单次审核结果
python scripts/editorial_manager.py record-review "{书名目录}" --chapter 37 --stage final --agent consistency-reviewer --verdict pass --p0 0 --p1 2 --p2 1

# 查看最近 N 章审核历史（表格格式）
python scripts/editorial_manager.py status "{书名目录}" --last 10

# 检测是否需要人工介入（防死循环）
python scripts/editorial_manager.py need-human "{书名目录}"
```

管理多 Agent 协作写作流程的状态。snapshot 生成编辑团队启动上下文快照；record-review 追加审核结果到 `review_history.json`；status 输出表格格式状态报告；need-human 检测防死循环（单章返工上限 2 次、连续条件通过 3 章强制人工介入）。对应 `workflow/editorial-spawn.md` 的 Step 1 与 Step 7。

### 24. hooks.py — 自动化 Hook 机制（v6.0 新增）

```bash
# 会话开始时显示进度快照
python scripts/hooks.py session-start "{书名目录}"

# 写正文前检查大纲是否存在
python scripts/hooks.py guard-outline "{书名目录}" --chapter 37

# 正文写入后轻量扫描（毒句式+元信息泄漏）
python scripts/hooks.py check-prose "正文/第037章_标题.md" --book-dir "{书名目录}"

# 检测设定缺口
python scripts/hooks.py detect-gaps "{书名目录}"

# 上下文压缩前保存进度快照
python scripts/hooks.py pre-compact "{书名目录}"
```

五个自动化 Hook，适配本 skill 四目录文件结构（正文/大纲/追踪/设定）：session-start（进度快照）、guard-outline（大纲存在性校验）、check-prose（正文轻量扫描，含毒句式 + 元信息泄漏）、detect-gaps（设定缺口检测）、pre-compact（压缩前快照）。

**机械部署（v7.0 新增，Claude Code）**：hooks.py 的上述子命令原靠模型自觉调用，v7.0 起提供平台级机械强制——`hook_entry.py`（事件分发器）+ `deploy_hooks.py`（settings.json 注册器）：

```bash
# 在书籍工程目录内执行，把 4 类 hook 注册进 .claude/settings.json（幂等，自动备份）
python scripts/deploy_hooks.py "{书名目录}"

# 卸载
python scripts/deploy_hooks.py "{书名目录}" --uninstall
```

注册后，PreToolUse 在「无章纲写正文」时平台级阻断（exit 2），PostToolUse 在「毒句式欠账未清」时阻断，SessionStart/PreCompact 自动做进度/压缩前快照。全程 fail-open（Python/脚本缺失、无法定位书目录时静默放行），正文文件含 `<!-- lns:skip -->` 时跳过检查。多书切换可用 `LNS_BOOK_DIR` 环境变量或项目根 `.active-book` 指定活跃书。

### 25. rag_retriever.py — RAG 检索增强（v6.0 新增）

```bash
# 构建章节级 RAG 索引（章节号/标题/摘要/实体/字数/情绪）
python scripts/rag_retriever.py build "{书名目录}"

# 两级 BM25+TF-IDF 检索 + 写前上下文建议
python scripts/rag_retriever.py query "{书名目录}" "林雷的战斗场景" --top 4

# 轻场景跳过全量检索（赶路/过场自动跳过）
python scripts/rag_retriever.py query "{书名目录}" "赶路过场" --light

# 索引状态（覆盖率/最后更新/缓存命中率）
python scripts/rag_retriever.py status "{书名目录}"
```

基于 `entity_index.py` 的 BM25 检索能力增强，侧重语义级相关章节检索。build 构建章节级 RAG 索引；query 两级 BM25+TF-IDF 检索输出可解释结果 + 写前上下文建议（`next_plot_context.md`），轻场景触发判定（赶路/过场自动跳过全量检索），查询缓存 + 命中可解释；status 输出索引覆盖率与缓存命中率。与 entity_index.py 互补使用。

### 26. common.py — 共享工具函数（v6.0 新增）

```python
from common import read_text, write_text, count_chinese_chars, parse_chapter_number, find_book_dir
```

所有脚本共享的工具函数集合：文件 I/O（read_text/write_text/read_json/write_json）、文本处理（count_chinese_chars/split_paragraphs/normalize_whitespace/truncate_text）、章节解析（parse_chapter_number/find_book_dir）等。集中管理通用逻辑，减少重复代码，默认 utf-8-sig 编码兼容 BOM。

### 27. config.py — 全局配置常量（v6.0 新增）

```python
from config import SKILL_VERSION, BOOK_DIRS, TRACKING_FILES, SETTING_FILES
```

全局配置常量集中管理：SKILL_VERSION/SKILL_NAME、书籍工程目录结构（BOOK_DIRS）、追踪/设定文件名（TRACKING_FILES/SETTING_FILES）、章节命名格式、BM25 参数等。修改一处即全局生效，避免散落在各脚本中的魔法数字。

## 测试套件（scripts/tests/，v6.0 新增）

`scripts/tests/` 是核心脚本的单元测试套件，纯标准库（unittest）。**744 个测试覆盖 20 个脚本模块**（默认全量运行，CI 流水线 5 个 Python 版本 × 3 平台验证）：

- `test_common.py`（36）— common.py 共享工具函数
- `test_config.py`（14）— config.py 配置常量
- `test_check_text.py`（23）— check_text.py 7 Gate 闸口
- `test_novel_flow.py`（16）— novel_flow.py 写作流程编排
- `test_context_manager.py`（15）— context_manager.py 上下文管理
- `test_static_check.py`（19）— static_check.py 静态代码质量
- `test_benchmark.py`（16）— benchmark.py 性能基准
- `test_rhythm_guard.py`（18）— rhythm_guard.py 节奏配额
- `test_entity_index.py`（16）— entity_index.py 实体索引
- `test_outline_anchor.py`（16）— outline_anchor.py 大纲锚点

```bash
# 运行全部测试
python scripts/tests/run_tests.py

# 运行指定模块
python scripts/tests/run_tests.py test_common test_check_text
```

`run_tests.py` 是测试运行器，输出形如 `test_common.py ............... 36/36 通过` 的进度行，末尾汇总 `总计：744/744 通过`。退出码 0 全通过 / 1 有失败 / 2 参数错误。

## 编辑团队（assets/agents/，v2.1 新增）

`references/craft/editorial-team.md` 是方法论，`assets/agents/` 是让它真正跑起来的四个
agent 定义文件 + 部署/降级/防死循环协议。

- `planning-editor.md`：策划主编，读章纲/人物卡/追踪文件，产出 Chapter Brief。
- `novelist.md`：写作特工，只接收 Brief，只输出 `NOVEL_TEXT_START...NOVEL_TEXT_END` 之间的纯正文。
- `anti-ai-editor.md`：反AI编辑，对正文执行 7 Gate 检测 + 两遍式润色，输出报告 + 净化后正文。
- `consistency-reviewer.md`：连载核实官，核查事实冲突/伏笔断线/角色属性一致性，输出 S1–S4 报告。

部署方式、模型分级建议、Fallback 链（缺 agent → 主会话内联扮演 → 单 Agent 循环，机器闸口永远可用）、
防死循环协议（单章返工上限 2 次、连续 3 章有条件通过强制人工介入）见 `assets/agents/README.md`。
日常日更走单 Agent 循环，关键章（卷末高潮/大反转/上架前）才启用团队。

## 扩展新题材

复制 `references/genres/` 下任一题材卡的栏目骨架（12 个固定栏目 + 九件事正文层规范），
撰写新卡，把别名登记进 `references/genres/INDEX.md` 即可，核心 skill 不用动。
九件事规范详见 `references/genres/GENRE-PROSE-SPEC.md`。

## provenance

- maintainer: 熊小雨
- version: 7.0.0
- created: 2026-07-26
- last_reviewed: 2026-08-10
- review_interval_days: 90
- source_references:
  - skills/novel-creator-skill（借鉴五层一致性/Beat Sheet/节奏配额/语义级节奏审查/知识图谱/联网调研/风格库设计，未引用内容）
  - skills/oh-story-claudecode（借鉴7 Gate/拆文/扫榜/短篇/对话精通/悬念分级/信息团/爆款语料设计，未引用内容）
