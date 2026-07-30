# 全自动写书调度（auto-write）

托管模式：把「写 N 章」整件事交给调度器，自动完成从会话恢复到进度报告的全流程。
单章逻辑完全不变（仍走 `chapter-loop.md` 的 Step 0–8），本文件只管「多章自动调度的
状态机、断点续写、幂等缓存、门禁熔断、进度报告」。

## 何时用这个

- 用户说「托管写完」「自动日更」「帮我连续写 N 章」「睡一觉起来写 10 章」
- 适用前提：书籍工程已开书（`book-init.md` 走完），章纲已排到目标章号之后至少
  5 章（滚动补纲，见 `outline-system.md`）。
- 不适用：开书首章、卷末大高潮、关键转折章——这些质量优先于数量，走单章
  `chapter-loop.md` 或 `beat-pipeline.md`，不进托管。

## 与 daily-batch.md 的关系

| 关注点 | daily-batch.md | auto-write.md |
|---|---|---|
| 触发方式 | 人工触发，每轮 2–3 章 | 托管触发，连续写 N 章 |
| 会话边界 | 单会话内完成 | 跨会话（断点续写） |
| 状态持久化 | 无（会话内串行） | 有（state.json + cache.json） |
| 进度报告 | 批末一次 | 每 5 章一次 + 终止报告 |
| 熔断机制 | 无（人工判断） | 门禁连续 3 章未通过自动停 |
| 人工介入 | 每章都向作者报告 | 仅熔断/终止时通知 |

简单说：`daily-batch` 是「人在边上盯着的批量」，`auto-write` 是「人去睡觉的托管」。
托管期间调度器代替人做「要不要继续写下一章」的决策，但不代替人做「改主线/改设定」
的决策（遇到这类需求会停下来等人工）。

## 三阶段调度

托管模式分 plan / run / report 三个阶段，每个阶段有明确的输入、输出和持久化文件。
状态机的 PLANNING 态对应 plan 阶段，WRITING+GATE+TRACKING 态对应 run 阶段，
REPORTING 态对应 report 阶段。

### plan 阶段（计划）

**输入**：简介/总纲（`大纲/总纲.md`）+ 当前进度（`resume.py` 输出）+ 目标章数。
**动作**：
1. 解析总纲的分卷规划表，计算卷章结构（每卷章数、总字数预算）。
2. 确认目标章号范围内的章纲是否就位（缺纲的章标记为「需补纲」）。
3. 确认无欠账（`resume.py` 退出码 0）。
4. 输出计划文件 `追踪/auto_write_plan.json`。

**plan.json 结构**：

```json
{
  "book_dir": "D:/存放/小说/我的书",
  "plan_at": "2026-07-28T10:00:00",
  "target_chapters": 10,
  "start_chapter": 25,
  "end_chapter": 34,
  "volume_structure": [
    { "volume": 2, "chapters": "20-35", "title": "龙城风云", "total_words": 48000 }
  ],
  "chapters_missing_outline": [30, 32],
  "debt_check": { "passed": true, "issues": [] },
  "estimated_words": 30000,
  "estimated_time": "5h"
}
```

plan.json 是一次性的计划快照，run 阶段不修改它（run 的进度写在 state.json）。
断点续写时如果 plan.json 存在，直接读取跳过 plan 阶段。

### run 阶段（执行）

**输入**：plan.json + state.json（断点续写时）。
**动作**：循环执行「补章纲（如缺）→ 单章写作循环（chapter-loop.md Step 0–8）→
机器闸口 → 追踪更新 → 下一章」。
**状态持久化**：每章完成后更新 `追踪/auto_write_state.json` 和
`追踪/auto_write_cache.json`（见下节）。
**自动暂停**：遇到终止条件（见终止条件节）即停止 run 循环，进入 report 阶段。

run 阶段每章的安全约束（不可跳过）：
- `check_text.py`（7 Gate + 字数 + 禁用词 + 毒句式 + 伏笔超期 + 量化打分）
- `rhythm_guard.py`（A/B/C 配额 + 事件冷却 + 档位）
- `validate_tracking.py`（追踪五文件格式复核）

### report 阶段（报告）

