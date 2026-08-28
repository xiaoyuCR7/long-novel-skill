# 门禁产物规范（实际接口）

本文件描述仓库当前脚本实际读写的接口，不把人工报告模板当成已实现的自动流水线。
章节完成还必须通过 `references/workflow/chapter-loop.md` 的自查与事务提交；
单个 JSON 的 `passed=true` 不代表语义审查、追踪同步或发布验收完成。

## 产物、路径与写入者

章号 N 不补零，例如 `追踪/门禁/gate_ch5.json`。正文文件可使用第005章等既有命名。

| 产物 | 谁生成 | 实际用途 |
|---|---|---|
| `gate_ch{N}.json` | `check_text.py --gate-state`，然后 `rhythm_guard.py --gate-state` 合并 | 正文机器检查与节奏检查 |
| 检查详情（标准输出） | `check_text.py --gate-report`、`rhythm_guard.py` | 命中定位与修复依据；需要保留时由调用者保存到 stage 外工作资料 |
| 语义审查报告 | 实际执行审查的 Agent/作者 | 一致性、情绪兑现、结尾模式、文风等判断，不由上述脚本自动生成 |
| journal/checkpoint/stage | `chapter_transaction.py` | 提交验证、冲突检查和恢复，不能用 gate 文件替代 |

`--gate-report` 本身不落盘。当前脚本不自动生成 `check_ch{N}.json`、
`rhythm_ch{N}.json`、`gate_result_ch{N}.json` 或任何 `*.meta.json`。
旧资料中使用这些名称的报告只能视为人工工作资料，不能作为不存在的自动接口调用，
也不能冒充 `gate_ch{N}.json` 的别名。

## gate_ch{N}.json

以下是正文检查与节奏检查都实际执行后的字段示例；时间、哈希、分数以当次运行为准：

```json
{
  "chapter": 37,
  "chapter_file": "第037章.md",
  "chapter_mtime": 1787790000.0,
  "chapter_sha256": "a8b66e095a54f7d8ad416a690c794722f4a64d8439eefb509499b02c6a4bb218",
  "checked_at": "2026-08-27T12:00:00",
  "passed": true,
  "blocking": 0,
  "advisory": 0,
  "ai_score": 0.0,
  "categories": {},
  "style_exemptions": [],
  "rhythm": {
    "passed": true,
    "fails": 0,
    "warns": 0,
    "declare": "配额 无，事件 world_painting，档位 中",
    "checked_at": "2026-08-27T12:00:01"
  }
}
```

| 字段 | 类型与语义 |
|---|---|
| `chapter` | 整数章号 |
| `chapter_file` | 正文文件的 basename，不是 stage 绝对路径，也不含正文目录前缀 |
| `chapter_mtime` | 数值 Unix 时间戳，兼容旧记录；不是 ISO 字符串 |
| `chapter_sha256` | 当次检查正文的字节哈希，优先用于写后改动检查 |
| `checked_at` | 正文机器检查时间的 ISO 字符串 |
| `passed` | 仅正文检查的通过状态，采用当次 `--fail-on` 口径，不是综合终态 |
| `blocking/advisory` | 正文检查的阻断/建议命中计数 |
| `ai_score` | 0–100 的机器 AI 味指标，不是文学质量评分，也不是 0–1 的 deslop_score |
| `categories` | 当次扫描统计字典；按运行模式变化，不是固定七字段 schema |
| `style_exemptions` | 本次实际生效的精确 B/G 文风豁免原记录数组；未生效为空，旧 gate 可缺省。仅记录章名、行号、整行、规则、理由和实际授权依据，不豁免其他门禁 |
| `rhythm` | 节奏工具合并的对象；未执行则可能缺失 |
| `rhythm.passed` | 节奏检查通过与否 |
| `rhythm.fails/warns` | CLI 写入的违规/警告数量（整数），具体文字在标准输出中 |
| `rhythm.declare` | 实际规范化的配额、事件、档位声明字符串 |
| `rhythm.checked_at` | 节奏检查时间 |

不存在 `checks.*`、`scores.*`、`created_at`、`updated_at` 或自动综合加权分数。
不得按这些字段读取当前 gate，也不得由 Agent 手填这些字段伪造机器检查。

## 合并与重新验证

1. `check_text.py --gate-state` 重建正文检查字段，保留已有的顶层 `rhythm` 对象。
   读取本书 `设定/文风豁免.json` 失败时退出 2，并写 `passed=false`、`style_policy_error`，不沿用旧成功。
   精确范围和 prepare 前登记要求见 `anti-ai-style.md`；记录不等于作者授权真实性经过机器证明。
