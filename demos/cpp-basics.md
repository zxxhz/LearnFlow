# C++ 基础语法

面向已有 Python 基础的 C++ 入门。文档内 ` ```cpp ` 代码块可一键编译运行（需要本机安装 [MinGW-w64](https://www.mingw-w64.org/) 的 g++ 并加入 PATH；未安装时应用会给出友好提示）。

## 第一个程序

C++ 是编译型语言：源码先被 g++ 编译成可执行文件，再运行。每个程序都从 `main()` 函数开始执行。

```cpp
#include <iostream>   // 输入输出库

int main() {
    std::cout << "Hello, LearnFlow!" << std::endl;
    std::cout << "1 + 2 = " << 1 + 2 << "\n";
    return 0;         // main 返回 0 表示正常结束
}
```

`#include` 相当于 Python 的 import；`std::` 是标准库的命名空间。写 `using namespace std;` 之后就可以省略前缀（小项目常用，大工程不推荐）。

```cpp
#include <iostream>
#include <string>
using namespace std;

int main() {
    string name = "C++";
    cout << "Hello, " << name << "!\n";
    cout << "这行没有 std:: 前缀\n";
    return 0;
}
```

## 变量与基本类型

和 Python 不同，C++ 变量必须**先声明类型**：`int` 整数、`double` 浮点、`char` 字符、`bool` 布尔、`string` 字符串。

```cpp
#include <iostream>
using namespace std;

int main() {
    int age = 25;
    double price = 19.99;
    char grade = 'A';            // 单引号是字符
    bool ok = true;              // 输出时是 1/0
    string name = "LearnFlow";   // 双引号是字符串

    cout << age << " " << price << " " << grade << " " << ok << "\n";
    cout << name << " 名字长度: " << name.length() << "\n";

    int guess = price;           // 隐式转换：小数截断为 19（会有警告风险，显式写更好）
    int price2 = static_cast<int>(price);
    cout << "转换: " << guess << " / " << price2 << "\n";
    return 0;
}
```

`const` 定义不可修改的量；`auto` 让编译器自己推断类型（C++11 起）。

```cpp
#include <iostream>
#include <string>
using namespace std;

int main() {
    const double PI = 3.14159;   // 常量，赋值后不能改
    auto n = 42;                 // auto -> int
    auto s = string("inferred"); // auto -> string

    cout << PI / 2 << " " << n << " " << s << "\n";
    return 0;
}
```

## 控制流

`if / else if / else`、`switch`、`for`、`while` 与 Python 语义相同，但条件必须加括号，代码块用大括号。

```cpp
#include <iostream>
using namespace std;

int main() {
    int score = 82;

    if (score >= 90) {
        cout << "优秀\n";
    } else if (score >= 80) {
        cout << "良好\n";
    } else if (score >= 60) {
        cout << "及格\n";
    } else {
        cout << "不及格\n";
    }

    int day = 3;
    switch (day) {
        case 1: cout << "周一\n"; break;
        case 3: cout << "周三\n"; break;
        default: cout << "其他\n"; break;   // 没有 break 会“贯穿”到下一个 case
    }
    return 0;
}
```

`for (int i = 1; i <= 5; i++)` 三段式是经典写法；`for (int x : arr)` 是范围 for，类似 Python 的 `for x in arr`。

```cpp
#include <iostream>
using namespace std;

int main() {
    for (int i = 1; i <= 5; i++) cout << i << " ";
    cout << "\n";

    int total = 0, n = 1;
    while (n <= 100) {
        total += n;
        n++;
    }
    cout << "1+2+...+100 = " << total << "\n";

    int nums[] = {3, 1, 4, 1, 5};
    for (int x : nums) {                  // 范围 for
        if (x % 2 == 0) continue;         // 跳过偶数
        if (x > 4) break;                 // 超过 4 结束
        cout << "奇数: " << x << "\n";
    }
    return 0;
}
```

## 函数

函数必须先声明类型：返回值类型写在函数名前。参数默认**按值传递**（拷贝一份），加 `&` 则是**按引用传递**（能修改原变量）。

