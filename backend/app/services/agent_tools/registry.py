"""学习 Agent 本地工具箱：提供受限沙箱运行、数学函数绘图、关卡自省与旧知/错题检索能力。

v0.5.6 全量工具扩权：课程/讲义/练习/题库/导图/批注/画像/学习数据/备份/同步的
用户可操作面统一开放为 agent 工具。读类免确认；写类一律经学员确认卡放行
（SENSITIVE_TOOLS / DESTRUCTIVE_TOOLS 分级见下）；提交作答与安全配置类操作
（LLM 密钥、中转、局域网、令牌、镜像、应用内更新安装、工具链安装、备份恢复）
刻意不设工具，见 prompt 操作准则与仓库安全边界。
"""
import asyncio
import json
import logging
import shutil
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_id, utcnow_iso
from app.services.execution.runner import run_code

logger = logging.getLogger(__name__)

# OpenAI 兼容协议工具声明定义
AGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "run_sandbox_code",
            "description": (
                "在受限安全沙箱中编译并真实运行 Python 或 C++ 代码，"
                "返回 stdout、stderr、exit_code 和执行状态。用于验证代码、排查错误、重现 bug 或测试运行结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要运行的代码完整文本"},
                    "language": {
                        "type": "string",
                        "enum": ["python", "cpp"],
                        "description": "代码语言（python 或 cpp）",
                    },
                },
                "required": ["code", "language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_math_plot",
            "description": (
                "使用 SymPy 解析并用 Matplotlib 渲染一维数学函数图像为矢量 SVG。"
                "用于帮助学生直观理解函数曲线、极值、奇点和图像性质。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expressions": {
                        "type": "string",
                        "description": "要绘制的函数表达式（多个函数用换行隔开，例如 'sin(x)/x' 或 'x**2'）",
                    },
                    "x_min": {
                        "type": "number",
                        "description": "x 轴起始范围（默认 -10）",
                        "default": -10.0,
                    },
                    "x_max": {
                        "type": "number",
                        "description": "x 轴结束范围（默认 10）",
                        "default": 10.0,
                    },
                },
                "required": ["expressions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_exercise",
            "description": "查询特定练习题或关卡的题面任务、提示信息、预期目标输出和参考实现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_id": {
                        "type": "string",
                        "description": "练习题或关卡的 ID",
                    }
                },
                "required": ["exercise_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_learned_section",
            "description": (
                "检索学员已学过的课程章节原文片段（按章节标题/知识点标题/正文关键词匹配）。"
                "用于引用学员以前学过的具体例子、定义或推导来类比当前新概念。"
                "注意：先扫视系统提示中的已学知识骨架目录选好类比锚点，再用本工具取细节。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "检索关键词，如知识点名、章节标题或术语（2~12 字效果最佳）",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_past_mistakes",
            "description": (
                "检索学员以前做错的课程练习与题库错题（按题目标题/题面/作答内容关键词匹配）。"
                "用于发现当前卡点与历史错误的关联，提醒学员不要再踩同一个坑。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "检索关键词，如错误主题、知识点名或术语",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    # ===== v0.5.6 全量工具扩权：读类（免确认） =====
    {
        "type": "function",
        "function": {
            "name": "search_learned_content",
            "description": (
                "全文检索所有已学讲义内容（FTS 全局搜索，比 lookup_learned_section 覆盖面更广）。"
                "回答「我之前在哪学过XX」类问题时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，可含多个空格分隔的关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_courses",
            "description": "查看学员的全部课程列表（含每章生成进度）。用于回答「我有哪些课」「学到哪了」。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_detail",
            "description": "查看某门课程的章节清单与状态。参数来自 list_courses 返回的 id。",
            "parameters": {
                "type": "object",
                "properties": {"course_id": {"type": "string", "description": "课程 ID"}},
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "阅读某章讲义正文（含小节目录）。用于需要引用原文细节、核对概念表述时；"
                "先看本提示的已学目录选章，再调本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "章节文档 ID"},
                    "section_id": {
                        "type": "string",
                        "description": "可选：只读某个小节（来自返回的小节目录）",
                    },
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_exercises",
            "description": "查看某章的闯关练习列表与学员作答状态（题目内容已脱敏）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_wrong_questions",
            "description": "查看错题本：最近一次作答未通过的闯关练习（跨课程），含作答与知识点归属。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_study_report",
            "description": "查看学习报告：各课程章节进度、薄弱知识点、学习时长热力、Token 用量。回答「我最近学得怎么样」。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_learner_profile",
            "description": "查看学习者画像与当前活跃的认知盲区（含证据溯源）。用于因材施教与盲区跟进。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_banks",
            "description": "查看全部题库及统计（题量/已答/正确率/错题数）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_bank_round",
            "description": (
                "从题库抽一轮题预览（题面已脱敏不含答案）。用于带学员复习、选题讲解；"
                "mode: all=随机 / new=只做新题 / wrong=错题重刷。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {"type": "string", "description": "题库 ID"},
                    "mode": {"type": "string", "enum": ["all", "new", "wrong"], "description": "抽题模式"},
                    "size": {"type": "integer", "description": "抽题数量（1-20，默认 5）"},
                },
                "required": ["bank_id", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mindmaps",
            "description": "查看全部思维导图列表（标题/节点数/来源）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mindmap",
            "description": "查看某张思维导图的结构大纲（限深展示，节点含 id）。编辑导图前先看结构。",
            "parameters": {
                "type": "object",
                "properties": {"map_id": {"type": "string", "description": "导图 ID"}},
                "required": ["map_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_annotations",
            "description": "查看某章讲义的划线与批注列表（颜色/备注/状态）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_app_update",
            "description": "检查 LearnFlow 桌面端是否有新版本（只读检查，不安装）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_backups",
            "description": "查看本地数据备份文件列表（名称/大小/时间）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sync_status",
            "description": "查看与云端中转服务端的连接状态与同步配置。"
        },
    },
    # ===== v0.5.6 全量工具扩权：写类（执行前弹学员授权确认卡） =====
    {
        "type": "function",
        "function": {
            "name": "create_course",
            "description": (
                "按主题创建一门新课：AI 生成课程大纲并落库，默认同时启动后台逐章生成讲义。"
                "仅当学员明确要求开新课/规划新课表时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "课程主题（1-200 字）"},
                    "level": {"type": "string", "description": "可选难度描述，如 入门/进阶"},
                    "chapter_count": {"type": "integer", "description": "可选期望章数（不填由 AI 定）"},
                    "start_generation": {
                        "type": "boolean",
                        "description": "是否立即开始生成讲义（默认 true；false 只出大纲草稿）",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_course_material",
            "description": (
                "把一段 Markdown 学习材料导入为新课程（自动切章、重建小节索引、尝试提取知识点）。"
                "材料应带清晰标题层级（# / ##）。适合「把这段笔记变成一门课」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "课程标题"},
                    "markdown": {"type": "string", "description": "完整 Markdown 材料文本"},
                },
                "required": ["title", "markdown"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regenerate_document",
            "description": (
                "重新生成某章讲义（后台任务，会替换该章正文并清理派生数据；导入的章节禁止重生）。"
                "需向学员复述影响后再调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "章节文档 ID"}},
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_section",
            "description": (
                "对讲义某个小节做手术式修订：AI 按学员要求审校并替换该段正文（替换前自动审校核查）。"
                "用于「这段讲错了/帮我改写这段」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "章节文档 ID"},
                    "section_id": {"type": "string", "description": "小节 ID（来自 read_document）"},
                    "instruction": {"type": "string", "description": "修订要求"},
                },
                "required": ["document_id", "section_id", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_exercises",
            "description": (
                "为知识点生成闯关练习（会替换该知识点下的全部旧关卡）。"
                "用于学员主动要求加练/换题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_point_id": {"type": "string", "description": "知识点 ID"},
                    "count": {"type": "integer", "description": "题目数量（0=用偏好设置）"},
                    "language": {"type": "string", "enum": ["python", "cpp"], "description": "代码题语言（默认 python）"},
                },
                "required": ["knowledge_point_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_quiz",
            "description": "为某章生成一份跨知识点随堂小测。",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "章节文档 ID"},
                    "kp_ids": {"type": "array", "items": {"type": "string"}, "description": "可选：限定知识点（默认取该章全部）"},
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_bridge_exercises",
            "description": "为学员卡住的主线难题生成 1-2 道阶梯式搭桥小题。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_hard_bone",
            "description": "切换练习题的「硬骨头」攻坚标记（暂跳过、日后专攻）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_id": {"type": "string", "description": "练习题 ID"},
                    "on": {"type": "boolean", "description": "可选：true=标记 / false=取消（缺省=翻转）"},
                },
                "required": ["exercise_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_bank_questions",
            "description": (
                "把一段杂乱试题文本智能切题后追加到指定题库。适合「把这几道题加进我的题库」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {"type": "string", "description": "题库 ID"},
                    "text": {"type": "string", "description": "试题文本（多题连排也可）"},
                },
                "required": ["bank_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correct_bank_question",
            "description": (
                "纠错改题：修改题库题目的题面/选项/答案/解析，并自动重判全部历史作答、更新错题池。"
                "仅当确凿核实原题有误时使用，需向学员说明依据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string", "description": "题目 ID（来自 draw_bank_round）"},
                    "title": {"type": "string", "description": "新题面（不修改则省略）"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "新选项列表（2-8 项）"},
                    "answer": {"type": "string", "description": "新答案字母，多选逗号分隔，如 B 或 A,C,D"},
                    "explanation": {"type": "string", "description": "新解析"},
                },
                "required": ["question_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_bank_prompt",
            "description": "设置题库的自定义答疑提示词（影响该库错题 AI 深度解析的风格）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_id": {"type": "string", "description": "题库 ID"},
                    "prompt": {"type": "string", "description": "提示词全文（空串恢复默认）"},
                },
                "required": ["bank_id", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_mindmap",
            "description": (
                "生成一张思维导图并保存到导图库：可按主题、按参考材料或按整门课程。"
                "学员说「画个导图/整理成思维导图」时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "导图主题（与 course_id 二选一）"},
                    "course_id": {"type": "string", "description": "按整门课程生成（与 topic 二选一）"},
                    "source_text": {"type": "string", "description": "可选参考材料（与 topic 搭配）"},
                    "depth": {"type": "integer", "description": "层级深度 2-5（默认 3）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_mindmap",
            "description": (
                "对已有导图做结构化编辑（先 get_mindmap 拿节点 id）：添加子分支/重命名/写节点详解/删除分支。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "map_id": {"type": "string", "description": "导图 ID"},
                    "operations": {
                        "type": "array",
                        "description": "编辑操作列表，按顺序执行",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "enum": ["add_child", "rename", "set_detail", "delete"]},
                                "node_id": {"type": "string", "description": "目标节点 id"},
                                "title": {"type": "string", "description": "rename 的新标题；add_child 的子分支标题"},
                                "detail": {"type": "string", "description": "set_detail 的节点详解 Markdown"},
                                "summary": {"type": "string", "description": "add_child 的子分支简述"},
                            },
                            "required": ["action", "node_id"],
                        },
                    },
                },
                "required": ["map_id", "operations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_annotation",
            "description": (
                "在讲义某小节为学员新建一条划线批注。exact 必须与小节原文逐字一致（先 read_document 取原文）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "章节文档 ID"},
                    "section_id": {"type": "string", "description": "小节 ID（来自 read_document）"},
                    "exact": {"type": "string", "description": "划线原文（逐字精确）"},
                    "note": {"type": "string", "description": "批注内容"},
                    "color": {"type": "string", "enum": ["yellow", "green", "blue", "pink"], "description": "高亮色"},
                },
                "required": ["document_id", "section_id", "exact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_learner_profile",
            "description": "更新学习者画像：背景描述或苏格拉底启发式开关。仅在学员明确提出时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "background": {"type": "string", "description": "学员背景描述（学习基础/目标/偏好）"},
                    "socratic_enabled": {"type": "boolean", "description": "是否启用苏格拉底启发式答疑"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_misconception",
            "description": "把某条认知盲区标记为已解决（学员确认已掌握该易错点时）。",
            "parameters": {
                "type": "object",
                "properties": {"misconception_id": {"type": "string", "description": "盲区记录 ID（来自 get_learner_profile）"}},
                "required": ["misconception_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_backup",
            "description": "立即创建一次本地数据全量备份（zip，含数据库/讲义/题库）。"
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_sync",
            "description": (
                "触发与云端服务端的双向数据同步（会合并/覆盖数据，耗时较长）。"
                "仅当学员明确要求同步时使用，并说明方向。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["both", "push", "pull"], "description": "both=双向 / push=推送本地到云端 / pull=拉取云端到本地"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_resource",
            "description": (
                "删除一个资源（course=课程 / bank=题库 / exercise=练习题 / quiz=小测 / "
                "mindmap=导图 / annotation=划线 / backup=备份）。不可恢复，必须先向学员复述将删除什么。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["course", "bank", "exercise", "quiz", "mindmap", "annotation", "backup"],
                    },
                    "id": {"type": "string", "description": "资源 ID（backup 用文件名）"},
                },
                "required": ["kind", "id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_resource_title",
            "description": "重命名资源（course=课程 / bank=题库 / mindmap=导图）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["course", "bank", "mindmap"]},
                    "id": {"type": "string", "description": "资源 ID"},
                    "title": {"type": "string", "description": "新标题"},
                },
                "required": ["kind", "id", "title"],
            },
        },
    },
]


# 执行前必须经学员授权确认卡放行的高影响工具（v0.5.1 建立的沙箱闸门 + v0.5.6 扩展到全部写类）
SENSITIVE_TOOLS = {
    "run_sandbox_code",
    "create_course",
    "import_course_material",
    "regenerate_document",
    "revise_section",
    "generate_exercises",
    "generate_quiz",
    "generate_bridge_exercises",
    "toggle_hard_bone",
    "add_bank_questions",
    "correct_bank_question",
    "set_bank_prompt",
    "create_mindmap",
    "edit_mindmap",
    "create_annotation",
    "update_learner_profile",
    "resolve_misconception",
    "create_backup",
    "trigger_sync",
    "delete_resource",
    "update_resource_title",
}

# 破坏性/覆盖性操作子集：前端确认卡用红色警示文案，提示词要求先复述影响
DESTRUCTIVE_TOOLS = {"regenerate_document", "trigger_sync", "delete_resource"}

# 工具中文名（前端确认卡与状态行展示用；与 schema 一一对应）
TOOL_LABELS: dict[str, str] = {
    "run_sandbox_code": "沙箱运行代码",
    "render_math_plot": "绘制函数图像",
    "inspect_exercise": "查看练习详情",
    "lookup_learned_section": "检索已学小节",
    "lookup_past_mistakes": "检索历史错题",
    "search_learned_content": "全文搜索已学内容",
    "list_courses": "查看课程列表",
    "get_course_detail": "查看课程详情",
    "read_document": "阅读章节讲义",
    "list_exercises": "查看章节练习",
    "list_wrong_questions": "查看错题本",
    "get_study_report": "查看学习报告",
    "get_learner_profile": "查看学习者画像",
    "list_banks": "查看题库列表",
    "draw_bank_round": "题库抽题预览",
    "list_mindmaps": "查看导图列表",
    "get_mindmap": "查看思维导图",
    "list_annotations": "查看划线批注",
    "check_app_update": "检查应用更新",
    "list_backups": "查看备份列表",
    "get_sync_status": "查看同步状态",
    "create_course": "创建课程",
    "import_course_material": "导入材料建课",
    "regenerate_document": "重新生成本章",
    "revise_section": "修订小节",
    "generate_exercises": "生成练习关卡",
    "generate_quiz": "生成随堂小测",
    "generate_bridge_exercises": "生成搭桥小题",
    "toggle_hard_bone": "切换硬骨头标记",
    "add_bank_questions": "题库追加题目",
    "correct_bank_question": "题库纠错改题",
    "set_bank_prompt": "设置题库提示词",
    "create_mindmap": "生成思维导图",
    "edit_mindmap": "编辑思维导图",
    "create_annotation": "新建划线批注",
    "update_learner_profile": "更新学习者画像",
    "resolve_misconception": "移除认知盲区",
    "create_backup": "创建备份",
    "trigger_sync": "触发云端同步",
    "delete_resource": "删除资源",
    "update_resource_title": "重命名资源",
}


def _schema_names(names: list[str]) -> list[dict[str, Any]]:
    by_name = {s["function"]["name"]: s for s in AGENT_TOOLS_SCHEMA}
    return [by_name[n] for n in names if n in by_name]


# 各归属域可见工具集：核心答疑集所有场景通用，域集按会话归属裁剪，
# 避免全量 schema（38 个）每轮全量注入撑爆上下文与模型注意力
_CORE_TOOLS = [
    "run_sandbox_code",
    "render_math_plot",
    "inspect_exercise",
    "lookup_learned_section",
    "lookup_past_mistakes",
    "search_learned_content",
    "get_study_report",
    "get_learner_profile",
    "resolve_misconception",
    "update_learner_profile",
]
_DOCUMENT_TOOLS = [
    "read_document",
    "list_courses",
    "get_course_detail",
    "list_exercises",
    "list_wrong_questions",
    "list_annotations",
    "create_annotation",
    "generate_exercises",
    "generate_quiz",
    "generate_bridge_exercises",
    "toggle_hard_bone",
    "revise_section",
    "regenerate_document",
    "create_mindmap",
    "edit_mindmap",
    "list_mindmaps",
    "get_mindmap",
    "delete_resource",
    "update_resource_title",
]
_BANK_TOOLS = [
    "list_banks",
    "draw_bank_round",
    "list_wrong_questions",
    "add_bank_questions",
    "correct_bank_question",
    "set_bank_prompt",
    "delete_resource",
    "update_resource_title",
]
_GLOBAL_TOOLS = [s["function"]["name"] for s in AGENT_TOOLS_SCHEMA]

TOOL_SETS: dict[str, list[str]] = {
    "document": _CORE_TOOLS + _DOCUMENT_TOOLS,
    "bank_question": _CORE_TOOLS + _BANK_TOOLS,
    "global": _GLOBAL_TOOLS,
}


def select_tool_schemas(context_type: str) -> list[dict[str, Any]]:
    """按会话归属域裁剪注入给模型的工具 schema（未知域回落全量，兼容旧数据）。"""
    return _schema_names(TOOL_SETS.get(context_type, _GLOBAL_TOOLS))


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _tool_lookup_learned_section(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.models import Document, KnowledgePoint, Section

    keyword = str(args.get("keyword") or "").strip()
    if not keyword or db is None:
        return {"error": "缺少检索关键词或数据库上下文"}

    exclude_doc = ""
    ctx = args.get("_ctx") or {}
    if isinstance(ctx, dict):
        exclude_doc = str(ctx.get("exclude_document_id") or "")

    like = f"%{keyword}%"
    cond = [
        Document.title.like(like),
        Document.summary.like(like),
        KnowledgePoint.title.like(like),
        KnowledgePoint.summary.like(like),
        Section.text_excerpt.like(like),
        Section.heading_path.like(like),
    ]
    stmt = (
        select(Section, Document)
        .join(Document, Document.id == Section.document_id)
        .outerjoin(KnowledgePoint, KnowledgePoint.document_id == Document.id)
        .where(Document.status == "done", or_(*cond))
        .order_by(Section.document_id, Section.order_index)
        .limit(12)
    )
    if exclude_doc:
        stmt = stmt.where(Section.document_id != exclude_doc)

    rows = (await db.execute(stmt)).all()

    hits: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for sec, doc in rows:
        if doc.id in seen_docs:
            continue
        seen_docs.add(doc.id)
        heading = ""
        try:
            hp = json.loads(sec.heading_path) if sec.heading_path else []
            heading = " > ".join(str(x) for x in hp)
        except Exception:  # noqa: BLE001
            heading = ""
        excerpt = _clip(sec.text_excerpt or "", 500)
        if not excerpt:
            continue
        references = [
            {
                "label": f"关联已学：《{doc.title}》" + (f" · {heading}" if heading else ""),
                "href": f"/read/{doc.id}?section={sec.id}",
            }
        ]
        hits.append(
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "chapter_index": doc.chapter_index,
                "heading": heading,
                "excerpt": excerpt,
                "references": references,
            }
        )
        if len(hits) >= 3:
            break

    if not hits:
        return {"status": "not_found", "message": f"没有在已学课程中检索到与「{keyword}」相关的章节"}
    return {"status": "success", "hits": hits}


async def _tool_lookup_past_mistakes(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.models import BankAttempt, BankQuestion, Document, Exercise, ExerciseAttempt, KnowledgePoint

    keyword = str(args.get("keyword") or "").strip()
    if not keyword or db is None:
        return {"error": "缺少检索关键词或数据库上下文"}

    like = f"%{keyword}%"
    hits: list[dict[str, Any]] = []

    # 课程练习错题（只看从未通过的最近一次失败作答）
    ex_rows = (
        await db.execute(
            select(ExerciseAttempt, Exercise, Document)
            .join(Exercise, Exercise.id == ExerciseAttempt.exercise_id)
            .outerjoin(Document, Document.id == Exercise.document_id)
            .outerjoin(KnowledgePoint, KnowledgePoint.id == Exercise.knowledge_point_id)
            .where(
                ExerciseAttempt.passed.is_(False),
                or_(
                    Exercise.title.like(like),
                    Exercise.task_md.like(like),
                    ExerciseAttempt.content.like(like),
                    KnowledgePoint.title.like(like),
                ),
            )
            .order_by(ExerciseAttempt.created_at.desc())
            .limit(6)
        )
    ).all()
    for att, ex, doc in ex_rows:
        href = f"/read/{doc.id}?section={ex.knowledge_point_id}" if doc else ""
        hits.append(
            {
                "source": "course_exercise",
                "title": ex.title,
                "course": doc.title if doc else "",
                "task_excerpt": _clip(ex.task_md, 220),
                "user_answer_excerpt": _clip(att.content, 220),
                "created_at": att.created_at,
                "references": [
                    {
                        "label": f"历史错题：{ex.title}" + (f"（《{doc.title}》）" if doc else ""),
                        "href": href,
                    }
                ],
            }
        )
        if len(hits) >= 3:
            break

    # 题库错题
    if len(hits) < 3:
        bank_rows = (
            await db.execute(
                select(BankAttempt, BankQuestion)
                .join(BankQuestion, BankQuestion.id == BankAttempt.question_id)
                .where(
                    BankAttempt.passed.is_(False),
                    BankAttempt.is_revoked.is_(False),
                    or_(
                        BankQuestion.title.like(like),
                        BankQuestion.ai_explanation.like(like),
                        BankQuestion.explanation.like(like),
                    ),
                )
                .order_by(BankAttempt.created_at.desc())
                .limit(6)
            )
        ).all()
        for att, q in bank_rows:
            hits.append(
                {
                    "source": "bank_question",
                    "title": f"题库第 {q.seq} 题",
                    "course": "",
                    "task_excerpt": _clip(q.title, 220),
                    "user_answer_excerpt": f"学员作答：{att.content}（正确答案：{q.answer_raw or q.answer}）",
                    "created_at": att.created_at,
                    "references": [
                        {
                            "label": f"历史错题：题库第 {q.seq} 题",
                            "href": "/bank",
                        }
                    ],
                }
            )
            if len(hits) >= 3:
                break

    if not hits:
        return {"status": "not_found", "message": f"没有检索到与「{keyword}」相关的历史错题"}
    return {"status": "success", "hits": hits}


# ===== v0.5.6 全量工具扩权：读类实现（免确认；大量复用 api 层端点函数直调，
# Depends 仅是参数默认值，显式传 db 即可；HTTPException 由 execute_tool 统一转 error） =====


def _ref(label: str, href: str) -> dict[str, str]:
    return {"label": label, "href": href}


async def _tool_search_learned_content(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.services.search import search as fts_search

    query = str(args.get("query") or "").strip()
    if not query or db is None:
        return {"error": "缺少检索词或数据库上下文"}
    rows = await fts_search(db, query, limit=8)
    if not rows:
        return {"status": "not_found", "message": f"没有检索到与「{query}」相关的已学内容"}
    hits = [
        {
            "course": r.get("course_title", ""),
            "document_id": r.get("document_id", ""),
            "document_title": r.get("document_title", ""),
            "heading": r.get("heading", ""),
            "snippet": _clip(str(r.get("snippet", "")).replace("<mark>", "【").replace("</mark>", "】"), 400),
            "references": [
                _ref(
                    f"原文：《{r.get('document_title', '')}》 · {r.get('heading', '')}",
                    f"/read/{r.get('document_id')}?section={r.get('section_id')}",
                )
            ],
        }
        for r in rows[:6]
    ]
    return {"status": "success", "hits": hits}


async def _tool_list_courses(db: AsyncSession) -> dict[str, Any]:
    from app.api.courses import list_courses as _api

    items = await _api(db=db)
    out = [
        {
            "id": it.id,
            "title": it.title,
            "status": it.status,
            "chapters_done": it.done_chapters,
            "chapters_total": it.total_chapters,
            "first_document_id": it.first_document_id,
        }
        for it in items
    ]
    if not out:
        return {"status": "empty", "message": "学员还没有任何课程"}
    return {"status": "success", "courses": out}


async def _tool_get_course_detail(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.courses import get_course as _api

    course_id = str(args.get("course_id") or "")
    detail = await _api(course_id=course_id, db=db)
    docs = [
        {
            "document_id": d.document_id,
            "chapter_index": d.chapter_index,
            "title": d.title,
            "status": d.status,
        }
        for d in (detail.documents or [])
    ]
    refs = [
        _ref(f"阅读：第{d['chapter_index']}章《{d['title']}》", f"/read/{d['document_id']}")
        for d in docs
        if d["status"] == "done"
    ][:6]
    return {
        "status": "success",
        "course": {"id": detail.id, "title": detail.title, "status": detail.status},
        "chapters": docs,
        "references": refs,
    }


async def _tool_read_document(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import Document, Section
    from app.services.sections_text import get_section_text, load_document_markdown

    document_id = str(args.get("document_id") or "")
    section_id = str(args.get("section_id") or "").strip()
    doc = await db.get(Document, document_id) if document_id else None
    if doc is None:
        return {"error": f"未找到章节文档 {document_id}"}

    sections = (
        await db.scalars(
            select(Section).where(Section.document_id == doc.id).order_by(Section.order_index)
        )
    ).all()
    sec_list = []
    for s in sections:
        try:
            hp = json.loads(s.heading_path) if s.heading_path else []
        except Exception:  # noqa: BLE001
            hp = []
        sec_list.append({"section_id": s.id, "heading": " > ".join(str(x) for x in hp)})

    if section_id:
        text = await get_section_text(db, doc, section_id)
        return {
            "status": "success",
            "document": {"id": doc.id, "title": doc.title, "chapter_index": doc.chapter_index},
            "section_id": section_id,
            "content": _clip(text, 6000),
            "references": [_ref(f"原文：《{doc.title}》", f"/read/{doc.id}?section={section_id}")],
        }
    full = load_document_markdown(doc)
    return {
        "status": "success",
        "document": {"id": doc.id, "title": doc.title, "chapter_index": doc.chapter_index},
        "sections": sec_list,
        "content": _clip(full, 6000),
        "note": "正文超长时已截断；需要某小节完整原文可用 section_id 精确读取",
        "references": [_ref(f"原文：《{doc.title}》", f"/read/{doc.id}")],
    }


async def _tool_list_exercises(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.exercise import list_exercises as _api

    document_id = str(args.get("document_id") or "")
    rows = await _api(document_id=document_id, db=db)
    out = [
        {
            "id": it.id,
            "title": it.title,
            "kind": it.kind,
            "kp_title": getattr(it, "kp_title", "") or "",
            "passed": getattr(it, "passed", None),
            "hard_bone": getattr(it, "is_hard_bone", False),
        }
        for it in rows
    ]
    if not out:
        return {"status": "empty", "message": "该章还没有练习关卡"}
    return {"status": "success", "exercises": out}


async def _tool_list_wrong_questions(db: AsyncSession) -> dict[str, Any]:
    from app.services.exercise import wrongbook

    rows = await wrongbook(db)
    out = [
        {
            "id": it.id,
            "title": it.title,
            "kind": it.kind,
            "kp_title": getattr(it, "kp_title", "") or "",
            "document_id": getattr(it, "document_id", "") or "",
        }
        for it in rows[:12]
    ]
    if not out:
        return {"status": "empty", "message": "错题本是空的，学员最近没有未通过的练习"}
    return {"status": "success", "wrong_exercises": out, "references": [_ref("打开错题本", "/wrongbook")]}


async def _tool_get_study_report(db: AsyncSession) -> dict[str, Any]:
    from app.api.dashboard import summary as _api

    d = (await _api(db=db)).model_dump()
    # 面向对话精简：保留进度/薄弱点/时长/用量主干，去掉前端专用的大数组
    d.pop("heatmap", None)
    d.pop("daily_minutes", None)
    return {"status": "success", "report": d}


async def _tool_get_learner_profile(db: AsyncSession) -> dict[str, Any]:
    from app.services.profile import get_active_misconceptions, get_or_create_profile

    profile = await get_or_create_profile(db)
    rows = await get_active_misconceptions(db, limit=10)
    return {
        "status": "success",
        "background": _clip(profile.background_summary or "", 800),
        "socratic_enabled": bool(profile.socratic_mode),
        "misconceptions": [
            {
                "id": m.id,
                "topic": m.topic,
                "tag": m.tag,
                "evidence": _clip(m.evidence or "", 200),
                "source_href": getattr(m, "source_href", "") or "",
            }
            for m in rows
        ],
    }


async def _tool_list_banks(db: AsyncSession) -> dict[str, Any]:
    from app.models import QuestionBank
    from app.services.bank import bulk_bank_stats

    banks = (
        await db.scalars(select(QuestionBank).order_by(QuestionBank.created_at.desc()))
    ).all()
    if not banks:
        return {"status": "empty", "message": "还没有任何题库"}
    stats_map = await bulk_bank_stats(db, [b.id for b in banks])
    out = [
        {
            "id": b.id,
            "name": b.name,
            "question_count": b.question_count,
            "stats": stats_map.get(b.id, {}),
        }
        for b in banks
    ]
    return {"status": "success", "banks": out, "references": [_ref("打开题库", "/bank")]}


async def _tool_draw_bank_round(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import QuestionBank
    from app.services.bank import draw_round

    bank_id = str(args.get("bank_id") or "")
    mode = str(args.get("mode") or "all")
    try:
        size = int(args.get("size") or 5)
    except (TypeError, ValueError):
        size = 5
    size = max(1, min(size, 20))
    bank = await db.get(QuestionBank, bank_id)
    if bank is None:
        return {"error": f"未找到题库 {bank_id}"}
    questions, pool_size = await draw_round(db, bank, mode, size)
    # 抽题预览与做题页同口径脱敏：不带答案/解析/AI 解析
    out = [
        {
            "question_id": q.id,
            "seq": q.seq,
            "qtype": q.qtype,
            "title": _clip(q.title, 800),
            "options": (json.loads(q.options) if q.options and q.options.startswith("[") else []),
        }
        for q in questions
    ]
    return {
        "status": "success" if out else "empty",
        "mode": mode,
        "pool_size": pool_size,
        "questions": out,
        "references": [_ref(f"进入题库《{bank.name}》刷题", f"/bank/{bank.id}")],
    }


async def _tool_list_mindmaps(db: AsyncSession) -> dict[str, Any]:
    from app.services.mindmap import list_mindmaps

    rows = await list_mindmaps(db)
    out = [
        {"id": m.id, "title": m.title, "node_count": m.node_count, "source": m.source}
        for m in rows
    ]
    if not out:
        return {"status": "empty", "message": "还没有思维导图"}
    return {"status": "success", "mindmaps": out, "references": [_ref("打开导图库", "/mindmap")]}


async def _prune_tree(node: dict[str, Any], depth: int, max_depth: int) -> dict[str, Any]:
    out = {
        "id": node.get("id", ""),
        "title": node.get("title", ""),
        "summary": _clip(str(node.get("summary") or ""), 120),
    }
    children = node.get("children") or []
    if depth < max_depth:
        out["children"] = [
            _prune_tree(c, depth + 1, max_depth) for c in children[:10]
        ]
        if len(children) > 10:
            out["children_truncated"] = True
    else:
        if children:
            out["children_count"] = len(children)
    return out


async def _tool_get_mindmap(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.mindmap import get_mindmap

    mm = await get_mindmap(db, str(args.get("map_id") or ""))
    if mm is None:
        return {"error": "未找到该思维导图"}
    try:
        root = json.loads(mm.root) if isinstance(mm.root, str) else (mm.root or {})
    except Exception:  # noqa: BLE001
        root = {}
    return {
        "status": "success",
        "mindmap": {
            "id": mm.id,
            "title": mm.title,
            "source": mm.source,
            "root": _prune_tree(root if isinstance(root, dict) else {}, 1, 4),
        },
        "note": "节点展示限深 4 层、每层最多 10 个子分支；编辑用节点 id",
        "references": [_ref(f"打开导图《{mm.title}》", f"/mindmap/{mm.id}")],
    }


async def _tool_list_annotations(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.annotations import list_annotations as _api

    rows = await _api(document_id=str(args.get("document_id") or ""), db=db)
    out = [
        {
            "id": a.id,
            "exact": _clip(a.exact, 120),
            "color": a.color,
            "note": _clip(a.note or "", 200),
            "status": a.status,
        }
        for a in rows
    ]
    return {"status": "success" if out else "empty", "annotations": out}


async def _tool_check_app_update(db: AsyncSession) -> dict[str, Any]:
    from app.services.update import check_update

    result = await asyncio.wait_for(check_update(db, force=False), timeout=20.0)
    return {"status": "success", "update": result}


def _tool_list_backups() -> dict[str, Any]:
    from app.services.system import list_backups

    rows = list_backups()
    return {
        "status": "success",
        "backups": [
            {"name": r["name"], "size_mb": round(r["size"] / 1048576, 1)} for r in rows
        ],
    }


def _tool_get_sync_status() -> dict[str, Any]:
    from app.services.relay.client import relay_client

    return {"status": "success", "relay": relay_client.get_status_dict()}


# ===== v0.5.6 全量工具扩权：写类实现（一律走学员确认卡放行后才会到达这里） =====


async def _tool_create_course(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.courses import generate as _api_generate
    from app.models import Course
    from app.schemas.course import CourseCreate
    from app.services.generation.outline import generate_outline
    from app.services.llm.openai_compat import create_adapter_from_settings

    topic = str(args.get("topic") or "").strip()
    if not topic:
        return {"error": "缺少课程主题"}
    adapter = await create_adapter_from_settings(db)
    req = CourseCreate(
        topic=topic[:200],
        level=(str(args.get("level") or "").strip() or None),
        chapter_count=int(args.get("chapter_count") or 0) or None,
    )
    title, outline = await generate_outline(db, adapter, req)
    course = Course(
        title=title,
        topic=req.topic,
        level=req.level,
        scope=req.scope,
        chapter_count=req.chapter_count,
        outline=json.dumps([o.model_dump() for o in outline], ensure_ascii=False),
        status="draft",
    )
    db.add(course)
    await db.commit()

    chapters = [o.title for o in outline]
    out: dict[str, Any] = {
        "status": "success",
        "course_id": course.id,
        "title": title,
        "outline": chapters,
        "references": [_ref(f"打开课程《{title}》", f"/courses/{course.id}")],
    }
    if args.get("start_generation", True):
        # 复用 API 层生成启动逻辑（建 Document/清派生/后台任务），课程详情页可看进度
        await _api_generate(course_id=course.id, body=None, db=db)
        out["generation"] = "已启动后台逐章生成，进度可在课程详情页查看"
        out["references"].append(_ref(f"查看《{title}》生成进度", f"/courses/{course.id}"))
    return out


async def _tool_import_course_material(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.api.imports import _extract_kp
    from app.models import Course, Document, KnowledgePoint
    from app.services.docparser import parse_blocks
    from app.services.generation.indexing import rebuild_sections
    from app.services.imports import detect_chapters, slice_text
    from app.services.llm.openai_compat import create_adapter_from_settings

    title = str(args.get("title") or "").strip() or "导入课程"
    markdown = str(args.get("markdown") or "")
    if not markdown.strip():
        return {"error": "导入材料为空"}
    if len(markdown) > 400_000:
        return {"error": "材料过长（>40 万字符），请拆分后分批导入"}

    chapters = detect_chapters(markdown, file_index=0, filename=title)
    if not chapters:
        return {"error": "未能从材料中识别出任何章节（需要 # / ## 级标题分层）"}

    adapter = None
    try:
        adapter = await create_adapter_from_settings(db, scene="generation")
    except Exception:  # noqa: BLE001  未配置 LLM 时导入仍可用，跳过知识点提取
        adapter = None

    course = Course(title=title[:200], topic=f"助教导入：{title[:160]}", outline="[]", status="ready")
    db.add(course)
    await db.flush()

    outline_items: list[dict[str, Any]] = []
    kp_extracted = 0
    try:
        prepared = []
        for ch in chapters:
            content = slice_text(markdown, ch["start_line"], ch["end_line"])
            if not content.strip():
                continue
            meta = await _extract_kp(adapter, content) if adapter is not None else None
            prepared.append((ch, content, meta))

        for j, (ch, content, meta) in enumerate(prepared):
            doc = Document(
                course_id=course.id,
                chapter_index=j + 1,
                title=str(ch.get("title") or f"第{j + 1}章"),
                version=1,
                status="done",
                source="imported",
            )
            db.add(doc)
            await db.flush()

            from app.core.config import settings as app_settings

            doc_dir = app_settings.courses_dir / course.id / doc.id
            doc_dir.mkdir(parents=True, exist_ok=True)
            current = doc_dir / "current.md"
            current.write_text(content, encoding="utf-8")
            doc.file_path = current.relative_to(app_settings.data_dir).as_posix()
            await rebuild_sections(db, doc, content, 1)

            blocks = parse_blocks(content)
            heading_levels = [
                len(b.raw) - len(b.raw.lstrip("#"))
                for b in blocks
                if b.block_type == "heading"
            ]
            chapter_level = heading_levels[0] if heading_levels else 1
            points = [
                b.text
                for b in blocks
                if b.block_type == "heading"
                and (len(b.raw) - len(b.raw.lstrip("#"))) == chapter_level + 1
            ][:8]
            outline_items.append({"index": j + 1, "title": doc.title, "points": points})

            if meta is not None:
                doc.summary = getattr(meta, "summary", "") or ""
                kp_extracted += len(getattr(meta, "knowledge_points", []) or [])
                rows = (
                    await db.scalars(select(Section).where(Section.document_id == doc.id))
                ).all()
                section_by_heading: dict[str, str] = {}
                for row in rows:
                    try:
                        hp = json.loads(row.heading_path)
                    except Exception:  # noqa: BLE001
                        hp = []
                    if hp:
                        section_by_heading.setdefault(hp[-1], row.id)
                for item in getattr(meta, "knowledge_points", []) or []:
                    sec_ids = (
                        [section_by_heading[item.heading]]
                        if getattr(item, "heading", "") and item.heading in section_by_heading
                        else []
                    )
                    db.add(
                        KnowledgePoint(
                            document_id=doc.id,
                            title=item.title,
                            summary=getattr(item, "summary", "") or "",
                            section_ids=json.dumps(sec_ids, ensure_ascii=False),
                        )
                    )
                    await db.flush()

        course.outline = json.dumps(outline_items, ensure_ascii=False)
        course.updated_at = utcnow_iso()
        await db.commit()
    except Exception:
        await db.rollback()
        from app.core.config import settings as app_settings

        shutil.rmtree(app_settings.courses_dir / course.id, ignore_errors=True)
        raise

    return {
        "status": "success",
        "course_id": course.id,
        "title": course.title,
        "chapters": len(outline_items),
        "knowledge_points": kp_extracted,
        "references": [_ref(f"打开课程《{course.title}》", f"/courses/{course.id}")],
    }


async def _tool_regenerate_document(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import Document
    from app.services.generation.pipeline import queue_single_document

    document_id = str(args.get("document_id") or "")
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"error": f"未找到章节文档 {document_id}"}
    course_id = await queue_single_document(document_id, None, None)
    return {
        "status": "success",
        "message": f"《{doc.title}》已加入重新生成队列（后台执行，原正文将在生成完成后被替换）",
        "course_id": course_id,
        "references": [_ref("查看课程生成进度", f"/courses/{course_id}")],
    }


async def _tool_revise_section(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import Document, Section
    from app.services.revision import apply_section_revision, review_section_revision

    document_id = str(args.get("document_id") or "")
    section_id = str(args.get("section_id") or "")
    instruction = str(args.get("instruction") or "").strip()
    if not instruction:
        return {"error": "缺少修订要求"}
    doc = await db.get(Document, document_id)
    sec = (
        await db.scalars(
            select(Section).where(Section.document_id == document_id, Section.id == section_id)
        )
    ).first()
    if doc is None or sec is None:
        return {"error": "文档或小节不存在"}
    original_md, review = await review_section_revision(db, doc, sec, instruction)
    revised = getattr(review, "revised_markdown", "") or getattr(review, "revised", "")
    if not revised:
        return {"error": "审校未产出修订稿", "review": str(review)[:400]}
    await apply_section_revision(db, doc, sec, revised)
    return {
        "status": "success",
        "section_heading": _clip(str(getattr(sec, "heading_path", "") or ""), 200),
        "original_excerpt": _clip(original_md, 300),
        "revised_excerpt": _clip(revised, 600),
        "references": [_ref(f"查看修订后的《{doc.title}》", f"/read/{doc.id}?section={section_id}")],
    }


async def _tool_generate_exercises(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.exercise import generate_for_kp

    kp_id = str(args.get("knowledge_point_id") or "")
    if not kp_id:
        return {"error": "缺少知识点 ID"}
    try:
        count = int(args.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    language = str(args.get("language") or "python").lower()
    if language not in ("python", "cpp"):
        language = "python"
    rows = await generate_for_kp(db, kp_id, language, count)
    return {
        "status": "success",
        "generated": len(rows),
        "note": "该知识点下的旧关卡已被替换；新题未作答前答案不展示",
        "exercises": [{"id": e.id, "title": e.title, "kind": e.kind} for e in rows[:10]],
    }


async def _tool_generate_quiz(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import KnowledgePoint
    from app.services.quiz import generate_quiz

    document_id = str(args.get("document_id") or "")
    kp_ids = [str(x) for x in (args.get("kp_ids") or []) if str(x).strip()]
    if not kp_ids:
        kp_rows = (
            await db.scalars(select(KnowledgePoint).where(KnowledgePoint.document_id == document_id))
        ).all()
        kp_ids = [k.id for k in kp_rows]
        if not kp_ids:
            return {"error": "该章没有知识点，无法组小测"}
    quiz = await generate_quiz(db, document_id, kp_ids, "python", 0)
    return {
        "status": "success",
        "quiz_id": quiz.id,
        "references": [_ref("在章节内打开闯关练习", f"/read/{document_id}")],
    }


async def _tool_generate_bridge_exercises(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.services.exercise import generate_bridge_exercises

    rows = await generate_bridge_exercises(db, str(args.get("exercise_id") or ""))
    return {
        "status": "success",
        "generated": len(rows),
        "exercises": [{"id": e.id, "title": e.title, "kind": e.kind} for e in rows],
    }


async def _tool_toggle_hard_bone(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.exercise import toggle_hard_bone

    exercise_id = str(args.get("exercise_id") or "")
    want = args.get("on")
    state = await toggle_hard_bone(db, exercise_id)
    if want is not None and bool(want) != bool(state):
        state = await toggle_hard_bone(db, exercise_id)
    return {"status": "success", "hard_bone": bool(state)}


async def _tool_add_bank_questions(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.bank import _format_parsed_questions
    from app.models import QuestionBank
    from app.schemas.bank import PasteParseResponse
    from app.services.bank import append_questions
    from app.services.llm.openai_compat import create_adapter_from_settings
    from app.services.prompt import render_prompt

    bank_id = str(args.get("bank_id") or "")
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "试题文本为空"}
    bank = await db.get(QuestionBank, bank_id)
    if bank is None:
        return {"error": f"未找到题库 {bank_id}"}
    adapter = await create_adapter_from_settings(db, scene="generation")
    parsed = await adapter.chat_json(
        [
            {"role": "system", "content": render_prompt("bank_text_parse")},
            {"role": "user", "content": f"请解析以下试题文本并结构化输出：\n\n{text}"},
        ],
        schema=PasteParseResponse,
    )
    added = await append_questions(db, bank, _format_parsed_questions(parsed.questions))
    return {
        "status": "success",
        "added": added,
        "bank": {"id": bank.id, "name": bank.name, "question_count": bank.question_count},
        "references": [_ref(f"进入题库《{bank.name}》", f"/bank/{bank.id}")],
    }


async def _tool_correct_bank_question(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import BankQuestion
    from app.services.bank import update_question

    question_id = str(args.get("question_id") or "")
    q = await db.get(BankQuestion, question_id)
    if q is None:
        return {"error": f"未找到题目 {question_id}"}
    options = args.get("options")
    if options is not None and not isinstance(options, list):
        return {"error": "options 必须是字符串数组"}
    updated, _recalibrated = await update_question(
        db,
        q,
        title=(str(args["title"]).strip() or None) if args.get("title") else None,
        options=[str(o) for o in options] if options else None,
        answer=(str(args["answer"]).strip().upper() or None) if args.get("answer") else None,
        explanation=(str(args["explanation"]).strip() or None) if args.get("explanation") else None,
    )
    return {
        "status": "success",
        "question": {
            "id": updated.id,
            "seq": updated.seq,
            "title": _clip(updated.title, 200),
            "answer": updated.answer_raw or updated.answer,
        },
        "note": "已自动重判全部历史作答并更新错题池",
        "references": [_ref("查看题库", f"/bank/{q.bank_id}")],
    }


async def _tool_set_bank_prompt(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import QuestionBank

    bank_id = str(args.get("bank_id") or "")
    prompt = str(args.get("prompt") or "").strip()
    bank = await db.get(QuestionBank, bank_id)
    if bank is None:
        return {"error": f"未找到题库 {bank_id}"}
    # ai_prompt 列 NOT NULL：空串即恢复默认答疑提示词（与 PATCH /banks/{id} 同口径）
    bank.ai_prompt = prompt
    await db.commit()
    return {
        "status": "success",
        "bank": {"id": bank.id, "name": bank.name},
        "note": "已设置为默认提示词" if not prompt else "自定义提示词已生效",
    }


async def _tool_create_mindmap(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.schemas.mindmap import MindMapCreate
    from app.services.mindmap import (
        create_mindmap,
        generate_mindmap_from_course,
        generate_mindmap_tree,
    )

    topic = str(args.get("topic") or "").strip()
    course_id = str(args.get("course_id") or "").strip()
    source_text = str(args.get("source_text") or "")
    try:
        depth = int(args.get("depth") or 3)
    except (TypeError, ValueError):
        depth = 3
    depth = max(2, min(depth, 5))

    if course_id:
        tree = await generate_mindmap_from_course(db, course_id, depth)
        title = topic or "课程导图"
    else:
        if not topic:
            return {"error": "请提供导图主题或课程 ID"}
        tree = await generate_mindmap_tree(topic, depth, source_text, db)
        title = topic
    if not isinstance(tree, dict) or not tree:
        return {"error": "导图生成结果为空，请重试"}

    mm = await create_mindmap(
        db,
        MindMapCreate(title=title[:120], topic=topic[:200], root=tree, source="generate"),
    )
    return {
        "status": "success",
        "map_id": mm.id,
        "title": mm.title,
        "references": [_ref(f"打开导图《{mm.title}》", f"/mindmap/{mm.id}")],
    }


async def _tool_edit_mindmap(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.schemas.mindmap import MindMapUpdate
    from app.services.mindmap import get_mindmap, update_mindmap

    map_id = str(args.get("map_id") or "")
    operations = args.get("operations")
    if not isinstance(operations, list) or not operations:
        return {"error": "缺少编辑操作列表"}
    mm = await get_mindmap(db, map_id)
    if mm is None:
        return {"error": f"未找到导图 {map_id}"}
    try:
        root = json.loads(mm.root) if isinstance(mm.root, str) else (mm.root or {})
    except Exception:  # noqa: BLE001
        return {"error": "导图数据损坏，无法编辑"}

    def find(node: dict[str, Any], node_id: str) -> dict[str, Any] | None:
        if str(node.get("id")) == node_id:
            return node
        for c in node.get("children") or []:
            found = find(c, node_id)
            if found is not None:
                return found
        return None

    applied = 0
    for op in operations[:20]:
        action = str(op.get("action") or "")
        node = find(root if isinstance(root, dict) else {}, str(op.get("node_id") or ""))
        if node is None:
            continue
        if action == "rename" and str(op.get("title") or "").strip():
            node["title"] = str(op["title"]).strip()
        elif action == "set_detail" and "detail" in op:
            node["detail"] = str(op.get("detail") or "")
        elif action == "add_child" and str(op.get("title") or "").strip():
            children = node.setdefault("children", [])
            if len(children) < 30:
                children.append(
                    {
                        "id": new_id(),
                        "title": str(op["title"]).strip(),
                        "summary": str(op.get("summary") or ""),
                        "detail": "",
                        "children": [],
                    }
                )
        elif action == "delete":
            # 删除分支=从父节点摘除：定位父节点后过滤
            def prune(parent: dict[str, Any], target: str) -> bool:
                kids = parent.get("children") or []
                kept = [c for c in kids if str(c.get("id")) != target]
                if len(kept) != len(kids):
                    parent["children"] = kept
                    return True
                return any(prune(c, target) for c in kids)

            if str(root.get("id")) == str(op.get("node_id")):
                return {"error": "不能删除根节点"}
            prune(root, str(op.get("node_id")))
        else:
            continue
        applied += 1

    if not applied:
        return {"error": "没有可执行的操作（检查 node_id 是否来自 get_mindmap 返回）"}
    await update_mindmap(db, map_id, MindMapUpdate(root=root))
    return {
        "status": "success",
        "applied": applied,
        "references": [_ref(f"查看导图《{mm.title}》", f"/mindmap/{mm.id}")],
    }


async def _tool_create_annotation(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.annotations import create_annotation as _api
    from app.models import Document, Section
    from app.schemas.annotation import AnnotationCreate

    document_id = str(args.get("document_id") or "")
    section_id = str(args.get("section_id") or "")
    exact = str(args.get("exact") or "").strip()
    if not exact:
        return {"error": "划线原文为空"}
    doc = await db.get(Document, document_id)
    sec = (
        await db.scalars(
            select(Section).where(Section.document_id == document_id, Section.id == section_id)
        )
    ).first()
    if doc is None or sec is None:
        return {"error": "文档或小节不存在（section_id 来自 read_document 返回）"}

    from app.services.sections_text import get_section_text

    text = await get_section_text(db, doc, section_id)
    pos = text.find(exact)
    if pos < 0:
        return {
            "error": "划线原文与小节文本不完全一致，请用 read_document 核对后逐字引用（含标点）"
        }
    body = AnnotationCreate(
        section_id=section_id,
        exact=exact,
        prefix=text[max(0, pos - 30) : pos],
        suffix=text[pos + len(exact) : pos + len(exact) + 30],
        start_offset=pos,
        end_offset=pos + len(exact),
        color=str(args.get("color") or "yellow"),
        note=(str(args.get("note") or "").strip() or None),
    )
    created = await _api(document_id=document_id, body=body, db=db)
    return {
        "status": "success",
        "annotation_id": created.annotation.id,
        "conversation_id": created.conversation_id,
        "references": [_ref(f"查看《{doc.title}》划线", f"/read/{doc.id}?section={section_id}")],
    }


async def _tool_update_learner_profile(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.profile import get_or_create_profile

    profile = await get_or_create_profile(db)
    background = args.get("background")
    socratic = args.get("socratic_enabled")
    if background is None and socratic is None:
        return {"error": "没有提供任何要更新的字段"}
    if background is not None:
        profile.background_summary = str(background).strip()[:2000]
    if socratic is not None:
        profile.socratic_mode = bool(socratic)
    await db.commit()
    return {"status": "success", "socratic_enabled": bool(profile.socratic_mode)}


async def _tool_resolve_misconception(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.api.study import remove_misconception as _api

    await _api(misconception_id=str(args.get("misconception_id") or ""), db=db)
    return {"status": "success", "note": "该盲区已标记为 resolved（保留作为演进查重依据）"}


def _tool_create_backup() -> dict[str, Any]:
    from app.services.system import create_backup

    path = create_backup()
    return {
        "status": "success",
        "backup": path.name,
        "references": [_ref("打开备份管理", "/settings")],
    }


async def _tool_trigger_sync(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.relay.sync import (
        execute_bi_directional_sync,
        pull_cloud_data_to_local,
        push_local_data_to_server,
    )

    direction = str(args.get("direction") or "both")
    if direction == "push":
        result = await push_local_data_to_server()
    elif direction == "pull":
        result = await pull_cloud_data_to_local()
    else:
        result = await execute_bi_directional_sync()
    summary = json.dumps(result, ensure_ascii=False, default=str)
    return {"status": "success", "direction": direction, "result": _clip(summary, 800)}


async def _tool_delete_resource(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from app.models import MindMap, QuestionBank

    kind = str(args.get("kind") or "")
    resource_id = str(args.get("id") or "")
    if not resource_id:
        return {"error": "缺少资源 ID"}

    if kind == "course":
        from app.api.courses import delete_course as _api

        await _api(course_id=resource_id, db=db)
        name = "课程"
    elif kind == "bank":
        bank = await db.get(QuestionBank, resource_id)
        if bank is None:
            return {"error": "题库不存在"}
        name = f"题库《{bank.name}》"
        from app.services.bank import delete_bank

        await delete_bank(db, bank)
    elif kind == "exercise":
        from app.services.exercise import delete_exercise

        await delete_exercise(db, resource_id)
        name = "练习题"
    elif kind == "quiz":
        from app.services.quiz import delete_quiz

        await delete_quiz(db, resource_id)
        name = "小测"
    elif kind == "mindmap":
        from app.services.mindmap import delete_mindmap

        if not await delete_mindmap(db, resource_id):
            return {"error": "导图不存在"}
        name = "思维导图"
    elif kind == "annotation":
        from app.api.annotations import delete_annotation as _api

        await _api(annotation_id=resource_id, db=db)
        name = "划线批注"
    elif kind == "backup":
        from app.services.system import delete_backup

        delete_backup(resource_id)
        name = f"备份 {resource_id}"
    else:
        return {"error": f"不支持的资源类型：{kind}"}
    return {"status": "success", "deleted": name, "note": f"{name} 已删除"}


async def _tool_update_resource_title(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.models import MindMap, QuestionBank

    kind = str(args.get("kind") or "")
    resource_id = str(args.get("id") or "")
    title = str(args.get("title") or "").strip()
    if not title:
        return {"error": "新标题为空"}
    if kind == "course":
        from app.models import Course

        course = await db.get(Course, resource_id)
        if course is None:
            return {"error": "课程不存在"}
        course.title = title[:200]
    elif kind == "bank":
        bank = await db.get(QuestionBank, resource_id)
        if bank is None:
            return {"error": "题库不存在"}
        bank.name = title[:120]
    elif kind == "mindmap":
        from app.services.mindmap import update_mindmap
        from app.schemas.mindmap import MindMapUpdate

        if await update_mindmap(db, resource_id, MindMapUpdate(title=title[:120])) is None:
            return {"error": "导图不存在"}
    else:
        return {"error": f"不支持的资源类型：{kind}"}
    await db.commit()
    return {"status": "success", "kind": kind, "id": resource_id, "title": title}


async def execute_tool(
    name: str,
    arguments: dict[str, Any] | str,
    db: AsyncSession | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行工具并返回结构化结果字典。context：服务层注入的调用现场（如当前文档 ID）。"""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}

    try:
        if name == "run_sandbox_code":
            code = str(args.get("code") or "")
            lang = str(args.get("language") or "python").lower()
            if not code.strip():
                return {"error": "代码内容为空"}
            res = await run_code(lang, code)
            return {
                "status": res["status"],
                "exit_code": res["exit_code"],
                "stdout": res["stdout"],
                "stderr": res["stderr"],
                "duration_ms": res["duration_ms"],
            }

        elif name == "render_math_plot":
            from app.api.math import render_sync

            exprs = str(args.get("expressions") or "").strip()
            if not exprs:
                return {"error": "函数表达式为空"}
            # 与 API 层 /api/math/render 同一套校验（v0.5.1 体检 P2）：区间合法、跨度受限、10s 超时，
            # 防模型给出的离谱区间卡死 to_thread 线程并让 SSE 永久停在工具步
            try:
                x_min = float(args.get("x_min", -10.0))
                x_max = float(args.get("x_max", 10.0))
            except (TypeError, ValueError):
                x_min, x_max = -10.0, 10.0
            import math as _math

            if not (_math.isfinite(x_min) and _math.isfinite(x_max)) or x_max <= x_min:
                x_min, x_max = -10.0, 10.0
            if (x_max - x_min) > 10000:
                x_min, x_max = -10.0, 10.0
            try:
                svg = await asyncio.wait_for(
                    asyncio.to_thread(render_sync, exprs, x_min, x_max), timeout=10.0
                )
            except asyncio.TimeoutError:
                return {"error": "函数图像渲染超时（10s），已放弃本次绘制"}
            # svg 通过 tool_result 事件透传给前端渲染；进入 LLM 历史前由 runner 剥离避免撑爆上下文
            return {
                "status": "success",
                "svg": svg,
                "svg_length": len(svg),
                "expressions": exprs,
            }

        elif name == "inspect_exercise":
            from app.models import Exercise

            ex_id = str(args.get("exercise_id") or "")
            if not ex_id or db is None:
                return {"error": "缺少 exercise_id 或数据库上下文"}
            exercise = await db.get(Exercise, ex_id)
            if exercise is None:
                return {"error": f"未找到 ID 为 {ex_id} 的关卡"}
            # 服务端防泄题白名单（v0.5.1 体检 P1）：苏格拉底护栏场景下参考实现/预期输出/渐进提示
            # 一律不出服务端——护栏不能只靠提示词，答案字段绝不允许经 tool_result 事件到达浏览器
            guardrail = ""
            if isinstance(context, dict):
                guardrail = str(context.get("guardrail") or "")
            if guardrail == "socratic":
                return {
                    "id": exercise.id,
                    "title": exercise.title,
                    "task": exercise.task_md,
                    "language": exercise.language,
                    "reference_hidden": True,
                    "note": "学员当前练习未通过（启发式辅导场景），参考实现、预期输出与渐进提示已按防泄题策略隐藏；请基于题面与学员作答点拨思路。",
                }
            return {
                "id": exercise.id,
                "title": exercise.title,
                "task": exercise.task_md,
                "language": exercise.language,
                "expected_output": exercise.expected_output,
                "reference_code": exercise.reference_code,
                "hints": exercise.hints,
            }

        elif name == "lookup_learned_section":
            args = {**args, "_ctx": context or {}}
            return await _tool_lookup_learned_section(db, args)

        elif name == "lookup_past_mistakes":
            return await _tool_lookup_past_mistakes(db, args)

        # ===== v0.5.6 读类分发 =====
        elif name == "search_learned_content":
            return await _tool_search_learned_content(db, args)
        elif name == "list_courses":
            return await _tool_list_courses(db)
        elif name == "get_course_detail":
            return await _tool_get_course_detail(db, args)
        elif name == "read_document":
            return await _tool_read_document(db, args)
        elif name == "list_exercises":
            return await _tool_list_exercises(db, args)
        elif name == "list_wrong_questions":
            return await _tool_list_wrong_questions(db)
        elif name == "get_study_report":
            return await _tool_get_study_report(db)
        elif name == "get_learner_profile":
            return await _tool_get_learner_profile(db)
        elif name == "list_banks":
            return await _tool_list_banks(db)
        elif name == "draw_bank_round":
            return await _tool_draw_bank_round(db, args)
        elif name == "list_mindmaps":
            return await _tool_list_mindmaps(db)
        elif name == "get_mindmap":
            return await _tool_get_mindmap(db, args)
        elif name == "list_annotations":
            return await _tool_list_annotations(db, args)
        elif name == "check_app_update":
            return await _tool_check_app_update(db)
        elif name == "list_backups":
            return _tool_list_backups()
        elif name == "get_sync_status":
            return _tool_get_sync_status()

        # ===== v0.5.6 写类分发（SENSITIVE_TOOLS 确认卡已在 runner 层把关） =====
        elif name == "create_course":
            return await _tool_create_course(db, args)
        elif name == "import_course_material":
            return await _tool_import_course_material(db, args)
        elif name == "regenerate_document":
            return await _tool_regenerate_document(db, args)
        elif name == "revise_section":
            return await _tool_revise_section(db, args)
        elif name == "generate_exercises":
            return await _tool_generate_exercises(db, args)
        elif name == "generate_quiz":
            return await _tool_generate_quiz(db, args)
        elif name == "generate_bridge_exercises":
            return await _tool_generate_bridge_exercises(db, args)
        elif name == "toggle_hard_bone":
            return await _tool_toggle_hard_bone(db, args)
        elif name == "add_bank_questions":
            return await _tool_add_bank_questions(db, args)
        elif name == "correct_bank_question":
            return await _tool_correct_bank_question(db, args)
        elif name == "set_bank_prompt":
            return await _tool_set_bank_prompt(db, args)
        elif name == "create_mindmap":
            return await _tool_create_mindmap(db, args)
        elif name == "edit_mindmap":
            return await _tool_edit_mindmap(db, args)
        elif name == "create_annotation":
            return await _tool_create_annotation(db, args)
        elif name == "update_learner_profile":
            return await _tool_update_learner_profile(db, args)
        elif name == "resolve_misconception":
            return await _tool_resolve_misconception(db, args)
        elif name == "create_backup":
            return _tool_create_backup()
        elif name == "trigger_sync":
            return await _tool_trigger_sync(args)
        elif name == "delete_resource":
            return await _tool_delete_resource(db, args)
        elif name == "update_resource_title":
            return await _tool_update_resource_title(db, args)

        else:
            return {"error": f"未注册的工具：{name}"}

    except HTTPException as e:
        # 复用的 api 层端点函数用 HTTPException 表达业务 4xx/5xx，转成工具错误
        return {"error": str(e.detail), "status_code": e.status_code}
    except Exception as e:
        logger.exception(f"工具执行异常：{name}")
        return {"error": str(e)}