**输入**：state.json + cache.json。
**动作**：生成进度报告（每 5 章一次 + 终止时终局报告）。
**输出**：报告文本（输出到对话 + 写入 state.json 的 `last_report_chapter`）。
**报告内容**：已完成卷/章/字数、门禁通过率、伏笔超期项、待处理问题。

三阶段的关系：plan 是一次性的（启动时跑一次），run 是循环的（每章一轮），report 是
周期性的（每 5 章 + 终止时）。断点续写时跳过 plan（plan.json 已存在），直接进入 run。

## 状态机

```
        ┌──────────┐
        │   IDLE   │ ← 初始/终止态
        └────┬─────┘
             │ 启动指令（目标章数 N）
             ▼
        ┌──────────┐
        │ PLANNING │ 读 state/cache、确认无欠账、校验章纲就位
        └────┬─────┘
             │ 前提就绪
             ▼
        ┌──────────┐
        │ WRITING  │ 走单章 chapter-loop Step 0–8
        └────┬─────┘
             │ 本章正文落盘 + 追踪更新
             ▼
        ┌──────────┐
        │   GATE   │ 机器闸口全绿？
        └────┬─────┘
             │ 是            │ 否（返工上限内）
             ▼               ▼
        ┌──────────┐   ┌──────────┐
        │ TRACKING │   │ 返工本章  │
        └────┬─────┘   └──────────┘
             │ 达报告周期/终止条件
             ▼
        ┌──────────┐
        │REPORTING │ 输出进度报告
        └────┬─────┘
             │ 未达终止条件
             ▼
        ┌──────────┐
        │ WRITING  │ 下一章
        └──────────┘
             │ 达终止条件
             ▼
        ┌──────────┐
        │   IDLE   │ 写终局报告，释放锁
        └──────────┘
```

### 各状态职责

- **IDLE**：无任务。检测到 `追踪/auto_write_state.json` 存在且状态非 IDLE → 进入断点续写询问（见下节）。
- **PLANNING**：读 `state.json` 与 `cache.json`，跑 `resume.py` 确认无欠账，校验目标章号范围内的章纲是否就位（缺纲的章先补纲再进 WRITING）。输出 `追踪/auto_write_plan.json` 作为计划快照（断点续写时若 plan.json 已存在则跳过此步）。
- **WRITING**：完整走 `chapter-loop.md` 的 Step 0–8，不做任何跳步。本章正文落盘、追踪五文件更新、`validate_tracking` + `entity_index build` 全部完成后才进 GATE。
- **GATE**：机器闸口判定。`check_text.py` + `rhythm_guard.py` + `style_fingerprint.py compare`（每 5–10 章）全绿 → TRACKING；有 FAIL → 在返工上限内返工本章，超限 → 熔断停止。
- **TRACKING**：更新 `state.json`（当前章号、已写章数、门禁通过率、上次断点时间）与 `cache.json`（本章处理摘要）。更新完进 REPORTING 或直接回 WRITING。
- **REPORTING**：每写完 5 章输出一次进度报告（见报告模板）。终止条件满足时输出终局报告。
- **IDLE（终止）**：终局报告输出后，`state.json` 标记 IDLE，释放执行锁。

## 状态持久化

### `追踪/auto_write_plan.json`

plan 阶段输出的一次性计划快照。结构见「三阶段调度 → plan 阶段」。run 阶段不修改此文件，
断点续写时若此文件存在则跳过 plan 阶段直接进入 run。

### `追踪/auto_write_state.json`

调度器在 TRACKING 阶段写入，WRITING 阶段读取。结构：

```json
{
  "status": "WRITING",
  "book_dir": "D:/存放/小说/我的书",
  "target_chapters": 10,
  "start_chapter": 25,
  "current_chapter": 28,
  "written_count": 4,
  "gate_pass_rate": 0.75,
  "consecutive_gate_fail": 0,
  "start_time": "2026-07-27T10:00:00",
  "last_checkpoint_time": "2026-07-27T11:30:00",
  "p0_rewrite_rounds": { "27": 0, "28": 1 },
  "last_report_chapter": 25
}
```