```cpp
#include <iostream>
using namespace std;

int add(int a, int b) {
    return a + b;
}

// 按引用传递：swap 真正交换两个变量
void swap(int &a, int &b) {
    int tmp = a;
    a = b;
    b = tmp;
}

int main() {
    cout << "add(3, 4) = " << add(3, 4) << "\n";

    int x = 1, y = 9;
    swap(x, y);
    cout << "swap 后: x=" << x << " y=" << y << "\n";
    return 0;
}
```

同名函数可以**重载**（参数不同即可）；参数可以带默认值。

```cpp
#include <iostream>
using namespace std;

int area(int side) {                 // 正方形
    return side * side;
}

double area(double w, double h) {    // 长方形：重载
    return w * h;
}

int area(int w, int h, int offset = 0) {  // 默认参数：预留边距
    return w * h + offset;
}

int main() {
    cout << area(5) << " " << area(2.5, 4.0) << " " << area(3, 4, 2) << "\n";
    return 0;
}
```

## 数组与 vector

原生数组大小固定；实际开发更常用 `std::vector`——可以动态增长的数组，带 `size() / push_back()` 等方法。

```cpp
#include <iostream>
#include <vector>
using namespace std;

int main() {
    int arr[5] = {3, 1, 4, 1, 5};            // 原生数组：大小固定
    cout << "arr[0]=" << arr[0] << "\n";

    vector<int> v = {3, 1, 4};               // vector：动态数组
    v.push_back(1);                          // 追加元素
    v.push_back(5);

    cout << "长度: " << v.size() << ", 元素:";
    for (int x : v) cout << " " << x;
    cout << "\n";

    v[0] = 9;                                // 下标修改
    cout << "第一个元素改为: " << v.front() << ", 最后: " << v.back() << "\n";
    return 0;
}
```

`std::string` 本质也是字符容器，和 vector 用法一致；常用函数见例子。

```cpp
#include <iostream>
#include <string>
using namespace std;

int main() {
    string s = "LearnFlow";
    cout << s.substr(0, 5) << " " << s[s.size() - 1] << "\n";

    string text = "the quick brown fox the end";
    int count = 0;
    string word = "the";
    size_t pos = text.find(word);
    while (pos != string::npos) {            // npos 表示“没找到”
        count++;
        pos = text.find(word, pos + 1);
    }
    cout << "'" << word << "' 出现 " << count << " 次\n";
    return 0;
}
```

## 结构体与 map

`struct` 把不同类型的值打包成一个新类型——没有类的继承时，它就是轻量的自定义类型。`std::map` 是有序键值容器，类似 Python 的 dict。

```cpp
#include <iostream>
#include <map>
#include <string>
#include <vector>
using namespace std;

struct Student {
    string name;
    int score;
};

int main() {
    vector<Student> roster = {
        {"Alice", 92}, {"Bob", 78}, {"Carol", 85},
    };

    map<string, int> byName;                 // 键自动按字典序排列
    for (const Student &s : roster) {
        byName[s.name] = s.score;
    }

    int best = 0;
    string who;
    for (const Student &s : roster) {
        cout << s.name << ": " << s.score << "\n";
        if (s.score > best) { best = s.score; who = s.name; }
    }
    cout << "最高分: " << who << " " << byName[who] << "\n";
    return 0;
}
```

## 综合：猜数字（自动模拟）

一个把变量、循环、条件、函数全用上的小程序。因为没有人工输入（沙箱stdin是关闭的），这里让电脑自己"猜"自己"答"。

```cpp
#include <iostream>
using namespace std;

int secret = 42;                      // 目标数字

// 电脑用二分法猜：返回猜测次数
int guess_game() {
    int lo = 1, hi = 100, times = 0;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        times++;
        cout << "猜 " << mid;
        if (mid == secret) {
            cout << " -> 猜中了！\n";
            return times;
        } else if (mid < secret) {
            cout << " -> 太小\n";
            lo = mid + 1;
        } else {
            cout << " -> 太大\n";
            hi = mid - 1;
        }
    }
    return times;
}

int main() {
    int used = guess_game();
    cout << "二分法共猜了 " << used << " 次\n";
    return 0;
}
```
