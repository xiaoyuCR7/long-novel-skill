# 编辑团队 Spawn 协议（editorial-spawn）

定义编辑团队从快照到关闭的完整 8 步生命周期，以及四角色 Agent 的 spawn 规则、并行编排、
SendMessage/TeamDelete 生命周期管理、防死循环、降级协议、状态持久化。角色人设定义见
`assets/agents/`（含 `README.md` 与四个角色 `.md` 文件），方法论见
`references/craft/editorial-team.md`。**本文档只管「怎么把这四个 Agent 编排跑起来」，
不管角色本身怎么定义。**

## 何时用这个

- 卷末大高潮章 / 关键转折反转章 / 上架签约前的重要章节。
- 作者主动要求「双审」「团队写这章」。
- 单章门禁连续 2 次失败（单 Agent 循环兜不住，需要团队介入）。
- `auto-write.md` 托管模式遇到关键章（托管调度器自动切换到团队模式）。

日常日更不启用，走 `chapter-loop.md` 单 Agent 循环即可——团队流程的 token 消耗约为
单 Agent 的 3–4 倍（见 `assets/agents/README.md` 模型分级建议）。

## 与现有文档的关系

| 文档 | 管什么 | 与本文档的关系 |
|---|---|---|
| `assets/agents/README.md` | 角色定义、部署方式、模型分级、Fallback 链、防死循环 | 定义「角色是谁」，本文档定义「怎么编排」 |
| `references/craft/editorial-team.md` | 团队方法论、Chapter Brief 模板、正文隔离协议 | 定义「为什么这么分工」，本文档定义「怎么跑」 |
| `references/workflow/chapter-loop.md` | 单章写作循环 Step 0–8 | 团队模式替代 Step 1–6，Step 0/7/8 不变 |
| `references/craft/review-rubric.md` | 卷级多视角盲评 | 卷级评审用盲评，单章生产用本文档 |
| `references/workflow/cross-review.md` | 章级跨 Agent 审核 | 出厂后抽检，与本文档的生产时内审互补 |

## 8 步 Spawn 协议

完整生命周期：快照 → 创建团队 → 分派任务 → 写作 → 并行审核 → 汇总判定 → 记录 → 关闭。

```
Step1 快照 → Step2 创建团队 → Step3 分派任务 → Step4 写作
                                              ↓
Step8 关闭 ← Step7 记录 ← Step6 汇总判定 ← Step5 并行审核
```

### Step 1：快照（上下文快照）

**目的**：生成本章上下文快照，供 spawn 的子 Agent 读取，避免子 Agent 直接访问完整工程目录。

**前置检查**（铁律第 1 条，不可跳过）：

```bash
python scripts/resume.py "{书名}" --json
```

`resume.py --json` 输出 JSON 格式的上下文快照，包含：
- 上一章门禁状态（通过/未通过/有条件通过）
- 追踪文件同步状态（五个文件是否都回写到最新章）
- 伏笔台账 🔴 超期项清单
- 下一章章纲是否就位

`resume.py` 退出码 1（有欠账）→ 不进入 Step 2，先补账。欠账类型与补账方式：
- 上一章门禁未通过 → 走 `chapter-loop.md` Step 4–7 返工。
- 追踪文件未同步 → 补回写五文件 + `validate_tracking.py`。
- 伏笔 🔴 超期 → 先处理超期伏笔（回收/延期/废弃），再开新章。

**快照落盘**：快照 JSON 写入 `追踪/editorial_state.json` 的 `snapshot` 字段，供后续步骤引用。

### Step 2：创建团队（声明四角色）

**目的**：声明本轮编辑团队的四角色定义，初始化本轮状态。

**四角色声明**（从 `assets/agents/` 读取角色定义）：

| 角色 | 定义文件 | 职责 | 模型建议 |
|---|---|---|---|
| 策划主编（planning-editor） | `assets/agents/planning-editor.md` | 读章纲+对标节奏 → 产出 Chapter Brief | 高（旗舰级） |
| 写作特工（novelist） | `assets/agents/novelist.md` | 按 Brief 写纯正文 | 高（旗舰级） |
| 反AI编辑（anti-ai-editor） | `assets/agents/anti-ai-editor.md` | 7 Gate 检测 + 两遍式润色 | 中（Sonnet 级） |
| 连载核实官（consistency-reviewer） | `assets/agents/consistency-reviewer.md` | 事实冲突/伏笔断线/角色一致性核查 | 低（Haiku 级） |

