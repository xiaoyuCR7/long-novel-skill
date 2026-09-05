# 修订流程（revision）

适用：改纲波及已写章节、开篇重写、平台迁移、盲评后大修，以及一句话的措辞小改。
只请求诊断时不改稿；已发布章节须取得作者对修改范围的授权，不能自行覆盖线上版本。

## 共同边界

- 所有正文修改均复用 `references/workflow/chapter-loop.md` 的章事务，不能先改正式正文再验收。
- 纯措辞/顺句小改不要求改纲；只有事件或走向变化才先按 `outline-system.md` 处理改纲授权。
- 需要改纲或登记设定变更时，在 prepare 前完成；prepare 后发现还需改这些输入，先 recover
  放弃本次事务，再改纲/设定并重新 prepare。不得在 stage 内改纲，也不静默扩大事务白名单。
- 大修逐章提交，不是全书原子事务。冻结新章直到所有受影响章节及跨章一致性核对完成；
  中途遇阻保留已提交章和受阻章 checkpoint，明确当前混合版本状态，不能宣称整书已回滚或完成。

## Step 1：圈定范围与确认

旧章改动可先运行 `python scripts/story_graph.py impact "{book}" --chapter {N}`。
它只列当前来源提及、图谱候选及可能受影响的引用；旧图谱、过期哈希和推测必须回查原文，
不据此自动改写后文或追踪。图谱缺失时用正文搜索回退；完整解释见 `evidence-review.md`。

小改记录作者要求、章号与既有文件名即可。大修先在本次工作目录登记原因、范围、冻结状态，
按 `outline-system.md` 完成必要改纲，再用正文搜索定位受影响的人物、地点、伏笔与后续引用。
列逐章清单：重写 / 局部修 / 不动；不得为了修辞顺手改变授权事件。
作者若只允许修重复解释、指代或标点，实际发生的动作次数、先后与参与者仍须保留；
同义解释可压缩，多次动作不能因此变成一次。只有明确包含删减冗余动作的修订范围，才按
功能判断是否合并实际回合；不确定时保留并列为建议，不替作者扩大修改范围。
本次工作目录在 stage 与正式工程之外，保存章意图、Beat、修订记录、语义报告和修复次数。

工艺修订先保护作者认可样段、禁令、叙事距离与内心戏；叙述者与角色声线分开判断。
按 `scene-rendering.md` 判断信息、策略、关系、风险、节奏、视角的实际损失，短摘录记入现有
工程外修订记录，附功能和改/留理由。不另造 Brief schema，不凑 3–5 个问题，不为词频或动作
重复换词/轮换身体动作。有功能的长句、日常、情绪命名和标点保留；必要验收及变化后的关系不删。
确定需精确豁免的 B/G 误报须有实际作者授权，在 prepare 前按 `anti-ai-style.md` 登记本书
`设定/文风豁免.json`；不向上跨书查、不在 stage 改配置，不豁免作者禁词或其他硬门禁。

## Step 2：逐章 prepare 与暂存修订

先运行恢复诊断，未完事务按 `chapter-loop.md` recover；允许进入修订来处理被报告的欠账，
但欠账未清不能开新章。读取该章必需来源与已有正文后：

```bash
python scripts/chapter_transaction.py prepare "{book}" --chapter {N}
```

严格使用输出的 `stage_root` 和 `chapter_file`，旧章沿用原文件名，不另造同章标题文件。
只在 `{stage}/正文/{chapter_file}` 修改候选正文、在 stage 的追踪五表同步受影响条目；
不向正文追加修订记录或审核说明。一句话小改也必须经此边界。
章意图沿用 `assets/templates/chapter-intent.json` 的完整字段，按
`references/craft/scene-rendering.md` 保留事件授权、情绪前后变化及 ending_mode。

## Step 3：暂存五表与核对影响

- `章节摘要.md`：替换受影响章的原条目，不重复追加；核对后文引用是否仍成立。
- `角色状态.md`：依据已写到的最新章节重算当前状态，不用早期章的修订状态覆盖后续事实。
- `伏笔台账.md`：修正埋设/回收章节，被删除的伏笔注明修订销账，新授权伏笔登记。
- `时间线.md`：同步修正受影响时间关系。
- `节奏配额.md`：替换该章记录并复核上下游冷却与档位；不能只追加造成重复触发。

无变化的表保留，不为凑变更制造状态。报告、章意图和 Beat 均留在工作目录；stage 除正文
与五表外不允许人工改文件，gate/index 由脚本生成，否则会被拒绝为 `stage_changed_outside_transaction`。

## Step 4：验证、真实自查与共同提交

```bash
# 只读标点候选，不自动改写；非零本身不是章事务 blocking
python scripts/normalize_punct.py "{stage}/正文/{chapter_file}" --check
python scripts/chapter_transaction.py validate "{book}" --min-chars {下限} --max-chars {上限} --declare "{配额,事件类型,档位}"
# 只有总编辑真实自查通过、全部 blocking/P0 清零后才能执行
python scripts/chapter_transaction.py commit "{book}" --self-review-confirmed
```

validate 只验证追踪、机器正文/节奏门禁、索引与哈希，不读取语义报告，也不证明情绪/一致性
通过。总编辑须按 `chapter-loop.md` 自查当前候选正文；修改 stage 后重新 validate。
标点保留有功能的打断与迟疑，不跑默认归一化，不生成 `.bak`。文风指纹偏离、advisory 或连续
重复报警只供语境复核，不自动强改。修后连读确认说话人、主体指代、空间与因果清楚，
合并无作用重复而不把每拍都扩写。实际 blocking/P0、授权、事实、预算和配额要求不放宽。
不触发配额且值以减号开头时写 `--declare=-,world_painting,中`。
任何 blocking/P0 最多自动定向修复两轮；第二轮仍失败输出 `gate_blocked`，不再自动改、
不 commit，保留 checkpoint 与待作者裁决项。换团队、Beat、模型、会话或重新 prepare
不能清零同一修订任务的次数；工具/模型降级不能把 blocking 改成 advisory。

## Step 5：跨章核对与解冻

所有受影响章逐章通过后，连读改动上下游，核对摘要引用、当前人物状态、伏笔、时间线和配额。
若还需修正文或五表，重新走该章事务；新章继续冻结。跨章核对也通过后才登记大修完成并解冻。
报告每章实际提交状态、剩余风险和作者需裁决事项，不把单章通过说成全书原子成功。
