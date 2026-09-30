# Python 基础语法

零基础友好的 Python 语法速览。文档内所有 ` ```python ` 代码块右上角都有「▶ 运行」按钮，点一下就能看到输出（LearnFlow 安装版内置了 Python 运行环境）。

## 变量与数据类型

Python 不用声明类型，赋值即创建。基础类型四种：整数 `int`、浮点数 `float`、字符串 `str`、布尔值 `bool`。

```python
age = 25                # int
price = 19.99           # float
name = "LearnFlow"      # str（单双引号等价）
ok = True               # bool（注意大写开头）

print(type(age), type(price), type(name), type(ok))

# f-string 格式化：最常用的拼接方式
print(f"{name} 已经 {age} 岁，价格 {price:.1f} 元")

# 类型转换
n = int("42")           # 字符串 -> 整数
s = str(3.14)           # 数字 -> 字符串
print(n + 8, "|" + s + "|")
```

动态类型的另一面：同一个名字可以随时指向不同类型的值，`type()` 随时帮你确认。

```python
x = 100
print(x, type(x).__name__)
x = "now a string"
print(x, type(x).__name__)
```

## 控制流

条件用 `if / elif / else`，注意 Python 用**缩进**表示代码块（约定 4 个空格），不需要大括号。

```python
score = 82

if score >= 90:
    grade = "优秀"
elif score >= 80:
    grade = "良好"
elif score >= 60:
    grade = "及格"
else:
    grade = "不及格"

print(f"分数 {score} -> {grade}")
```

循环有两种：`for ... in range(...)` 遍历数字区间，`while` 按条件重复。`break` 跳出整层循环，`continue` 跳过本轮。

```python
for i in range(1, 6):        # 1 2 3 4 5，含头不含尾
    print(i, end=" ")
print()

total = 0
n = 1
while n <= 100:
    total += n
    n += 1
print("1+2+...+100 =", total)

for i in range(1, 10):
    if i % 2 == 0:
        continue             # 跳过偶数
    if i > 7:
        break                # 超过 7 就结束
    print("奇数:", i)
```

## 常用数据结构

四容器一句话记忆：`list` 有序可变，`tuple` 有序不可变，`dict` 键值映射，`set` 去重。

```python
langs = ["Python", "C++", "Rust"]        # list：增删改都行
langs.append("Go")
print(langs, "长度:", len(langs))
print(langs[0], langs[-1])               # 下标从 0 开始；-1 是最后一个

point = (3, 5)                           # tuple：不可修改
x, y = point                             # 解包
print(f"坐标 ({x}, {y})")

scores = {"Alice": 92, "Bob": 78}        # dict：键 -> 值
scores["Carol"] = 85
for name, s in scores.items():
    print(f"{name}: {s}")

nums = [3, 1, 3, 2, 1]
print("去重:", set(nums), "排序:", sorted(nums))
```

推导式是 Python 的招牌写法，一行完成"过滤 + 变换"。

```python
squares = [n * n for n in range(1, 6)]
print(squares)

evens = [n for n in range(20) if n % 2 == 0]
print(evens)

lengths = {w: len(w) for w in ["apple", "pear", "fig"]}
print(lengths)
```

## 函数

用 `def` 定义函数。参数可以带默认值；`*args` 收集多余位置参数，`**kwargs` 收集关键字参数。

```python
def greet(name, punctuation="!"):
    return f"Hello, {name}{punctuation}"

def summarize(*args, **kwargs):
    print("位置参数:", args)
    print("关键字参数:", kwargs)

print(greet("LearnFlow"))
print(greet("World", punctuation="?"))
summarize(1, 2, 3, mode="fast", limit=10)
```

函数也是对象，可以当参数传；`lambda` 适合写一行的小函数，常与 `sorted` 搭配。

```python
def apply(f, value):
    return f(value)

double = lambda n: n * 2
print(apply(double, 21), apply(lambda n: n + 1, 9))

pairs = [("b", 2), ("a", 3), ("c", 1)]
print(sorted(pairs, key=lambda p: p[1]))    # 按第二个元素排序
```

## 字符串处理

字符串不可变，所有"修改"都返回新字符串。切片 `[start:stop:step]` 是高频操作。

```python
s = "LearnFlow Learning Agent"

print(s.upper(), s.lower())
print(s.replace("Agent", "助手"))
print("切片:", s[:9], "|", s[-5:], "|", s[::2])
print("拆分:", s.split(" ", 1))
print("拼接:", "-".join(["2026", "09", "30"]))
print("查找:", s.find("Flow"), "Flow" in s)
```

实战小例子：统计一段文本的词频。

```python
text = "the quick brown fox jumps over the lazy dog the end"
counts = {}
for word in text.split():
    counts[word] = counts.get(word, 0) + 1

top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
print("出现最多的词:", top)
```

## 异常与文件

用 `try / except / finally` 优雅地处理错误，而不是让程序崩溃。`raise` 主动抛出异常。

```python
def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return "除数不能为 0"
    finally:
        print(f"  (safe_divide 被调用: {a}/{b})")

print(safe_divide(10, 2))
print(safe_divide(1, 0))
```

`with open(...)` 自动在结束时关闭文件，不怕忘记。沙箱的工作目录是一次性临时目录，写读同路径的文件没有问题。

```python
with open("demo.txt", "w", encoding="utf-8") as f:
    f.write("第一行\n第二行\n第三行\n")

with open("demo.txt", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        print(i, line.strip())
```
