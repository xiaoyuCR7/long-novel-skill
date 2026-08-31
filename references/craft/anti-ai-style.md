# 7 Gate 去 AI 腔：按功能修订

去 AI 腔是修复空泛、重复、失真的表达，不是删除某类词、标点或内心戏。
作者本轮明确决定与认可的本书声线优先于通用技巧和对标统计；作者禁令、已发生事实、
章纲授权、required context、真实 P0、字数预算、节奏配额和章事务不因此放宽。
工艺判断复用 `scene-rendering.md`：一句话对信息、策略、关系、风险、节奏或视角有何作用？
只改能指出损失的地方，不因词频高就判文学失败，也不把通过机器检查等同于写得好。

## 机器边界与处理顺序

`check_text.py --gate-report` 保持既有 blocking/advisory 分级。机器定位候选，人工核对语境；
blocking 不能凭一句“读起来没问题”跳过，须修复或使用下述已有授权的精确豁免后重跑。

| Gate | 机器覆盖 | 人工判断 |
|---|---|---|
| A 禁用词 | 内置词表叙述 blocking、对话 advisory；已有词白名单 | 作者禁词、必要术语、限知不确定还是套话 |
| B 毒句式 | 否定对比、否定排比、这一刻、音量反差等既有正则 | 是否真正区分事实、纠正误判或改变理解 |
| C 心理告知 | 心理句式候选，advisory | 情绪命名/内心戏是否承载视角、取舍或压缩时间 |
| D 节奏 | 短句连排、长段、微动作、密度等 advisory | 断了指代/因果、无作用重复还是有效节奏 |
| E 对话 | 声线与关系主要靠人工 | 说话人清楚，话符合目的、知识、关系语境 |
| F 结尾 | 总结候选；预告/状态总结的既有规则仍 blocking | 兑现本章 ending_mode 还是赘述已有结论 |
| G 解释腔 | 既有解释句式 blocking | 越界剧透还是已批准叙述距离中的判断 |

工程元信息泄漏和 AI 身份/拒绝语残留仍 blocking。引号内外分域以脚本实际识别为准，
不要为过闸口改引号或伪装成对白。密度、风格分数和重复报警不自动升级为 P0。

### 词白名单与精确句式豁免

先用已有词白名单解决适用问题：书籍根 `.deslop-whitelist` 每行一个词或短语，支持 `#` 注释；
也可用 `--whitelist` 或 `设定/禁用词.txt` 的 `!` 前缀。完整短语只豁免该短语所在行的相关词命中，
不是句式正则豁免。题材专属词表仍在 `设定/禁用词.txt`，作者明确禁用的词不得擅自加白。

有功能的 B/G 句式被误报、且有实际作者授权时，只在本书 `设定/文风豁免.json` 登记：

```json
{
  "version": 1,
  "exemptions": [{
    "chapter": "第001章.md",
    "line": 1,
    "text": "她不是不想回家，而是不敢带着这封信回去。",
    "rule": "not-is-comparison",
    "reason": "区分意愿与恐惧，删前项会丢失她仍想回家的事实",
    "authority": "作者本轮明确要求保留这句对比"
  }]
}
```

这是示例，不能复制示例授权冒充真实批准。允许的规则仅为 `not-is-comparison`、`no-only`、
`this-moment`、`negation-parade`、`reverse-not-is`、`voice-contrast`、`explainer-tone`。
章文件名、从 1 开始的原始行号、含空格/标点的整行原文、rule 必须全部匹配；其他行和其他规则照扫。
正文改行或改字后旧记录不再匹配，重新核对授权与原文，不扩大豁免范围。
非法类型、未知规则或损坏配置退出 2；配合 `--gate-state` 会写失败记录，不能沿用以前成功。
普通 CLI、`--gate-report`、`--ai-patterns` 使用同一范围；实际生效的完整记录写入 gate JSON
顶层 `style_exemptions`。不可豁免 meta/refusal、作者禁词、事实、字数、台账、节奏或事务。

配置只自动读取当前 `正文` 所属书籍的 `设定/文风豁免.json`，不向上跨书搜索。
在 prepare 前登记，非隐藏文件会进入快照；stage 内不可改设定。prepare 后才确认需新增时，
先 recover，再按授权登记并重新 prepare，修复轮数不重置。不要新增整章 `<!-- 闸口:跳过 -->`
绕过扫描；旧标记不是局部文风修订的解决办法。

## Gate A/B：删空泛，不删区分

机器内置词表以 `scripts/check_text.py` 的 `BANNED_WORDS` 为准：仿佛、似乎、不禁、不由得、
一丝、眼底闪过、嘴角勾起、嘴角上扬、意味深长、若有所思、不容置疑、空气仿佛凝固、
时间仿佛静止、众所周知、值得一提、不得不说。其他词仅在本书已加载词表中才是机器禁词。

| 候选 | 先问 | 最小修复 / 保留条件 |
|---|---|---|
| 仿佛、似乎 | 视角真的不能确定，还是避开具体描写？ | 无不确定性则直写；限知推测保留并按需白名单 |
| 嘴角勾起 | 笑是否改变互动？ | 可简写“他笑了”；笑是退让/接受信号时不删掉反应 |
| 沉声道、淡淡地说 | 语气有无新增作用？ | 冗余时改“说”或去标签；说话人不能因此含混 |
| 不是 A，而是 B | 两项是否有真实区别？ | 只是换词拔高则删前项；纠正误判、区分动机则留 |
| 这一刻 | 时间对照是否重要？ | 空起手删；转折时点有意义则按实际语境处理 |
| 名词前多个修饰 | 各自是否提供不同信息？ | 删重复，不固定为“一个形容词”；颜色有关线索时不能删 |