字段说明：
- `status`：IDLE / PLANNING / WRITING / GATE / TRACKING / REPORTING
- `target_chapters`：本轮托管目标章数（用户指定）
- `start_chapter`：起始章号（= 启动时 `resume.py` 报告的下一章）
- `current_chapter`：当前正在写/刚写完的章号
- `written_count`：本轮已写完的章数（= current - start + 1，已写完的）
- `gate_pass_rate`：本轮门禁一次通过率（一次通过章数 / 已写章数）
- `consecutive_gate_fail`：连续门禁未通过章数，达到 2 触发熔断
- `start_time` / `last_checkpoint_time`：用于估算剩余时间
- `p0_rewrite_rounds`：每章的 P0 返工轮次（键=章号，值=轮次），单章上限 2
- `last_report_chapter`：上次进度报告对应的章号，用于判断是否该出下一份报告

### `追踪/auto_write_cache.json`

幂等缓存，记录每章的处理摘要，用于断点续写时跳过已完成的章：

```json
{
  "chapters": {
    "25": {
      "status": "done",
      "title": "第025章_龙城惊变",
      "word_count": 3120,
      "gate_pass": true,
      "rewrite_rounds": 0,
      "completed_at": "2026-07-27T10:25:00",
      "summary": "主角识破陷阱，与反派正面交锋，埋下神秘符文伏笔。"
    },
    "26": {
      "status": "done",
      "title": "第026章_暗流涌动",
      "word_count": 2980,
      "gate_pass": false,
      "rewrite_rounds": 1,
      "completed_at": "2026-07-27T10:55:00",
      "summary": "配角线推进，揭示反派背景，为下一章高潮铺垫。"
    }
  }
}
```

断点续写时，cache 中 `status: "done"` 的章直接跳过；`status: "writing"`（异常中断的章）
→ 询问用户「丢弃半成品重写」还是「从断点继续」（默认重写，因为半成品可能上下文已丢失）。

## 执行锁

`追踪/auto_write.lock` 防止并发执行。启动时写入当前进程标识：

```
PID: 12345
started: 2026-07-27T10:00:00
```

- 启动 PLANNING 前检查锁文件是否存在。存在 → 询问用户「另一实例可能正在运行，强制接管还是退出？」
- 用户选「强制接管」→ 覆盖锁文件，继续。选「退出」→ 停止。
- 终局报告输出后或熔断停止后，删除锁文件。
- 异常崩溃导致锁未清理：下次启动检测到锁 + 对应 `state.json` 状态非 IDLE → 走断点续写询问。

## 断点续写

会话中断后重新进入时，调度器先检查 `state.json`：

1. **文件不存在**：全新任务，正常启动。
2. **文件存在且 `status == IDLE`**：上一轮已正常结束，清理后启动新任务。
3. **文件存在且 `status != IDLE`**：检测到未完成任务，向用户报告：

   ```
   检测到未完成的托管任务：
   - 目标：从第 25 章起写 10 章
   - 进度：已写 4 章（第 25–28 章），当前状态 WRITING（第 28 章可能未完成）
   - 门禁通过率：75%
   - 上次断点：2026-07-27 11:30

   选择：
   [1] 继续从第 28 章重写（推荐，半成品可能上下文已丢）
   [2] 继续从第 29 章开始（跳过第 28 章，若已确认第 28 章完成）
   [3] 重置任务，从头开始
   [4] 放弃托管，手动接手
   ```

用户选择后，更新 `state.json` 对应字段，进入 PLANNING。

## 每章流程

托管模式下每章完整走 `chapter-loop.md` 的 Step 0–8，不做任何跳步。差异点：

1. **Step 0 欠账门**：托管模式不向用户逐章报告欠账，而是自动补账（修未通过门禁的章、
   补回写追踪文件、处理 🔴 超期伏笔）。补账失败 → 熔断停止，报告原因。
2. **Step 1 读章纲**：章纲缺失 → 自动触发滚动补纲（`outline-system.md`），补纲后继续。
   补纲涉及主线变更 → 熔断停止（托管不改主线，铁律第 6 条）。