**部署检查**：按 `assets/agents/README.md` 的 Fallback 链检查每个角色是否可 spawn：
1. 检查项目 agents 目录（`.claude/agents/` → `.opencode/agents/` → `.codex/agents/`）。
2. 对应 `.md` 文件存在且 frontmatter `name:` 匹配 → 可 spawn。
3. 文件缺失/损坏 → 该角色降级为「主会话内联扮演」。

**初始化本轮状态**：写入 `追踪/editorial_state.json`：

```json
{
  "chapter": 37,
  "team_start": "2026-07-28T14:00:00",
  "mode": "L1",
  "agents": {
    "planning-editor": { "status": "pending", "spawn": true },
    "novelist": { "status": "pending", "spawn": true },
    "anti-ai-editor": { "status": "pending", "spawn": true },
    "consistency-reviewer": { "status": "pending", "spawn": true }
  },
  "rewrite_round": 0,
  "result": null
}
```

### Step 3：分派任务（策划主编产出 Chapter Brief）

**目的**：策划主编读取章纲和对标节奏，产出 Chapter Brief，传给写作特工。

**策划主编输入**（SendMessage 传递）：
- 本章章纲（`大纲/章纲_第{NNN}章.md`）
- 出场人物卡（`设定/角色/{名}.md`）× 出场人数
- 近 5–10 章摘要（`追踪/章节摘要.md`）
- 伏笔台账活跃项（`追踪/伏笔台账.md` 的 🟡 + 🔴）
- 节奏配额记录（`追踪/节奏配额.md` 近 3 章）
- 大纲锚点约束（`scripts/outline_anchor.py inject` 的输出）
- 对标节奏（`对标/{书名}/节奏.md`，如有）

**SendMessage 格式**（主 Agent → 策划主编）：

```
[TO: planning-editor]
你是策划主编。读取以下资料，产出第 {N} 章的 Chapter Brief。

章纲：{粘贴章纲}
人物卡：{粘贴出场人物卡}
近章摘要：{粘贴近5-10章摘要}
伏笔台账（活跃项）：{粘贴🟡+🔴项}
节奏配额：{粘贴近3章记录}
大纲锚点约束：{粘贴 inject 输出}

按 editorial-team.md 的 Chapter Brief 模板产出。
```

**策划主编输出**：Chapter Brief（格式见 `references/craft/editorial-team.md` 的模板）。

**状态更新**：`editorial_state.json` 的 `planning-editor.status` → `done`。

### Step 4：写作（写作特工按 Brief 写正文）

**目的**：写作特工只接收 Chapter Brief，输出纯正文，严格隔离 meta 信息。

**写作特工输入**（SendMessage 传递，只给 Brief，不给其他上下文）：

```
[TO: novelist]
你是小说写作特工。只输出纯正文，不输出任何分析、说明、meta信息。

接收 Chapter Brief：
[CHAPTER_BRIEF]
{粘贴完整 Brief}
[/CHAPTER_BRIEF]

规则：
1. 只输出 NOVEL_TEXT_START 到 NOVEL_TEXT_END 之间的纯小说正文
2. 正文中不得出现 [说明]、（注：）、TODO、大纲语言
3. 按章纲情节点清单写，字数在预算内
4. 结构四拍齐全：承接→发展→结算→钩子
5. 对话遮住名字能认出谁说的
6. 设定挂在动作/冲突/细节上，不成段讲解
```

**写作特工输出**：`NOVEL_TEXT_START...NOVEL_TEXT_END` 标记内的纯正文。

**输出隔离检查**（P0 触发器，写作特工输出后立即检查）：
- 标记外有多余内容 → P0，重写。
- 正文含 `[说明]`/`TODO`/大纲语言 → P0，重写。
- 字数偏差 >20% → P0，重写。
- 连续 3 段以上「他/她」开头句式雷同 → P0（AI 腔信号），重写。

P0 触发 → 不进入 Step 5，直接回 Step 4 重写（计入返工轮次）。

**状态更新**：`editorial_state.json` 的 `novelist.status` → `done`，记录 `word_count` 和
`output_clean`。

### Step 5：并行审核（反AI编辑 + 连载核实官）

**目的**：写作特工产出纯正文后，反AI编辑和连载核实官并行审查，互不依赖。

**并行规则**：

