import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button, Input, Select, Spinner, Textarea } from "../../components/ui";

export default function NewCoursePage() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [level, setLevel] = useState("");
  const [scope, setScope] = useState("");
  const [chapterCount, setChapterCount] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.courses.create({
        topic: topic.trim(),
        level: level || null,
        scope: scope.trim() || null,
        chapter_count: chapterCount ? Number(chapterCount) : null,
      }),
    onSuccess: (res) => navigate(`/courses/${res.course.id}`),
  });

  return (
    <div className="mx-auto max-w-2xl p-8">
      <Link to="/" className="text-sm text-gray-500 hover:text-brand-600">
        ← 返回首页
      </Link>
      <h1 className="mt-4 text-2xl font-bold text-gray-900">新建课程</h1>
      <p className="mt-1 text-sm text-gray-500">
        描述你想学的内容，AI 会先生成课程大纲供你确认，再逐章生成文档（约需几分钟）。
      </p>

      <div className="mt-6 space-y-4 rounded-xl border border-gray-200 bg-white p-6">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            学习主题 <span className="text-red-500">*</span>
          </label>
          <Input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="如：C++ 基础 / 高等数学-多元微积分"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">当前基础</label>
          <Select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">不填写</option>
            <option value="零基础">零基础</option>
            <option value="有其他语言基础">有其他语言基础</option>
            <option value="有相关课程基础">有相关课程基础</option>
            <option value="进阶">进阶</option>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">范围与期望（可选）</label>
          <Textarea
            rows={4}
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            placeholder="如：只讲到指针和结构体，多安排练习；或：期末考试范围，偏计算"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">期望章节数（可选）</label>
          <Input
            type="number"
            min={1}
            max={30}
            value={chapterCount}
            onChange={(e) => setChapterCount(e.target.value)}
            placeholder="留空由 AI 决定"
          />
        </div>

        {create.isError && (
          <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {create.error.message}
            {String(create.error.message).includes("尚未配置") && (
              <>
                {" "}
                <Link to="/settings" className="underline">
                  去设置 →
                </Link>
              </>
            )}
          </div>
        )}

        <Button
          className="w-full"
          disabled={!topic.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? (
            <>
              <Spinner className="border-white/40" /> 正在生成大纲（10-30 秒）…
            </>
          ) : (
            "生成课程大纲"
          )}
        </Button>
      </div>
    </div>
  );
}