2. `rhythm_guard.py --gate-state` 更新顶层 `rhythm`，不修改正文的 `passed` 或计算综合分数。
3. 因此正文重验后旧 `rhythm` 可能仍在；正文或配额变化后必须重跑两者。
4. `chapter_transaction.py validate` 在同一 stage 中顺序运行追踪校验、正文检查、
   节奏检查和实体索引构建，确认正文哈希及两个通过状态，再保存 staged 哈希。
5. 语义审查不写入机器 gate：机器脚本不会验证 Agent 发现，也不会自动把 P0 改成通过。
   总编辑必须真实复核所有 blocking/P0 已解决，才可使用 `--self-review-confirmed`。
6. 改完正文、追踪或 stage 中任何输入后，旧 validate 成功记录不可复用；必须重新 validate。
   `commit` 检查 stage 与 canonical 哈希，不接受过期的成功状态。

## 实际调用

先按章节事务 prepare 得到 `{stage}` 与 `{chapter_file}`。
下列单项命令用于诊断，不取代最终 validate/commit：

```bash
python scripts/check_text.py "{stage}/正文/{chapter_file}" --current-chapter {N} --min-chars {下限} --max-chars {上限} --ledger "{stage}/追踪/伏笔台账.md" --gate-report --gate-state
python scripts/rhythm_guard.py --chapter-file "{stage}/正文/{chapter_file}" --quota "{stage}/追踪/节奏配额.md" --chapter {N} --declare "{配额,事件类型,档位}" --gate-state
python scripts/chapter_transaction.py validate "{book}" --min-chars {下限} --max-chars {上限} --declare "{配额,事件类型,档位}"
python scripts/chapter_transaction.py commit "{book}" --self-review-confirmed
```

声明以减号开头时使用 `--declare=-,world_painting,中` 的等号形式。
命令失败后保留 pending draft，不发布、不覆盖正式文件。两轮定向修复仍有 blocking/P0，
报告 `gate_blocked` 并转作者裁决；换流程或模型不能重置次数。

## 跨会话消费者

- `resume.py`：检查 journal、最新章门禁、正文是否改动及追踪欠账。已记录的节奏失败是欠账。
- `check_text.py --verify-prev`：检查上一章文本门禁与已记录的节奏失败，优先用正文哈希，
  旧记录无哈希时使用 mtime；这是局部兼容检查，不能替代整书恢复报告或事务检查。
- 旧 gate 缺少 rhythm 时不能称为“完整验证”；使用章事务的 validate 补齐实际检查。
- `chapter_transaction.py commit`：以持久 journal 和 validate 哈希为准，不仅检查 passed。
- `validate_tracking.py`：校验追踪文件，不会凭空要求旧文档列出的所有人工报告和 meta 文件。
- 修订早期章节还要人工核对受影响的后续章节；只查最新章不能证明全书一致。

## 语义报告与统一发现格式

按任务需要执行 `references/craft/pacing-review.md`、
`references/craft/quality-checklist.md` 或编辑团队核查。报告放在 stage 外的本次工作目录，
注明章节、被审正文 SHA-256、时间和实际执行者；不要在 validate 后向 stage 塞额外报告文件。

跨角色汇总时每条发现记录：

| 字段 | 内容 |
|---|---|
| `id` | 本次报告内唯一标识 |
| `severity` | P0 阻断 / P1 建议 / P2 可选；原工具 blocking 必须映射 P0 |
| `category` | 如 continuity、style、pacing、ending、context |
| `evidence` | 文件位置、原文或事实来源，不能只有抽象评分 |
| `why_it_matters` | 对读者理解、人物动机或一致性的实际影响 |
| `minimal_fix` | 不新增未授权事件的最小修复 |
| `confidence` | 高/中/低；不确定的标需复核，不伪装成确定性命中 |
| `source` | 实际检查器/角色及来源记录 |

S1–S4 是一致性核查分类，不是另一套优先级；保留原分类并给出上述 severity。
机器 advisory 不自动升级为 blocking；人工判断升级必须提供具体证据。
最终结论用“阻断 / 通过但有建议 / 通过”，不得把残留 P0 描述为“有条件通过”。

## 人工扩展报告的边界

校对、质量评估、修复计划、文风校准、记忆更新、跨章待办和发布就绪报告可以按需生成，
但当前没有自动生成这些文件、合并 meta 或执行十一阶段流水线的脚本。
只为实际执行的步骤留证，不制造空报告凑数量。记忆更新最终仍落实到五表与实体索引，
不得用一份“memory_update”报告代替真实写回。发布报告也不等于作者已批准外部发布。

工作报告保留本次来源与处置；正文改变后旧报告标为过期，重新审核受影响部分。
journal/checkpoint 由事务工具管理，不手改；归档不等于删除失败证据。具体中断恢复、
外部编辑冲突和多文件提交边界以 `references/workflow/chapter-loop.md` 为准。