```
         写作特工产出的纯正文
              │
         ┌────┴────┐
         ▼         ▼
    反AI编辑    连载核实官（并行）
         │         │
         └────┬────┘
              ▼ 两份报告
         Step 6 汇总判定
```

**SendMessage：写作特工 → 反AI编辑**：

```
[TO: anti-ai-editor]
你是反AI编辑。对以下正文执行 7 Gate 检测 + 两遍式润色。

正文：
[NOVEL_TEXT]
{粘贴纯正文}
[/NOVEL_TEXT]

机器闸口报告（参考底稿）：
{粘贴 check_text.py --gate-report 输出}

文风锚：{粘贴 设定/文风锚.md 的量化基线部分}
禁用词表：{粘贴 设定/禁用词.txt}

输出：
1. 7 Gate 审查报告（P0/P1/P2 分级 + 具体段落）
2. AI 味分数（1-10）
3. 润色后正文（只改 AI 腔，不改情节）
```

**SendMessage：写作特工 → 连载核实官**：

```
[TO: consistency-reviewer]
你是连载核实官。核查以下正文的一致性。

正文：
[NOVEL_TEXT]
{粘贴纯正文}
[/NOVEL_TEXT]

角色状态：{粘贴 追踪/角色状态.md}
伏笔台账：{粘贴 追踪/伏笔台账.md}
时间线：{粘贴 追踪/时间线.md}
出场人物卡：{粘贴相关角色卡}

输出 S1-S4 核查报告：
S1：角色地理位置与状态文件一致性
S2：角色能力边界未违反
S3：已死亡/离开角色未复活（非回忆/幻觉）
S4：伏笔操作与台账一致（该埋的埋了、该收的收了）
每项标注 pass/fail + 具体问题。
```

**并行超时**：如果一个角色 5 分钟无输出（子 Agent 卡死），不等了，用已有的单份
报告做降级裁决，状态标注 `{agent} timeout, degraded verdict`。

**状态更新**：两个角色的 `status` → `done`，记录各自的 P0/P1/P2 计数和详情。

### Step 6：汇总判定（总编辑裁决）

**目的**：收集两个审核角色的报告，判定通过/返工/需人工。

**裁决规则**：

| 判定 | 条件 | 后续动作 |
|---|---|---|
| 通过 | 无 P0，无 P1 | 用润色版正文，进 Step 7 |
| 有条件通过 | 无 P0，有未解决 P1 | 用润色版正文，P1 记入日志，进 Step 7 |
| 返工 | 有 P0 | 写作特工重写，回 Step 4（计入返工轮次） |
| 需人工 | 返工达上限/角色报告矛盾/Brief与章纲冲突 | 停止，进 Step 7 记录后等人工 |

**P0 判定标准**：
- 反AI编辑报告 P0：禁用词/毒句式/正文污染/字数偏差 >20%。
- 连载核实官报告 P0：死角色复活/主线矛盾/时间线错乱/伏笔台账不一致。
- 正文出现 `[说明]`/`TODO`/分析性段落（正文隔离 P0 触发器，见 `editorial-team.md`）。

**P1 判定标准**：
- 反AI编辑报告 P1：节奏断裂/人设偏差/钩子缺失。
- 连载核实官报告 P1：角色位置逻辑可疑/能力边界擦边。

**防死循环检查**（返工时）：
- 返工轮次 < 2 → 回 Step 4 重写。
- 返工轮次 = 2（第 3 次仍有 P0）→ 强制人工，不再重写。
- 连续 3 章「有条件通过」→ 强制人工，说明系统性问题。

**状态更新**：`editorial_state.json` 的 `result` 字段写入裁决结果（`pass` /
`conditional_pass` / `rewrite` / `human_needed`）。

### Step 7：记录（审核结果落盘）

**目的**：把本轮审核结果记入持久化文件，供跨章分析和断点恢复。

**落盘文件**：`追踪/门禁/editorial_review_ch{XXX}.json`

