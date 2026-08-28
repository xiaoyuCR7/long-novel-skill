# assets/agents — 多 Agent 定义与协作协议

本目录是「编辑团队」的可部署资产。`references/craft/editorial-team.md` 是方法论，
本目录是让它真正跑起来的四个 agent 定义文件 + 部署/降级/防死循环协议。

## 文件清单

| 文件 | 角色 | 职责一句话 |
|---|---|---|
| `planning-editor.md` | 策划主编 | 读章纲/人物卡/追踪文件，产出 Chapter Brief 传给写作特工 |
| `novelist.md` | 写作特工 | 完整 Brief 生成候选正文，输入无效则 BLOCKED，不伪装正文 |
| `anti-ai-editor.md` | 反AI编辑 | 对正文执行 7 Gate 检测 + 两遍式润色，输出报告 + 净化后正文 |
| `consistency-reviewer.md` | 连载核实官 | 核查事实冲突/伏笔断线/角色属性一致性，输出 S1–S4 报告 |

每个 `.md` 文件带 frontmatter（`name:`/`description:`），可被 Claude Code / OpenCode
等支持项目级 agents 的工具直接加载；Codex CLI 需转成 `.toml`
（`name`/`description`/`developer_instructions` 三字段），或由主会话按文件内容内联扮演（solo 模式）。

## 部署

把四个 `.md` 文件拷入目标环境的项目级 agents 目录：

```bash
# Claude Code / OpenCode（项目级）
cp assets/agents/*.md {书籍工程根}/.claude/agents/

# TRAE（项目级）
cp assets/agents/*.md {书籍工程根}/.trae/agents/

# Codex CLI 需转成 .toml（name/description/developer_instructions 三字段），
# 或直接由主会话按本目录文件内容内联扮演（solo 模式）。
```

部署后新开会话，由主 Agent（总编辑）在编辑团队流程中按 `editorial-team.md`
的 spawn 协议调用。

**部署不等于输入就绪**：四角色文件内保留必需字段与渲染规则，整章生产/审核调用仍须实际传入完整
Chapter Brief 与来源内容。只给 `chapter-intent.json` 或场景规则的链接不算交付，目标工程可能
根本没有技能目录。Brief 字段唯一来源为 `assets/templates/chapter-intent.json`；总编辑将已填
章意图、required 来源和场景渲染规则内容一并内联/附入，不假设 Agent 共享主会话上下文。
required 缺失/截断或预算不足就停止；outline_underfilled 必须带 missing_beat_budget，
不得把待补充 Brief 派给写作角色。成功正文标记与 BLOCKED 协议互斥。

例外仅限 `anti-ai-editor.md` 的片段模式：用户只给片段要求措辞润色、不要求整章验收或正式
文件修改时，可凭原文工作，不要求完整 Brief。保留事实和情绪/动机反应桥，不补造未知背景，
标明仅片段范围、未完成整章核查；不修改正式正文、不 commit。整章/团队任务不得据此降级放行。

## 共同事务与结尾契约

需要正式正文落盘的新章、修订（含一句话小改）、团队与 Beat，都由总编辑复用 `scripts/chapter_transaction.py`：
prepare → stage 候选正文/五表 → validate → 真实语义自查确认 → commit。
实际命令见 `references/workflow/chapter-loop.md`，旧章沿用 prepare 输出文件名。
stage 只人工改本章正文与五表；章意图、Beat、报告、修复计数放在 stage 与正式工程之外的
工作目录。必须改纲/设定时在 prepare 前完成；prepare 后才发现则先 recover 再按授权重开。
validate 只核对机器门禁、追踪、索引与哈希，不读取语义报告；主 Agent 真实自查通过才能
使用 `--self-review-confirmed`，不能先改正式正文后验收。

ending_mode 为 serial/closed/finale。closed/finale 的 hook_question 为空，兑现闭合要求，
不强行制造下章悬念/预告；finale 不把配额事件推给不存在的后续章。首章无上章钩子可 N/A。
反 AI 编辑保留反应、态度、互动功能；场景可合并/交织 beats，不机械一拍一段。

## 模型分级建议（成本与质量平衡）

| Agent | 建议档位 | 理由 |
|---|---|---|
| planning-editor | 高（旗舰/Opus 级） | Chapter Brief 质量决定本章上限，值得用好模型 |
| novelist | 高（旗舰/Opus 级） | 正文质量是核心产出 |
| anti-ai-editor | 中（Sonnet 级） | 7 Gate 是模式识别活，中档足够 |
| consistency-reviewer | 低（Haiku 级） | 一致性核查是比对活，便宜模型即可，还能省出每章都查的成本 |

## Fallback 链（spawn 前必查）

按以下顺序判定，**任何一级不满足就降级，不强行 spawn**：

1. 检查项目 agents 目录（`.claude/agents/` → `.trae/agents/` → `.opencode/agents/` → `.codex/agents/`）：
   对应文件存在且 frontmatter 的 `name:` 与目标 agent 一致 → 可用。
2. 任一 agent 缺失/文件损坏 → 该角色降级为「主会话内联扮演」
   （用对应 .md 文件的内容作为 prompt 切换视角），报告中注明 `Fallback: missing {agent} -> solo`。
3. spawn 调用本身失败 → 同样降级 solo，注明 `Fallback: spawn failed -> solo`。
4. 全部 agent 不可用时，整个编辑团队流程退化为 `chapter-loop.md` 单 Agent 循环，
   机器闸口（`check_text.py` + `rhythm_guard.py`）不依赖角色部署；脚本本身不可用则报告
   `tool_unavailable` 并保留待审草稿，不得假称已通过或手工覆盖正式文件。

