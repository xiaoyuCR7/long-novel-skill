# 如何使用评测集

这是可运行的评测输入集，不是已通过的模型成绩单。

- `cases.json`：24 个原始任务与评阅标准，三类各8个、三题材覆盖。模型只接收 prepare 输出的输入与 prompt。
- `retrieval.json`：12 个合成文档和12个检索问题，含多证据答案。
- `scripts/skill_eval.py`：校验、准备、记录工件、BM25 合成检索指标。命令从 Skill 根目录运行。

完整流程与证据限制见 `references/workflow/evidence-review.md`。真实运行输出放在工程外新目录，
不能覆盖现有书籍，不把本目录的 criteria 传给被测 Agent。缺少模型调用、轨迹或人工评阅时明确 not_run。