```json
{
  "chapter": 37,
  "round": 1,
  "team_start": "2026-07-28T14:00:00",
  "team_end": "2026-07-28T14:45:00",
  "mode": "L1",
  "planning-editor": {
    "status": "done",
    "brief_generated": true
  },
  "novelist": {
    "status": "done",
    "word_count": 3150,
    "output_clean": true
  },
  "anti-ai-editor": {
    "status": "done",
    "p0": 1,
    "p1": 2,
    "p2": 3,
    "ai_score": 3.2,
    "details": ["Gate B: 否定翻转句式 x1", "Gate C: 心理告知 x2"]
  },
  "consistency-reviewer": {
    "status": "done",
    "p0": 0,
    "p1": 1,
    "p2": 2,
    "s1_pass": true,
    "s2_pass": true,
    "s3_pass": false,
    "s4_pass": true,
    "details": ["S3: 角色位置逻辑可疑——主角从A城到B城无交代"]
  },
  "verdict": "rewrite",
  "rewrite_reason": "P0: Gate B 毒句式",
  "rewrite_round": 0,
  "result": "rewrite"
}
```

**日志用途**：
- **跨章分析**：连续多章的 P0/P1 分布趋势，识别系统性问题。
- **返工溯源**：某章被多次返工，查看每轮的具体问题和改法。
- **Fallback 追踪**：哪些角色经常降级 solo，是否需要修复 agents 部署。
- **成本核算**：统计团队模式的实际 token 消耗，优化使用频率。

**更新 `editorial_state.json`**：把本轮最终结果同步到状态文件，供断点恢复使用。

### Step 8：关闭（清理临时上下文）

**目的**：本章流程结束后，清理团队状态，让总编辑回到单 Agent 模式。

**关闭动作**（TeamDelete）：
1. 本轮记录的 `result` 字段写入最终结果（`pass` / `conditional_pass` / `human_needed`）。
2. `team_end` 时间戳写入 `editorial_state.json`。
3. 如果使用了 spawn 的子 Agent，确保子 Agent 会话已结束（不残留后台进程）。
4. 释放本章占用的上下文（团队模式上下文膨胀快，一章结束后及时清理）。
5. `editorial_state.json` 的 `status` 标记为 `closed`。

**TeamDelete 不是删除日志文件**——`editorial_review_ch{XXX}.json` 是永久记录，每章每轮
都保留。TeamDelete 是结束本轮编排状态，让总编辑回到单 Agent 模式。

**关闭后衔接**：
- 结果为 `pass` 或 `conditional_pass` → 走 `chapter-loop.md` Step 7（更新追踪五文件）+
  Step 8（向作者报告）。
- 结果为 `human_needed` → 向作者报告争议点，等待人工裁决。

## SendMessage / TeamDelete 生命周期管理

### SendMessage 上下文传递

角色之间通过结构化消息传递，不共享上下文。每条 SendMessage 包含：
- `[TO: {角色}]`：目标角色
- 消息体：结构化内容（章纲/正文/报告等）
- `[END]`：消息结束标记

**上下文隔离原则**：
- 策划主编的上下文（章纲/人物卡/摘要）不传给写作特工——写作特工只收 Brief。
- 写作特工的上下文（只有 Brief）不传给审核角色——审核角色只收纯正文 + 各自需要的参考文件。
- 反AI编辑和连载核实官互不知道对方的报告——各自独立审查，由总编辑汇总。

### TeamDelete 生命周期

```
TeamCreate（Step 2） → Agent spawn × 4 → SendMessage 传递 → 汇总判定 → TeamDelete（Step 8）
```

- **TeamCreate**：Step 2 声明四角色，初始化 `editorial_state.json`。
- **Agent spawn**：按需 spawn，不是一次性全 spawn。策划主编先 spawn，产出 Brief 后才
  spawn 写作特工；写作特工产出正文后才并行 spawn 两个审核角色。
- **TeamDelete**：Step 8 关闭。关闭后 `editorial_state.json` 标记 `closed`，子 Agent 会话
  结束，临时上下文清理。

**异常处理**：如果 Step 1–7 中途因崩溃/超时中断，`editorial_state.json` 的 `status` 会
停留在非 `closed` 状态。下次进入时检测到未关闭的团队 → 询问用户「上一轮团队流程未正常
结束，是否恢复？」→ 恢复则从断点 Step 继续，不恢复则强制 TeamDelete 后重新开始。

## 防死循环机制

多轮审核最危险的失控是「改了审、审了改」无限循环。三条硬规则：

### 规则1：单章返工上限 2 次

```
MAX_P0_REWRITE_ROUNDS = 2
```

- 第 1 轮 P0 → 写作特工重写，反AI编辑 + 连载核实官重审（完整重跑，不只查上轮的 P0 项）。
- 第 2 轮 P0 → 写作特工再重写，重审。
- 第 3 轮仍有 P0 → 停止，触发人工介入（Step 6 判定 `human_needed`）。