3. **Step 4 写正文**：正常写。
4. **Step 5 机器闸口**：全绿 → TRACKING。有 FAIL：
   - P0 级（禁用词/毒句式/正文污染/字数严重偏差）→ 返工，计入 `p0_rewrite_rounds`。
   - P1/P2 级（节奏配额越界/文风漂移）→ 尝试局部修，修不好则标记「有条件通过」继续。
   - 单章返工达 2 次（MAX_P0_REWRITE_ROUNDS=2）仍有 P0 → 标记「门禁未通过」，
     `consecutive_gate_fail += 1`，写回 `state.json`，继续下一章（不无限卡在一章）。
5. **Step 7 更新追踪**：正常更新，跑 `validate_tracking` + `entity_index build`。
6. **Step 8 报告**：托管模式不逐章向用户报告，而是写入 `cache.json`。每 5 章输出一次进度报告。

## 进度报告

### 每 5 章报告模板

```
========== 托管进度报告（第 {start}–{current} 章）==========
【卷】第 X 卷 {卷名}
【当前章】第 {current} 章 {标题}
【已写】{written_count} / {target_chapters} 章
【字数】本轮累计 {total_words} 字，平均 {avg_words} 字/章
【门禁】一次通过率 {pass_rate}%，返工 {rewritten} 章
【伏笔】活跃 {active} 条，超期 {overdue} 条
【时间】已用 {elapsed}，平均 {avg_time}/章，预计剩余 {eta}
【状态】{status}
下次报告：第 {current + 5} 章后
======================================================
```

### 终局报告模板

```
############## 托管完成 ##############
【目标】从第 {start} 章起写 {target} 章
【结果】{written_count} 章完成（{success_count} 章通过，{conditional_count} 章有条件通过，{fail_count} 章未通过）
【终止原因】{正常完成 / 用户手动停止 / 门禁熔断 / 补纲需人工}
【总字数】{total_words} 字
【门禁通过率】{pass_rate}%
【返工统计】共 {total_rewrites} 次返工，涉及 {rewritten_chapters} 章
【伏笔台账】新埋 {planted} 条，回收 {resolved} 条，超期 {overdue} 条
【总用时】{total_time}
【遗留问题】
  - {问题1}
  - {问题2}
【建议】{下一步操作建议}
######################################
```

## 终止条件

满足以下任一条件，调度器停止并输出终局报告：

1. **正常完成**：`written_count >= target_chapters`，所有章门禁通过或有条件通过。
2. **用户手动停止**：用户在任意时刻说「停」「停止托管」「暂停」。调度器在当前章
   走完 Step 8 后停止（不中途打断正在写的章，保证状态一致性）。
3. **门禁熔断**：`consecutive_gate_fail >= 2`（连续 2 章门禁未通过）。说明系统性
   问题（多半是纲或设定的问题，不是单章问题），停止并报告根因分析，提示人工介入。
4. **伏笔超期**：`resume.py` 报告伏笔台账出现 🔴 超期项 → 暂停，提示先处理超期伏笔
   （回收/延期/废弃）。伏笔超期是连载硬伤，带病继续写只会让断线更难补。
5. **节奏配额越界**：`rhythm_guard.py --declare` 预检 FAIL（A/B/C 配额越界 / 事件冷却
   违规 / 连续快档超限）→ 暂停，提示改纲（调整本章档位声明或修改节奏配额表）。
6. **补纲需人工**：滚动补纲触及主线变更，托管不改主线（铁律第 6 条），停止等人工。

熔断时的根因分析报告：
- 列出连续 3 章的 FAIL 项分类（禁用词/毒句式/字数/节奏/伏笔）
- 判断是「写作层问题」（改正文可解）还是「结构层问题」（需改纲/改设定）
- 给出建议处理方向

## 熔断后的恢复

熔断后 `state.json` 标记为 `GATE_FAIL_BURNT`（非 IDLE），等待人工处理：

1. 作者排查根因，修正纲/设定/禁用词表。
2. 修正后重新启动托管，检测到 `GATE_FAIL_BURNT` 状态：
   ```
   上次托管因门禁熔断停止（连续 3 章未通过）。
   涉及章节：第 {X}–{X+2} 章
   根因：{上次报告的根因}
   
   是否已处理？[1] 已处理，继续托管 [2] 手动接手
   ```
