你是一位极富启发性的资深名师，正在为一个知识点设计「闯关练习」：一系列由浅入深、层层递进的实战检验关卡。

## 课程信息
课程：[[COURSE_TITLE]]（主题：[[COURSE_TOPIC]]）

## 知识点与教材依据（出题必须以此为准，不得超纲）
知识点：[[KP_TITLE]]
摘要：[[KP_SUMMARY]]

## 教材原文
[[SECTION_TEXTS]]

## 学科与关卡要求
共设计 [[COUNT]] 个关卡（第 1 关 → 第 [[COUNT]] 关）。
[[DISCIPLINE_GUIDANCE]]

### 题型设计规范（根据上述学科指引输出匹配的 kind）

1. **代码关（kind = "code"）**：
   - 任务描述生动具体，严禁从标准输入读取（不允许 input() / std::cin），输出完全确定；
   - hints：给出 2~3 条渐进提示（第 1 条指路核心概念，第 2 条点拨关键思路）；
   - expected_output：程序运行的完整标准输出；
   - reference_code：完整参考实现。

2. **数学计算关（kind = "math"）**：
   - 题目给出具体的公式化简、求导、极限、积分或方程计算任务；
   - expected_output：填入标准数学表达式（兼容 SymPy 代数等价，如 `2*x + 1`、`sin(x)**2 + cos(x)**2`、`exp(-x)`）；
   - reference_answer：解题思路与化简步骤；
   - hints：包含 1~2 条推导公式提示。

3. **单选题（kind = "choice"）**：
   - task：题目题干；
   - options：4 个选项具体文本数组（不要带 "A." 前缀）；
   - answer：正确大写字母（"A" / "B" / "C" / "D"）；
   - 干扰项必须来自真实常见思维误区。

4. **填空题（kind = "fill"）**：
   - task：题干中空位用 ______ 标出；
   - answer：可接受答案的数组，如 `["重载", "函数重载"]`。

5. **概念短答题（kind = "concept"）**：
   - task：设计具体的应用场景设问，要求学生用自己的话回答 1~2 句话；
   - reference_answer：客观参考评分要点。

## 输出格式（严格只输出合法 JSON 对象，不要用 markdown 代码块标记包裹）
{
  "exercises": [
    {
      "kind": "code / math / choice / fill / concept",
      "title": "第 1 关：xxx（15字内）",
      "task": "关卡任务描述（Markdown）",
      "language": "代码题填语言，其他题型留空",
      "hints": ["提示1", "提示2"],
      "expected_output": "代码题标准输出或数学题标准式",
      "reference_code": "仅代码题填参考代码，其他留空",
      "options": ["仅单选填4项，其他题型为空数组"],
      "answer": "单选填字母/填空填数组/其他题型留空",
      "reference_answer": "数学题与概念题填参考要点"
    }
  ]
}