返工时不换策划主编（Brief 没问题就不重新生成），只让写作特工重写。如果 Brief 本身
有问题（情节点逻辑不通导致怎么写都过不了门禁），策划主编重新生成 Brief，返工轮次
清零重新计。

### 规则2：连续 3 章条件通过 → 强制人工

```
MAX_CONDITIONAL_CHAPTERS = 3
```

「条件通过」= 无 P0 但有未解决的 P1。连续 3 章条件通过说明系统性问题（多半是纲或
设定的问题，不是单章写作问题）：
- 可能是章纲的情节点设计有问题（每章都差点意思）。
- 可能是人设的动机线没理清（角色行为总是差点说服力）。
- 可能是节奏配额的分配不合理（A/B/C 配额卡太死或太松）。

触发后暂停团队模式，向作者汇报根因分析，走 `revision.md` 或 `outline-system.md`
的改纲流程修正。

### 规则3：审核不迭代

反AI编辑与连载核实官每章每轮各跑一次，不因为「报告不满意」让同一角色重审同一章。
分歧由总编辑裁决，不靠「再审一遍碰运气」。

### 规则4：状态持久化防丢失

所有返工轮次、条件通过计数、角色状态都写入 `追踪/editorial_state.json`。会话中断后
靠状态文件恢复，不靠对话记忆。

## 降级协议

子 Agent 不可用时的降级策略，与 `references/craft/editorial-team.md` 的 Fallback 链衔接：

### L1：4 角色全部可用

**条件**：四个角色文件都在 + spawn 可用。
**执行方式**：全部子 Agent spawn，完整 8 步流程。
**日志标注**：`mode: L1`（full_team）
**可靠性**：最高——上下文完全隔离，无污染风险。

### L2：合并审核角色

**条件**：spawn 可用但角色数不足（如只有 3 个 Agent 槽位）。
**执行方式**：策划主编和写作特工仍各自 spawn（串行隔离不能省）；反AI编辑 + 连载核实官
合并为一个角色（审核官），同一个子 Agent 先跑 7 Gate 再跑一致性核查。
**日志标注**：`mode: L2`（merged_reviewer）
**可靠性**：高——写作隔离仍在，审核维度合并但检查项不减少。
**注意**：合并后审核角色不能并行了，Step 5 从并行变串行，耗时增加。

### L3：单 Agent 串行执行

**条件**：spawn 不可用 / 无 agents 目录。
**执行方式**：主会话按 `editorial-team.md` 的检查清单手动执行，四个角色全由主会话
切换视角串行执行。
**日志标注**：`mode: L3`（all_solo）
**可靠性**：中——上下文隔离靠视角切换声明，有污染风险。
**执行顺序**：
1. 主会话切换到策划主编 prompt → 生成 Brief。
2. 主会话切换到写作特工 prompt → 写正文（清空上一角色的上下文，防污染）。
3. 主会话切换到反AI编辑 prompt → 7 Gate 审查。
4. 主会话切换到连载核实官 prompt → 一致性核查。
5. 主会话回到总编辑视角 → 汇总裁决。

**L3 模式下的纪律**：
- 角色切换时要显式声明「现在切换到 {角色} 视角」，避免主会话把多个角色的思路混在一起
  （这是正文污染的主要来源之一）。
- 机器闸口（`check_text.py` + `rhythm_guard.py`）永远跑——机器闸口不依赖任何 Agent，
  是质量底线（见 `assets/agents/README.md`）。

### 降级原则

- L1 > L2 > L3 逐级降级，不跳级。
- 降级不跳过质量：无论哪一级，机器闸口永远跑。
- 降级透明：任何降级都在日志和最终报告中标注，作者有权知道这章是不是「完整团队」产出的。
- L3 降级产出的章，门禁标「有条件通过」，下次有机会做 L1/L2 时可复审。

## 状态持久化

### `追踪/editorial_state.json`

当前章的团队流程状态，每步更新。结构：

```json
{
  "chapter": 37,
  "status": "closed",
  "team_start": "2026-07-28T14:00:00",
  "team_end": "2026-07-28T14:45:00",
  "mode": "L1",
  "snapshot": { "from": "resume.py --json", "debt": false },
  "agents": {
    "planning-editor": { "status": "done", "spawn": true, "round": 0 },
    "novelist": { "status": "done", "spawn": true, "round": 1, "word_count": 3150 },
    "anti-ai-editor": { "status": "done", "spawn": true, "p0": 0, "p1": 2, "p2": 3 },
    "consistency-reviewer": { "status": "done", "spawn": true, "p0": 0, "p1": 1, "p2": 2 }
  },
  "rewrite_round": 1,
  "consecutive_conditional": 0,
  "result": "conditional_pass"
}
```

