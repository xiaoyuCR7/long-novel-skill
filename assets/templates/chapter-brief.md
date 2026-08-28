# 第{N}章 Chapter Brief

本表只是交付包；章意图字段唯一来源是 `assets/templates/chapter-intent.json`，
解释与渲染契约见 `references/craft/scene-rendering.md`。不能以本表替代锁定章纲或省略字段。

## 完整章意图

粘贴 chapter-intent.json 的全部字段并填写实际内容，不交付模板空值。
ending_mode 为 serial/closed/finale；closed/finale 的 hook_question 必须为 ""，
closure_requirements 填明确闭合要求，不预告不存在的下一章。

## 预算与场景计划

- 章节号、暂定标题与本章字数预算。
- 每个 scene unit 的目的、阻力、变化、感官锚、行动/反应、过渡及其覆盖的授权 beats。
- 情绪前态 → 后态与触发/选择；保留兑现前后反应、态度和互动变化，不机械扩写重复办理动作。

## 实际输入内容

附本章章纲、上一章正文或可靠摘要（首章无前章可 N/A）、出场人物最新状态、
相关未结伏笔/时间线硬约束、采用的文风依据与来源，以及场景渲染规则内容。
来源路径用于追溯，不能替代输入内容；独立 Agent 不应被要求猜测未部署的技能路径。

## 阻断与工作资料边界

required 缺失/被截断或预算不能容纳时停止，输出具体缺口；不交付可继续写的待补充 Brief。
授权 beats 不够则 literal `outline_underfilled` + `missing_beat_budget`，等作者补纲或缩短目标。
Brief、Beat、章意图与报告保存在 stage 和正式工程之外的工作目录，不混入正文或事务目标。
