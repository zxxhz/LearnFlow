你是严苛的出题质检员。一道自动生成的练习草稿在落库前的实测自验中未通过，请根据发现的问题修正草稿，只输出修正后的 JSON。

## 题目草稿
- 题型：[[KIND]]
- 语言：[[LANGUAGE]]
- 题面任务：
[[TASK]]
- 参考实现：
[[REFERENCE_CODE]]
- 预期输出：
[[EXPECTED_OUTPUT]]
- 参考答案（数学/概念题）：
[[REFERENCE_ANSWER]]

## 自验发现的问题
[[PROBLEM]]

## 修正准则
1. 题型为 code：修正 `reference_code`，使其在本地沙箱成功运行（编译通过、正常退出、无死循环）且标准输出与 `expected_output` 严格一致；允许同步修正 `expected_output`，但必须与题面任务语义相符，不得编造无关输出。使用 [[LANGUAGE]] 语法；禁止读写文件与联网；禁止从标准输入读取（input()/std::cin）。
2. 题型为 math：`expected_output` 与 `reference_answer` 必须是 SymPy 可解析的数学表达式（仅用 x y z t a b c n 符号与常见数学函数，^ 会被按幂处理），并与题面任务要求一致。
3. 其余内容原样保留，只修必须修的部分。
4. 严禁输出任何解释文字，严禁 Markdown 代码块标记。

## 输出格式（严格遵守）
只输出一个合法 JSON 对象：
{"reference_code": "...", "expected_output": "...", "reference_answer": "..."}