**字段说明**：
- `status`：`pending` / `active` / `closed` —— 标记本轮生命周期。
- `mode`：L1/L2/L3 —— 降级级别。
- `snapshot`：Step 1 的快照引用。
- `agents`：每角色的状态、spawn 方式、审核计数。
- `rewrite_round`：当前返工轮次（0=首写，1=第一次返工，2=第二次返工）。
- `consecutive_conditional`：连续条件通过章数（跨章累计，达 3 触发人工）。
- `result`：`pass` / `conditional_pass` / `human_needed` / `closed`。

### `追踪/门禁/editorial_review_ch{XXX}.json`

每章的永久审核记录（Step 7 落盘），不因 TeamDelete 而删除。结构见 Step 7 的示例。

### 日志查询

写新章前可以查近期日志，了解上一章的审核情况：

```bash
# 查看最近5章的团队审核记录
# 关注：有没有连续条件通过、有没有经常 P0 的 Gate 类型
```

如果上一章是「条件通过」，本章的策划主编 Brief 要特别注意上章未解决的 P1 项，
在 Brief 里针对性规避。

## 与 chapter-loop.md 的衔接

团队模式替代 `chapter-loop.md` 的 Step 1–6（读章纲 → 检索 → 速记 → 写正文 →
机器闸口 → 自查），Step 0/7/8 不变：

| chapter-loop Step | 团队模式对应 |
|---|---|
| Step 0 欠账门 | Step 1 快照（resume.py 前置检查） |
| Step 1 读章纲 | Step 3 策划主编读章纲（含在 Brief 生成中） |
| Step 2 检索 | Step 3 策划主编检索（含在 Brief 生成中） |
| Step 3 压速记 | Step 3 策划主编产出 Brief（速记的升级版） |
| Step 4 写正文 | Step 4 写作特工写正文 |
| Step 5 机器闸口 | Step 5 反AI编辑 + 连载核实官（机器闸口作为参考输入） |
| Step 6 自查清单 | Step 6 总编辑汇总裁决（替代人工自查） |
| Step 7 更新追踪 | 不变（团队流程结束后仍要更新五文件 + validate + entity_index） |
| Step 8 向作者报告 | 不变（团队流程的报告含审核结论） |

## 与 assets/agents/README.md 的关系

`assets/agents/README.md` 是角色定义文档——定义四个角色是谁、怎么部署、模型分级建议、
Fallback 链。本文档是 spawn 协议——定义怎么把这四个角色编排跑起来。

| 文档 | 管什么 |
|---|---|
| `assets/agents/README.md` | 角色定义、部署方式、模型分级、Fallback 链 |
| `editorial-spawn.md`（本文件） | 8 步 spawn 协议、SendMessage/TeamDelete 生命周期、防死循环、状态持久化 |
| `references/craft/editorial-team.md` | 团队方法论、Chapter Brief 模板、正文隔离协议 |

三份文档各管一层：README.md 管「角色是谁」，editorial-team.md 管「为什么这么分工」，
本文件管「怎么跑」。

## 团队纪律

- **角色不越权**：写作特工不改情节，反AI编辑不改情节只改 AI 腔，连载核实官不改正文
  只出报告。情节变更必须经总编辑裁决，涉及主线的经作者确认（铁律第 6 条）。
- **上下文隔离**：写作特工只收 Brief，不收其他角色的分析——防止审核意见污染正文。
- **日志必记**：每步每个角色的状态都要写入 `editorial_state.json` 和
  `editorial_review_ch{XXX}.json`，不依赖对话记忆。会话中断后靠日志恢复，不靠「我还记得」。
- **Fallback 透明**：任何角色降级 solo 都要在日志和最终报告中标注，作者有权知道
  这章是不是「完整团队」产出的。
- **budget 提醒**：团队流程 token 消耗约为单 Agent 循环的 3–4 倍。每章团队流程结束后
  报告 token 用量，连续 5 章团队模式后提醒作者「是否切回单 Agent 循环」（日常章不需要团队）。