## 防死循环协议（总编辑必须执行）

多轮审核最危险的失控是「改了审、审了改」无限循环。硬规则：

1. **单章返工上限 2 次**：任何 blocking/P0 最多自动定向修两轮；第 2 轮仍失败 →
   `gate_blocked`，保留 checkpoint 与 pending draft，不再自动改、不提交、不写下一章。
2. **不重置或降级放行**：同一章同一任务跨团队、Beat、模型、solo、会话和重新 prepare
   共享已用次数，记录在工作报告里交接；不得把 P0 写成“有条件通过”或 advisory。
3. **审核仅随证据更新**：不因不喜欢报告无限重审；改稿后复核受影响问题，最终自查对应
   当前候选。额度耗尽转作者裁决，不追加自动改写轮次。
4. **budget 提醒**：编辑团队流程 token 消耗约为单 Agent 循环的 3–4 倍，
   日常日更走单 Agent 循环，关键章（卷末高潮/大反转/上架前）才启用团队。

## 与脚本的协作（v2.1）

编辑团队不取代机器闸口，而是与 `scripts/` 下的工具协同。团队流程的关键节点都对接了脚本：

| 流程节点 | 用哪个脚本 | 作用 |
|---|---|---|
| 团队启动前确认无欠账 | `scripts/resume.py "{书}"` | 欠账未清禁止启动团队写新章（铁律第 1 条） |
| 确认上一章门禁已清 | `scripts/check_text.py {章} --verify-prev` | 上一章门禁未过则不开新章 |
| 7 Gate 检测（反AI编辑可调用） | `scripts/check_text.py {章} --gate-report` | 机器查七类，agent 看报告定性 |
| 节奏配额检查 | `scripts/rhythm_guard.py --chapter-file {章} --quota {配额}` | 越界/冷却违规机器先报 |
| 标点诊断（stage 候选） | `scripts/normalize_punct.py {章} --check` | 只按命中修候选，不生成事务外 .bak |
| 追踪五文件回写后校验 | `scripts/validate_tracking.py "{书}"` | 防 agent 把追踪格式写歪，让下游脚本静默漏检 |
| 重建实体索引 | `scripts/entity_index.py build "{书}"` | 让下一章的策划主编能查实体定位章节 |
| 文风漂移检测（可选） | `scripts/style_fingerprint.py compare {章} {文风锚}` | anti-ai-editor 判断腔调是否漂移的量化依据 |

**机器闸口是底线，agent 是增量**：`check_text.py` + `rhythm_guard.py` 任何时候都能跑，
不依赖 agent 是否部署；`anti-ai-editor` 与 `consistency-reviewer` 是在机器闸口之上
加一层语义判断（情绪展示是否到位、伏笔回收细节是否对得上埋设细节等）。

## 开书与恢复的对接

- **新建书籍工程**用 `scripts/init_book.py "{书名}" --genre {} --platform {}` 一键建骨架，
  agents 部署到生成出来的 `{书名}/.claude/agents/`（或对应工具目录）。
- **会话恢复**用 `scripts/resume.py "{书}"` 在团队流程开始前确认无欠账，
  退出码 1（有欠账）时不启动团队，先补账。

## 状态查询

主会话可以用 `scripts/resume.py {书}` 在团队流程开始前确认无欠账；
用 `scripts/check_text.py {章} --verify-prev` 确认上一章门禁已清——
欠账未清时禁止启动团队写新章（铁律第 1 条）。

## 模型分层体系（v2.1 新增）

### 分层定义

| 分层 | 代号 | 代表模型 | 定位 |
|---|---|---|---|
| 旗舰层 | T0 | Claude Opus 4 / GPT-4o | 最强推理，用于复杂规划与预算计算 |
| 主力层 | T1 | Claude Sonnet 4 / GPT-4o-mini | 创意生成+模式匹配，质量与成本平衡 |
| 效率层 | T2 | Claude Haiku / GPT-4o-mini | 规则检查+事实核查，高吞吐低成本 |

### 各 Agent 分层配置

| Agent | 推荐模型 | 分层 | 分层理由 |
|---|---|---|---|
| planning-editor | claude-opus-4-20250514 | T0 | 章纲规划、情节点预算计算、节奏配额核查需要复杂多步推理和数值计算 |
| novelist | claude-sonnet-4-20250514 | T1 | 创意生成和文风控制，不需要旗舰级推理，T1 在创意质量和成本间最佳平衡 |
| anti-ai-editor | claude-sonnet-4-20250514 | T1 | 模式识别和文本改写，对语言理解有较高要求但不需要旗舰级推理 |
| consistency-reviewer | claude-haiku-4-20250514 | T2 | 规则检查和事实核查为主，不涉及创意生成，T2 即可胜任 |

### 降级协议

- 当推荐模型不可用时，可降级到下一层模型（T0 -> T1 -> T2）
- 降级后需增加人工复核步骤
- blocking/P0 仍然阻断，不得因降级变为 advisory，也不重置两轮修复额度
- T2 Agent 不建议降级到更低层（已是最低）
- 如 T2 不可用，建议暂停编辑团队流程，改为单 Agent 模式

### 与已有「模型分级建议」的关系

上文的「模型分级建议」是初始概览；本节是正式的分层体系定义。
各 Agent `.md` 文件的 frontmatter 中包含 `recommended_model` 和 `model_tier`
两个字段，可被部署工具直接读取。两节信息一致，本节作为集中参考。
