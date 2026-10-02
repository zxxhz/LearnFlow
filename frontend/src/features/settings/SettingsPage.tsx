// 设置页：LLM 配置（OpenAI 兼容）+ 学习偏好 + 数据目录（PRD §5.7）
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { LLMConfig, Preferences, SceneLLMConfig, SceneName, SettingsData } from "../../lib/types";
import { Button, Input, Spinner } from "../../components/ui";
import { HL_COLOR_KEYS, HL_DEFAULTS, HL_LABELS } from "../reader/colors";
import RuntimeEnvSection from "./RuntimeEnvSection";
import type { AnnotationColor } from "../../lib/types";

const PROVIDER_PRESETS: { label: string; base_url: string; model: string }[] = [
  { label: "智谱 GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  { label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { label: "Moonshot", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { label: "Ollama 本地", base_url: "http://localhost:11434/v1", model: "qwen2.5:7b" },
];

const SCENE_META: { name: SceneName; label: string; hint: string }[] = [
  { name: "generation", label: "生成模型", hint: "章节生成、导入知识点提取——建议用便宜量大的模型" },
  { name: "chat", label: "答疑模型", hint: "划线提问对话——建议用响应快的模型" },
  { name: "feynman", label: "费曼模型", hint: "学生追问与理解度评价——建议用推理强的模型" },
];

const EMPTY_SCENE: SceneLLMConfig = { base_url: "", api_key: "", model: "" };

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [llm, setLlm] = useState<LLMConfig>({ base_url: "", api_key: "", model: "", temperature: 0.7 });
  const [scenes, setScenes] = useState<Record<SceneName, SceneLLMConfig>>({
    generation: { ...EMPTY_SCENE },
    chat: { ...EMPTY_SCENE },
    feynman: { ...EMPTY_SCENE },
  });
  const [prefs, setPrefs] = useState<Preferences>({
    daily_new_cards: 20,
    chapter_length: 3000,
    feynman_max_rounds: 4,
    auto_create_cards: true,
    exercises_per_kp: 2,
    highlight_colors: {},
    github_repo: "",
  });
  const [saveMsg, setSaveMsg] = useState("");

  useEffect(() => {
    if (settings) {
      setLlm({ ...settings.llm, api_key: "" }); // key 留空 = 不修改
      setScenes({
        generation: { ...EMPTY_SCENE, ...settings.scenes?.generation, api_key: "" },
        chat: { ...EMPTY_SCENE, ...settings.scenes?.chat, api_key: "" },
        feynman: { ...EMPTY_SCENE, ...settings.scenes?.feynman, api_key: "" },
      });
      setPrefs(settings.preferences);
    }
  }, [settings]);

  const saveLlm = useMutation({
    mutationFn: () =>
      api.settings.update({
        llm: {
          base_url: llm.base_url,
          model: llm.model,
          temperature: llm.temperature,
          ...(llm.api_key ? { api_key: llm.api_key } : {}),
        },
        scenes: {
          generation: {
            ...scenes.generation,
            ...(scenes.generation.api_key ? {} : { api_key: undefined }),
          },
          chat: { ...scenes.chat, ...(scenes.chat.api_key ? {} : { api_key: undefined }) },
          feynman: {
            ...scenes.feynman,
            ...(scenes.feynman.api_key ? {} : { api_key: undefined }),
          },
        },
      }),
    onSuccess: () => {
      setSaveMsg("已保存");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setTimeout(() => setSaveMsg(""), 2000);
    },
  });

  const savePrefs = useMutation({
    mutationFn: () => api.settings.update({ preferences: prefs }),
    onSuccess: () => {
      setSaveMsg("已保存");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setTimeout(() => setSaveMsg(""), 2000);
    },
  });

  const [testResult, setTestResult] = useState<string>("");
  const [testing, setTesting] = useState(false);
  const [version, setVersion] = useState<string>("");
  const [updateResult, setUpdateResult] = useState<string>("");
  const [checkingUpdate, setCheckingUpdate] = useState(false);

  const checkUpdate = async (force: boolean) => {
    setCheckingUpdate(true);
    setUpdateResult("");
    try {
      const r = await api.update.check(force);
      setUpdateResult(
        r.has_update
          ? `🎉 有新版本 ${r.latest}（当前 ${r.current}），点击横幅中的「查看发布页」更新。`
          : r.error
            ? `ℹ️ ${r.error}`
            : `✅ 已是最新版本（${r.current}）`
      );
    } catch (e) {
      setUpdateResult(`❌ ${(e as Error).message}`);
    } finally {
      setCheckingUpdate(false);
    }
  };

  useEffect(() => {
    api.update.version().then((v) => setVersion(v.version)).catch(() => {});
  }, []);  const testLlm = async () => {
    setTesting(true);
    setTestResult("");
    try {
      const r = await api.settings.testLlm();
      setTestResult(
        r.ok
          ? `✅ 连接正常 · 模型回复「${r.model_reply}」· 延迟 ${r.latency_ms}ms`
          : `❌ ${r.error}`
      );
    } catch (e) {
      setTestResult(`❌ ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-bold text-gray-900">设置</h1>
      {saveMsg && <span className="ml-3 text-sm text-green-600">{saveMsg}</span>}

      {/* LLM 服务 */}
      <section className="mt-6 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">LLM 服务（OpenAI 兼容）</h2>
        <p className="mt-1 text-xs text-gray-500">
          支持智谱 GLM、DeepSeek、OpenAI 等任何 OpenAI 兼容端点。API Key 留空表示不修改。
        </p>
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-gray-500">快捷填入：</span>
            {PROVIDER_PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => setLlm((prev) => ({ ...prev, base_url: p.base_url, model: p.model }))}
                className="rounded-full border border-gray-200 px-2.5 py-1 text-gray-600 hover:border-brand-500 hover:text-brand-600"
                title={`${p.base_url}（模型：${p.model}，可再手改）`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Base URL</label>
            <Input
              value={llm.base_url}
              onChange={(e) => setLlm({ ...llm, base_url: e.target.value })}
              placeholder="https://open.bigmodel.cn/api/paas/v4 或 https://api.deepseek.com/v1"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">API Key</label>
            <Input
              type="password"
              value={llm.api_key}
              onChange={(e) => setLlm({ ...llm, api_key: e.target.value })}
              placeholder={settings?.llm.api_key ? `已保存：${settings.llm.api_key}` : "sk-…"}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">模型名</label>
              <Input
                value={llm.model}
                onChange={(e) => setLlm({ ...llm, model: e.target.value })}
                placeholder="glm-4-flash / deepseek-chat"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Temperature</label>
              <Input
                type="number"
                step={0.1}
                min={0}
                max={2}
                value={llm.temperature}
                onChange={(e) => setLlm({ ...llm, temperature: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              disabled={saveLlm.isPending}
              onClick={() => {
                setTestResult("");
                saveLlm.mutate();
              }}
            >
              保存
            </Button>
            <Button variant="secondary" disabled={testing} onClick={testLlm}>
              {testing ? (
                <>
                  <Spinner /> 测试中…
                </>
              ) : (
                "测试连接"
              )}
            </Button>
          </div>
          {testResult && (
            <p className={`text-sm ${testResult.startsWith("✅") ? "text-green-600" : "text-red-600"}`}>
              {testResult}
            </p>
          )}
          {saveLlm.isError && <p className="text-sm text-red-600">{saveLlm.error.message}</p>}

          {/* 场景化模型（PRD §5.7：便宜模型做生成、强模型做费曼评价） */}
          <div className="border-t border-gray-100 pt-4">
            <h3 className="text-sm font-semibold text-gray-900">场景模型（留空 = 使用主配置）</h3>
            <div className="mt-3 space-y-4">
              {SCENE_META.map((s) => (
                <div key={s.name} className="rounded-lg border border-gray-100 bg-gray-50/60 p-3">
                  <div className="text-sm font-medium text-gray-800">{s.label}</div>
                  <div className="mt-0.5 text-xs text-gray-400">{s.hint}</div>
                  <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
                    <Input
                      value={scenes[s.name].base_url}
                      onChange={(e) =>
                        setScenes((prev) => ({
                          ...prev,
                          [s.name]: { ...prev[s.name], base_url: e.target.value },
                        }))
                      }
                      placeholder="Base URL（可空）"
                    />
                    <Input
                      type="password"
                      value={scenes[s.name].api_key}
                      onChange={(e) =>
                        setScenes((prev) => ({
                          ...prev,
                          [s.name]: { ...prev[s.name], api_key: e.target.value },
                        }))
                      }
                      placeholder={
                        settings?.scenes?.[s.name]?.api_key
                          ? `已保存：${settings.scenes[s.name].api_key}`
                          : "API Key（可空，用主配置的）"
                      }
                    />
                    <Input
                      value={scenes[s.name].model}
                      onChange={(e) =>
                        setScenes((prev) => ({
                          ...prev,
                          [s.name]: { ...prev[s.name], model: e.target.value },
                        }))
                      }
                      placeholder="模型名（可空）"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 学习偏好 */}
      <section className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">学习偏好</h2>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">每日新卡上限</label>
            <Input
              type="number"
              min={0}
              value={prefs.daily_new_cards}
              onChange={(e) => setPrefs({ ...prefs, daily_new_cards: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">每章篇幅（字）</label>
            <Input
              type="number"
              min={500}
              step={500}
              value={prefs.chapter_length}
              onChange={(e) => setPrefs({ ...prefs, chapter_length: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">费曼最大追问轮数</label>
            <Input
              type="number"
              min={1}
              max={10}
              value={prefs.feynman_max_rounds}
              onChange={(e) => setPrefs({ ...prefs, feynman_max_rounds: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">每知识点练习数</label>
            <Input
              type="number"
              min={1}
              max={4}
              value={prefs.exercises_per_kp}
              onChange={(e) => setPrefs({ ...prefs, exercises_per_kp: Number(e.target.value) })}
            />
          </div>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={prefs.auto_create_cards}
            onChange={(e) => setPrefs({ ...prefs, auto_create_cards: e.target.checked })}
          />
          文档生成后自动为知识点创建复习卡
        </label>
        <div className="mt-3">
          <label className="mb-1 block text-sm font-medium text-gray-700">
            GitHub 仓库（更新检查用，格式 owner/repo；留空禁用）
          </label>
          <Input
            value={prefs.github_repo}
            onChange={(e) => setPrefs({ ...prefs, github_repo: e.target.value })}
            placeholder="如 your-name/learnflow"
          />
        </div>
        <div className="mt-3">
          <label className="mb-1 block text-sm font-medium text-gray-700">划线高亮颜色</label>
          <div className="flex flex-wrap items-center gap-4">
            {HL_COLOR_KEYS.map((k: AnnotationColor) => (
              <label key={k} className="flex items-center gap-1.5 text-xs text-gray-600">
                <input
                  type="color"
                  value={prefs.highlight_colors?.[k] || HL_DEFAULTS[k]}
                  onChange={(e) =>
                    setPrefs({
                      ...prefs,
                      highlight_colors: { ...prefs.highlight_colors, [k]: e.target.value },
                    })
                  }
                  className="h-7 w-9 cursor-pointer rounded border border-gray-200 bg-white p-0.5"
                />
                {HL_LABELS[k]}
              </label>
            ))}
            <button
              type="button"
              onClick={() => setPrefs({ ...prefs, highlight_colors: {} })}
              className="text-xs text-gray-400 underline-offset-2 transition hover:text-gray-600 hover:underline"
            >
              恢复默认
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-400">影响阅读器划线底色与标注卡片色板，保存偏好后生效。</p>
        </div>
        <Button className="mt-4" disabled={savePrefs.isPending} onClick={() => savePrefs.mutate()}>
          保存偏好
        </Button>
      </section>

      {/* 代码运行环境（沙箱工具链检测 + 一键便携安装） */}
      <RuntimeEnvSection />

      {/* 数据 */}
      <section className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">数据</h2>
        <p className="mt-1 text-xs text-gray-500">
          所有数据保存在本地 <code className="rounded bg-gray-100 px-1">backend/data/</code>{" "}
          目录（SQLite + 纯 Markdown 文档）。复制该目录即可备份；文档可用 git 管理。
        </p>
        <Button
          className="mt-3"
          variant="secondary"
          onClick={() => api.settings.openDataDir().catch((e) => alert(e.message))}
        >
          打开数据目录
        </Button>
      </section>

      {/* 关于 */}
      <section className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">
          关于 LearnFlow{" "}
          {version && <span className="ml-1 text-sm font-normal text-gray-400">v{version}</span>}
        </h2>
        <div className="mt-3 flex items-center gap-3">
          <Button variant="secondary" disabled={checkingUpdate} onClick={() => checkUpdate(true)}>
            {checkingUpdate ? (
              <>
                <Spinner /> 检查中…
              </>
            ) : (
              "检查更新"
            )}
          </Button>
          {updateResult && <span className="text-sm text-gray-600">{updateResult}</span>}
        </div>
        <p className="mt-2 text-xs text-gray-400">
          打开应用时会自动检查一次（静默，失败不影响使用）；仓库发布 GitHub Release 后生效。
        </p>
      </section>
    </div>
  );
}