## Gate C：内心戏、情绪命名与外化都可用

“他很紧张”可能是赘述，也可能是叙述距离所需的简洁交代。先看这句是否已被上下文表达、
是否推进选择或体现角色自我认识；没有一律外化的要求。大段重复解释可合并，不能把每句
心理都替换成手抖、握拳、移开视线，更不能新增身体反应、往事或事件凑情绪。

例如前句已写“他把门闩摸了三遍，始终没敢开门”，后句“他很害怕，心里充满恐惧”
没有新功能，可删除后句。反例：“他承认自己害怕，仍把门闩拉开了。”命名与选择形成落差，
应保留。相邻动作/情绪重复按 `scene-rendering.md` 合并，必要验收与变化后的关系不删。

## Gate D：恢复自然句群

- 保留作者声线中的长句、短句、排比和停顿，只有读不清、无功能复述或节奏失真才改。
- 指代、空间、时序、因果要清楚；有语义作用的“的、了、就、却、才、因为、于是”不清零。
- `ai-low-connective-density` 只提示可能的提纲/电报体；补缺失关系，不全局填连接词。
- 破折号可表现被打断，省略号可表现吞咽/沉默；不强制改动作或句号。标点按语气和作者契约选。
- 平均句长、对白占比和段落长度只帮助定位偏离；对照 `设定/文风锚.md` 的受保护特征再判断。

## Gate E：声线来自人，不来自动作轮换

先确认角色要得到什么、知道多少、在对谁说。普通“说”、日常问答、直说动机都可成立。
遮名测试用来定位差异不足，不要求每句短答都可独立认人；补清说话人比硬造口癖重要。
只在能改变策略、关系或节奏时加动作/沉默，不按频率穿插，不限定对白比例。详见 `dialogue.md`。

## 状态核对与状态复盘

必要状态核对会改变悬疑、改变行动或改变读者认知，也可包含一次确有作用的责任确认；应保留。
无新增戏剧功能的状态复盘，是在动作或后果已经确立之后，再重复同一状态、选择或责任。

删除时逐句核对：

- 前文的动作或后果是否已经让同一信息成立；
- 删除是否不损失因果、连续性、悬疑、行动依据和读者必要认知；
- 仍有重复才直接删，不改写成另一句总结，也不补造事实。

不能仅因“仍”“依旧”等词机械删除；这些词可能承担时间连续、状态变化或必要对照。

### Relationship explanation deletion test

For direct relationship conclusions, check the local observable carriers (actions, forms of address, pauses, object handoffs, and consequences) before deleting. Delete or compress only when the sentence adds no new information and deletion preserves relationship state and interaction function; preserve necessary state, causality, strategy, viewpoint knowledge, or interaction function with the smallest current-POV rewrite. Do not invent memories, diagnoses, symbols, actions, dialogue, motives, or facts to satisfy show-don't-tell, and protect on_page_requirements. This is shared by full-chapter and recovery review, not fragment mode.

## Gate F/G：结尾与解释服从叙事契约

删重复点题、越过视角的信息和抢先定性的旁白；保留已批准声线中的判断、回顾、内心戏与余韵。
“这意味着”若是人物当场推断，不等于上帝剧透；按精确句式豁免处理，不整章降级。
serial 留已授权问题，closed/finale 兑现闭合要求，不强造新钩子。不能仅因“他知道”就删掉
选择依据，也不能为了躲词改写已发生事实。

## 防设定复述与元信息隔离

设定可挂在行动、阻力、价格或后果上；必要而简洁的背景交代也可保留，不强制每个术语都制造
冲突。删去后会损失信息、视角、生活质感或节奏的段落，不能因为“情节没动”就删。
大纲指令、TODO、写作过程、求票/请假等不进入正文；故事内真实谈论章节等的误报须单独
向作者说明边界，当前精确文风豁免不支持 meta，不能用整章跳过掩盖。

## 润色与复核

第一遍定位具体功能损失，做最小修复；第二遍复读确认信息、选择、关系、节奏和声线仍成立。
没有问题可以不改，禁止为了报告凑 3–5 个问题。频率与分数只用于决定先看哪段，不能决定
必须删多少或重写整章。报告复用工程外现有修订/语义记录：短摘录、功能、改/留理由；不另造 Brief。

正文修改一律走 `workflow/chapter-loop.md` 的 prepare/stage/validate/commit。单项检查示例：

```bash
python scripts/normalize_punct.py "{stage}/正文/{chapter_file}" --check
python scripts/check_text.py "{stage}/正文/{chapter_file}" --min-chars N --max-chars M \
  --ledger "{stage}/追踪/伏笔台账.md" --current-chapter N --gate-report --gate-state
python scripts/rhythm_guard.py --chapter-file "{stage}/正文/{chapter_file}" \
  --quota "{stage}/追踪/节奏配额.md" --gate-state
```

标点 `--check` 非零只是只读候选信号，不是章事务 blocking；有功能的标点留原样。不要运行默认
批量归一化，也不要在 stage 生成 `.bak`。检查器实际 blocking、配额、预算和真实 P0 仍须处理，
共享最多两轮定向修复；两轮后 `gate_blocked`，不提交、不降级。追踪与正文共同验证提交后才报告完成。
