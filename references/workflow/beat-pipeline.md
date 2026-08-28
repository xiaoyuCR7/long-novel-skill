# Beat Sheet 多步流水线（beat-pipeline）

Beat 是事件授权单元，scene unit 才是实际生成单元。Beat 流水线只替换
`chapter-loop.md` Step 4 的编排方式，欠账门、required context、章意图、门禁与事务均不省略。

## 何时启用

适用于高潮、反转、大结算、长章或作者需要分场景写作的章节。日常章可直接用单章循环。
单章遇阻时可在剩余修复额度内切换 Beat；已经修两轮仍有 blocking/P0，必须 `gate_blocked`，
不得把切换流水线当第三轮自动重写，也不能把失败降成 advisory。

## Step 1：准备与预算门

先按 `chapter-loop.md` 核对欠账和必需来源；若需改纲，须在 prepare 前取得授权并完成。
读取 `references/craft/scene-rendering.md`，生成以 `assets/templates/chapter-intent.json`
为唯一字段契约的完整 Brief，明确 ending_mode、情绪前后状态与触发/选择、允许事件及禁放信息。
若授权 beats 不足，停止并输出 literal `outline_underfilled` 和具体 `missing_beat_budget`，
不能用待补充 Brief、重复办理动作或新剧情补字数。

```bash
python scripts/chapter_transaction.py prepare "{book}" --chapter {N}
```

`{stage}`/`{chapter_file}` 只采用 prepare 输出；修旧章沿用原名。正文合成前正式文件不变。
章意图、Beat Sheet、场景片段与报告放在 stage 和正式工程之外的本次工作目录；不得写入
stage 的大纲目录。stage 只人工改本章正文和追踪五表，gate/index 由脚本生成。

## Step 2：Beat Sheet 与节奏预检

每个 Beat 写清：授权事件、触发/阻力、行动与反应、可观察变化、情绪前态 → 后态、预算。
再把有关联的 beats 合并、交织成场景；不固定一条 beat 一段、一条 beat 一个场景或一定 4–8 拍。
场景检查卡包含目的、阻力、变化、感官锚、行动/反应、过渡。

- 类型过于单一时调整已授权事件的呈现方式，不擅自插入新的异类型事件。
- 配额或冷却越界时停止并提出授权内调整；若需改纲，recover 后改，再 prepare。
- serial 的章末问题只能来自授权事件；closed/finale 的 hook_question 必须为空，以结算和
  闭合余韵收束。finale 不得把多余配额事件挪到不存在的后续章，须交作者取舍。

## Step 3：按 scene unit 渲染

每次调用独立写作 Agent，实际传入完整章意图与来源内容、场景渲染规则、本场景所覆盖的 beats、
当前场景进入状态及必要前段。不能只给当前 Beat + 上段，也不能只链接未部署的参考路径。
Brief 字段与阻断协议见 `assets/agents/novelist.md`。

- 允许在授权内合并、交织、局部重排 beats，不得改状态终点、禁放信息或结尾模式。
- 把情绪放进触发 → 选择/代价 → 行动反馈：兑现前后的态度、反应和互动须可感知。
- 详写有信息、阻力、选择或关系变化的回合；重复核看、等待、收据交付没有新功能就合并，
  不把机械动作当情绪交付，也不删掉必要验收证据。
- 局部片段检查只是诊断；不能把片段的结尾当章尾或把单段字数当全章门禁。

## Step 4：合成 pending draft

按戏剧因果串联合成，核对指代、时序、动机与过渡，消除分段生成的重复交代。
结构按 ending_mode 选择“承接 → 发展 → 结算 → 已授权悬念/闭合余韵”；首章上章承接可 N/A。
全章候选只写入 `{stage}/正文/{chapter_file}`，不是正式正文；不用未授权事件补足预算。

## Step 5：整章门禁、自查与追踪事务

执行 `chapter-loop.md` Step 5–7：机器诊断、总编辑语义自查、五表暂存并核对同步。
去 AI 味时保留反应、态度、互动功能，修复指代和连接，不删成纯事件流水账。

```bash
python scripts/chapter_transaction.py validate "{book}" --min-chars {下限} --max-chars {上限} --declare "{配额,事件类型,档位}"
# 自查真实通过、所有 blocking/P0 清零之后
python scripts/chapter_transaction.py commit "{book}" --self-review-confirmed
```

validate 只检查机器门禁、追踪和哈希，不验证语义报告；总编辑必须真实核对后一项。
声明以减号开头时用 `--declare=-,world_painting,中`。任何改稿都使旧验证/受影响审核过期。
blocking/P0 最多自动修两轮，仍失败输出 `gate_blocked`，保留 checkpoint 与 pending draft，
停止自动改写且不提交。团队、Beat、模型和会话之间共享该章该任务的修复计数，不能重置。

五表与正文共同 commit 成功才算本章完成并允许开下一章；finale 不预告不存在的下一章。
Beat Sheet 保留在工作目录供复盘，不是事务提交目标。

## 与编辑团队组合

策划主编提供完整 Brief 与场景计划，写作特工按场景生成，反 AI 编辑和连载核实官审整章；
仍由总编辑统一管理本章 stage、两轮上限与提交。团队细节见 `references/craft/editorial-team.md`。
