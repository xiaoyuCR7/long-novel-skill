# 编辑团队协作协议

团队只分工，不另建提交机制。日常章可 solo，高潮、反转、重要修订或作者要求时可用团队；
切换团队不能重置本章的修复次数。角色定义与实际部署见 `assets/agents/README.md`。

## 四个角色与总编辑

- 策划主编：读必要来源，校验事件/预算边界，交付完整 Chapter Brief；不写正文。
- 写作特工：在已授权范围内生成候选正文；不直接写正式文件。
- 反 AI 编辑：找表达问题、保留情绪功能，输出报告与候选润色稿。
- 连载核实官：核对事实/状态/时间线/伏笔，只有报告权。
- 总编辑：给各角色真实内容、管理 stage 与修复计数、实际自查、决定是否可以 commit。

写作角色可用独立无上下文 Agent；其他角色可按定义内联扮演。不可用时报告实际降级，
不假称已运行多角色或机器门禁，不能把 blocking 改成 advisory。

## 唯一 Chapter Brief 契约

字段以 `assets/templates/chapter-intent.json` 为准，含 goal、state_before、trigger、
choice_or_cost、state_after、allowed_events、forbidden_releases、emotion_transition、
pacing_tier、quota、style_authority、sources、ending_mode、hook_question 及 closure_requirements。
可用 `assets/templates/chapter-brief.md` 包装，不另列一套可省略字段的情节点模板。

Brief 必须实际包含：

1. 已填写的完整章意图；情绪为前态 → 后态并指明触发、选择/代价，非单个情绪词。
2. 章号、标题、字数预算与 scene units；允许多个 beats 合并/交织，不让 beat 列表决定段落形状。
3. 本章章纲、上一章正文或可靠摘要（首章 N/A）、出场人物最新状态、未结伏笔/时间线硬约束。
4. 本章采用的文风依据与来源内容；来源路径是证据，不是内容替代品。
5. `references/craft/scene-rendering.md` 的实际规则内容，尤其场景目的/阻力/变化/感官锚/
   行动反应/过渡、情绪兑现、重复动作取舍与去 AI 味后的连接恢复。不要假设孤立 Agent 能打开该路径。

required 缺失/不可读 → `required_context_missing`；预算不能无损容纳 →
`required_context_over_budget`；授权事件撑不起篇幅 → literal `outline_underfilled` +
具体 `missing_beat_budget`。以上均停止，不交付带待补充标记却可继续写的 Brief。

## 结尾与正文隔离

- serial：结算后留下已授权、下一章可承接的问题。
- closed/finale：hook_question 必须为空，按 closure_requirements 闭合，不强制钩子或下章预告。
  finale 不得把配额冲突挪给不存在的后续章；须请作者裁决当前章取舍。
- 首章没有上章钩子时可 N/A；任一模式都不能为钩子新造未授权事件。
- 写作特工成功只输出 `NOVEL_TEXT_START...NOVEL_TEXT_END` 内的纯正文。
  输入无效则输出 `BLOCKED`、code 与具体缺口，不能把阻断说明塞进 NOVEL_TEXT 标记伪装正文。
- 反 AI 编辑的报告与 `HUMANIZED_TEXT_START...HUMANIZED_TEXT_END` 分离；总编辑剥去标记后
  才写 stage 正文。说明、分析、工程标签泄漏到正文是 P0，但正常小说标点不自动等于说明。

## 执行流程

1. 跑 `python scripts/resume.py "{book}"` 核对欠账/未完事务。修订可处理现有欠账，未清不能开新章。
2. 读取必要来源并解决作者授权、改纲或设定调整；这些修改全部在 prepare 前完成。
3. 策划主编形成完整 Brief 并通过预算门；总编辑准备本次工作目录（在 stage 和正式工程之外）。
4. 创建现有章事务：

```bash
python scripts/chapter_transaction.py prepare "{book}" --chapter {N}
```

使用输出的 stage_root 与 chapter_file，旧章沿用原文件名；不得另存一个同章标题文件。
5. 调用写作特工，实际传入角色定义、完整 Brief、来源内容与场景渲染规则；BLOCKED 就停止派写。
   候选正文只写 `{stage}/正文/{chapter_file}`，不得先改正式正文。
6. 反 AI 编辑和连载核实官可并行读取同一候选稿，报告与改稿建议写在工作目录，不互相写 stage。
   总编辑汇总后独自修改 stage，避免两个编辑覆盖彼此版本。
7. 按 `references/workflow/chapter-loop.md` Step 5–7 执行机器诊断、真实自查与五表暂存。
   stage 只人工改本章正文和五表；Beat、章意图、报告、额外设定不得写入 stage。
   gate/index 由脚本生成；否则会触发 `stage_changed_outside_transaction`。
8. 当前稿全部 blocking/P0 清零之后才提交：

```bash
python scripts/chapter_transaction.py validate "{book}" --min-chars {下限} --max-chars {上限} --declare "{配额,事件类型,档位}"
# 总编辑真实自查通过才能确认；不能用机器 passed 代替语义检查
python scripts/chapter_transaction.py commit "{book}" --self-review-confirmed
```

validate 只核对追踪、机器正文/节奏门禁、索引与哈希，不读取或验证语义报告。
声明以减号开头时用 `--declare=-,world_painting,中`；修改候选或五表后必须重新 validate。
提交完成才报告该章完成；closed/finale 只报告闭合兑现，不制造下章预告。
大修按 `references/workflow/revision.md` 逐章提交并冻结新章，跨章核对后才解冻。

## 修复上限与报告

任何 blocking/P0 最多自动定向修两轮。第二轮仍失败 → `gate_blocked`，保留 checkpoint、
pending draft 和问题证据，不再自动改、不 commit、不写下一章，交作者裁决。
计数记录在工作目录并跨角色/模型/Beat/solo/新会话传递，重新 prepare 也不能重置；
只有作者作出新的明确处置后才能按授权恢复，不能以“有条件通过”绕过未解决 P0。

报告逐条用 id、severity（P0/P1/P2）、category、evidence、why_it_matters、minimal_fix、
confidence、source；实际格式与机器接口见 `references/craft/gate-artifacts-spec.md`。
S1–S4 保留为一致性分类，不替代 severity。审核只复核受修复影响部分，不因不喜欢结论无限重审；
稿件变了则旧报告不能直接沿用，最终自查必须对应当前候选稿。

卷级或节点级跨视角审核按 `references/craft/review-rubric.md`；它不替代逐章事务，也不增加自动修复额度。