3. 用户确认「已处理」→ 重置 `consecutive_gate_fail = 0`，从熔断章重新开始写。

## 幂等性保障

`cache.json` 记录每章的处理摘要。断点续写或重试时：

- cache 中某章 `status == "done"` 且 `gate_pass == true` → 跳过，直接进入下一章。
- cache 中某章 `status == "done"` 但 `gate_pass == false`（有条件通过）→ 不重写，
  保留原结果，继续下一章。
- cache 中某章 `status == "writing"` 或不存在 → 正常写这一章。
- cache 中某章的 `word_count` 与正文文件实际字数不符 → 标记为「需重写」（正文文件
  可能被外部修改或写入不完整）。

幂等检查在 PLANNING 阶段执行：遍历目标章号范围，对照 cache 跳过已完成章，列出待写章清单。

## 退化防护（托管特有）

托管连写最长时间、最多章数，文风退化风险最高。在 `daily-batch.md` 的退化防护基础上
加强：

1. **每 5 章跑一次文风指纹对比**（`style_fingerprint.py compare`），与开书基线对比。
   漂移 > 15% → 在进度报告中标记警告，不立即停（可能是某一章的个别漂移）。
2. **连续 2 份报告（10 章）漂移都 > 15%** → 熔断停止，报告文风退化趋势。
3. **每 10 章做一次跨 Agent 审核**（见 `cross-review.md`），托管模式下这是
   自动触发的，不需要人工介入。审核发现 P0 → 熔断。

退化防护的基线：开书前 10 章的 AI 味分数均值 + 文风六维指纹，存在 `设定/文风锚.md`
的量化基线部分。

## 托管纪律

- **不越权决策**：托管只做「写下一章还是停」「返工还是标记有条件通过」「报告还是继续」。
  不做「改主线」「改设定」「弃伏笔」「换题材」——遇到这些需求一律熔断等人工。
- **不跳步**：每章完整走 Step 0–8。托管不意味着简化流程，只是省掉了「向用户逐章报告
  和等待确认」的环节。
- **不并发**：同一本书同一时间只允许一个托管实例（执行锁保障）。
- **不留半成品**：异常中断的章默认重写，不尝试从半成品续写（上下文可能已丢失）。
- **机器闸口是底线**：托管模式完全依赖机器闸口做质量判定。机器闸口本身不依赖任何 agent，
  永远可用（见 `assets/agents/README.md`）。

## 实现方式

本文档是协议规范，不是外部调度脚本。自建 skill 不依赖外部调度器进程，而是靠文件状态机
驱动：模型按本协议操作，通过读写 `auto_write_plan.json` / `auto_write_state.json` /
`auto_write_cache.json` 三个文件实现状态管理和断点续写。

- **plan/run/report 三阶段**由模型按本协议的步骤执行，不依赖外部编排引擎。
- **断点续写**靠读 `state.json` 恢复，不依赖外部检查点机制。
- **自动暂停**靠模型在每章完成后检查终止条件，不依赖外部监控进程。
- **幂等缓存**靠读 `cache.json` 跳过已完成章，不依赖外部去重逻辑。

模型执行本协议时，每个状态转换都要更新对应的 JSON 文件，确保会话中断后能从文件恢复。

## 与其他工作流的关系

| 场景 | 用哪个 |
|---|---|
| 人工日更 2–3 章 | `daily-batch.md` |
| 托管连写 N 章 | `auto-write.md`（本文件） |
| 单章精写 | `chapter-loop.md` |
| 复杂章拆 Beat | `beat-pipeline.md` |
| 关键章团队写 | `editorial-team.md` + `assets/agents/` |
| 卷级评审 | `review-rubric.md` |
| 每 10 章跨 Agent 审核 | `cross-review.md`（托管模式自动触发） |
| 大修 | `revision.md` |

托管模式是「调度器」角色：它调用 `chapter-loop.md`（单章逻辑）、`outline-system.md`
（滚动补纲）、`resume.py`（欠账检查）、机器闸口（质量判定），自身只管状态机和决策。
