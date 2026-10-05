// 设置页：LLM 配置（OpenAI 兼容）+ 学习偏好 + 数据目录（PRD §5.7）
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { AnnotationColor, AdhdMode, LLMConfig, Preferences, SceneLLMConfig, SceneName, SettingsData } from "../../lib/types";
import DataSafetySection from "./DataSafetySection";
import { Button, Input, Select, Spinner } from "../../components/ui";
import { HL_COLOR_KEYS, HL_DEFAULTS, HL_LABELS } from "../reader/colors";
import RuntimeEnvSection from "./RuntimeEnvSection";


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
];

const EMPTY_SCENE: SceneLLMConfig = { base_url: "", api_key: "", model: "" };

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [llm, setLlm] = useState<LLMConfig>({ base_url: "", api_key: "", model: "" });
  const [scenes, setScenes] = useState<Record<SceneName, SceneLLMConfig>>({
    generation: { ...EMPTY_SCENE },
    chat: { ...EMPTY_SCENE },
  });
  const [prefs, setPrefs] = useState<Preferences>({
    chapter_length: 3000,
    exercises_per_kp: 3,
    highlight_colors: {},
    auto_highlight: true,
    adhd_mode: "off",
  });

  const [ollamaModels, setOllamaModels] = useState<string[] | null>(null);
  const [saveMsg, setSaveMsg] = useState("");
  const [sceneOpen, setSceneOpen] = useState(false); // 场景模型默认折叠

  useEffect(() => {
    if (settings) {
      setLlm({ ...settings.llm, api_key: "" }); // key 留空 = 不修改
      setScenes({
        generation: { ...EMPTY_SCENE, ...settings.scenes?.generation, api_key: "" },
        chat: { ...EMPTY_SCENE, ...settings.scenes?.chat, api_key: "" },
      });
      setPrefs({ auto_highlight: true, ...settings.preferences });
    }
  }, [settings]);

  const saveLlm = useMutation({
    mutationFn: () =>
      api.settings.update({
        llm: {
          base_url: llm.base_url,
          model: llm.model,
          ...(llm.api_key ? { api_key: llm.api_key } : {}),
        },
        scenes: {
          generation: {
            ...scenes.generation,
            ...(scenes.generation.api_key ? {} : { api_key: undefined }),
          },
          chat: { ...scenes.chat, ...(scenes.chat.api_key ? {} : { api_key: undefined }) },
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
      if (r.has_update) {
        // 更新全局缓存并通知 Layout 弹出更新弹窗（无视本会话已忽略）
        queryClient.setQueryData(["update-check"], r);
        window.dispatchEvent(new CustomEvent("learnflow:update-found", { detail: r }));
        setUpdateResult(`🎉 有新版本 ${r.latest}（当前 ${r.current}）`);
      } else {
        setUpdateResult(
          r.error ? `ℹ️ ${r.error}` : `✅ 已是最新版本（${r.current}）`
        );
      }
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
    <div className="mx-auto max-w-5xl p-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">设置</h1>
      {saveMsg && <span className="ml-3 text-sm text-green-600 dark:text-green-400">{saveMsg}</span>}

      {/* LLM 服务 */}
      <section className="mt-6 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">LLM 服务（OpenAI 兼容）</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          支持智谱 GLM、DeepSeek、OpenAI 等任何 OpenAI 兼容端点。API Key 留空表示不修改。
        </p>
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-gray-500 dark:text-gray-400">快捷填入：</span>
            {PROVIDER_PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => setLlm((prev) => ({ ...prev, base_url: p.base_url, model: p.model }))}
                className="rounded-full border border-gray-200 dark:border-gray-700 px-2.5 py-1 text-gray-600 dark:text-gray-400 hover:border-brand-500 hover:text-brand-600"
                title={`${p.base_url}（模型：${p.model}，可再手改）`}
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={async () => {
                try {
                  setOllamaModels(null);
                  const r = await api.settings.ollamaModels();
                  setOllamaModels(r.models);
                  if (r.models.length > 0) {
                    setLlm((prev) => ({ ...prev, base_url: "http://localhost:11434/v1", model: r.models[0] }));
                  }
                } catch (e) {
                  alert((e as Error).message);
                }
              }}
              className="rounded-full border border-gray-200 dark:border-gray-700 px-2.5 py-1 text-gray-600 dark:text-gray-400 hover:border-brand-500 hover:text-brand-600"
              title="查询本机 Ollama 已装模型并自动填入"
            >
              检测本机 Ollama
            </button>
            {ollamaModels && (
              <span className="text-gray-400 dark:text-gray-500">
                {ollamaModels.length > 0 ? `发现 ${ollamaModels.length} 个本地模型，已填入第一个` : "Ollama 在线但没有已安装的模型"}
              </span>
            )}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">Base URL</label>
            <Input
              value={llm.base_url}
              onChange={(e) => setLlm({ ...llm, base_url: e.target.value })}
              placeholder="https://open.bigmodel.cn/api/paas/v4 或 https://api.deepseek.com/v1"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">API Key</label>
            <Input
              type="password"
              value={llm.api_key}
              onChange={(e) => setLlm({ ...llm, api_key: e.target.value })}
              placeholder={settings?.llm.api_key ? `已保存：${settings.llm.api_key}` : "sk-…"}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">模型名</label>
              <Input
                value={llm.model}
                onChange={(e) => setLlm({ ...llm, model: e.target.value })}
                placeholder="glm-4-flash / deepseek-chat"
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
            <p className={`text-sm ${testResult.startsWith("✅") ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
              {testResult}
            </p>
          )}
          {saveLlm.isError && <p className="text-sm text-red-600 dark:text-red-400">{saveLlm.error.message}</p>}

          {/* 场景化模型（PRD §5.7：便宜模型做生成）——默认折叠，点开展开 */}
          <div className="border-t border-gray-100 dark:border-gray-800 pt-4">
            <button
              type="button"
              className="flex w-full items-center justify-between text-left"
              onClick={() => setSceneOpen((v) => !v)}
            >
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">场景模型（留空 = 使用主配置）</span>
              <span className="text-xs text-gray-400 dark:text-gray-500">{sceneOpen ? "收起 ▾" : "展开 ▸"}</span>
            </button>
            {sceneOpen && (
            <div className="mt-3 space-y-4">
              {SCENE_META.map((s) => (
                <div key={s.name} className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/60 p-3">
                  <div className="text-sm font-medium text-gray-800 dark:text-gray-200">{s.label}</div>
                  <div className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{s.hint}</div>
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
            )}
          </div>
        </div>
      </section>

      {/* 学习偏好 */}
      <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">学习偏好</h2>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">每章篇幅（字）</label>
            <Input
              type="number"
              min={500}
              step={500}
              value={prefs.chapter_length}
              onChange={(e) => setPrefs({ ...prefs, chapter_length: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">每知识点关卡数</label>
            <Input
              type="number"
              min={1}
              max={4}
              value={prefs.exercises_per_kp}
              onChange={(e) => setPrefs({ ...prefs, exercises_per_kp: Number(e.target.value) })}
            />
          </div>
        </div>
        <div className="mt-3">
          <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">划线高亮颜色</label>
          <div className="flex flex-wrap items-center gap-4">
            {HL_COLOR_KEYS.map((k: AnnotationColor) => (
              <label key={k} className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
                <input
                  type="color"
                  value={prefs.highlight_colors?.[k] || HL_DEFAULTS[k]}
                  onChange={(e) =>
                    setPrefs({
                      ...prefs,
                      highlight_colors: { ...prefs.highlight_colors, [k]: e.target.value },
                    })
                  }
                  className="h-7 w-9 cursor-pointer rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-0.5"
                />
                {HL_LABELS[k]}
              </label>
            ))}
            <button
              type="button"
              onClick={() => setPrefs({ ...prefs, highlight_colors: {} })}
              className="text-xs text-gray-400 dark:text-gray-500 underline-offset-2 transition hover:text-gray-600 dark:hover:text-gray-300 hover:underline"
            >
              恢复默认
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">影响阅读器划线底色与标注卡片色板，保存偏好后生效。</p>
        </div>
        <div className="mt-4 border-t border-gray-100 dark:border-gray-800 pt-4">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 select-none cursor-pointer">
            <input
              type="checkbox"
              checked={prefs.auto_highlight ?? true}
              onChange={(e) => setPrefs({ ...prefs, auto_highlight: e.target.checked })}
              className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
            />
            <span>生成时自动划重点</span>
          </label>
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            生成新章节时，根据模型提炼与核心要点自动生成划线高亮。若关闭，则生成时不主动打标，仅在阅读时手动划选。
          </p>
        </div>
        <div className="mt-4 border-t border-gray-100 dark:border-gray-800 pt-4">
          <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            ADHD 模式
          </label>
          <div className="max-w-md">
            <Select
              value={prefs.adhd_mode ?? "off"}
              onChange={(e) => setPrefs({ ...prefs, adhd_mode: e.target.value as AdhdMode })}
            >
              <option value="off">关闭</option>
              <option value="a">A（段落交替底色 + 圆角）</option>
              <option value="b">B（鼠标移入聚焦高亮）</option>
            </Select>
            <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
              A 为开启后文章内每一段使用不同的背景颜色（段落周围带圆角）；B 为开启后鼠标移到段落区域即显示聚焦背景色，切换时具备流畅动效。
            </p>
            {/* 实时微缩预览 */}
            <div className="mt-2.5 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50/60 dark:bg-gray-850 p-2.5 text-xs text-gray-600 dark:text-gray-400">
              <span className="text-[11px] text-gray-400 dark:text-gray-500">效果预览：</span>
              <div className="mt-1.5 space-y-1.5">
                <div
                  className={`px-3 py-1.5 ${
                    prefs.adhd_mode === "a"
                      ? "adhd-para adhd-color-0"
                      : prefs.adhd_mode === "b"
                      ? "adhd-para adhd-mode-b"
                      : "rounded bg-white dark:bg-gray-800"
                  }`}
                >
                  第 1 段示例：注意力集中，通过视觉提示锚定阅读进度。
                </div>
                <div
                  className={`px-3 py-1.5 ${
                    prefs.adhd_mode === "a"
                      ? "adhd-para adhd-color-1"
                      : prefs.adhd_mode === "b"
                      ? "adhd-para adhd-mode-b"
                      : "rounded bg-white dark:bg-gray-800"
                  }`}
                >
                  第 2 段示例：{prefs.adhd_mode === "b" ? "将鼠标移动到这里试试聚焦动效" : "交替柔和底色防止阅读串行。"}
                </div>
              </div>
            </div>
          </div>
        </div>
        <Button className="mt-4" disabled={savePrefs.isPending} onClick={() => savePrefs.mutate()}>

          保存偏好
        </Button>
      </section>

      {/* 代码运行环境（沙箱工具链检测 + 一键便携安装） */}
      <RuntimeEnvSection />

      {/* 数据与安全：备份 / 恢复 / 局域网访问令牌 */}
      <DataSafetySection />

      {/* 数据 */}
      <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">数据</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          所有数据保存在本地 <code className="rounded bg-gray-100 dark:bg-gray-800 px-1">backend/data/</code>{" "}
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
      <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          关于 LearnFlow{" "}
          {version && <span className="ml-1 text-sm font-normal text-gray-400 dark:text-gray-500">v{version}</span>}
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
          {updateResult && <span className="text-sm text-gray-600 dark:text-gray-400">{updateResult}</span>}
        </div>
        <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
          打开应用时会自动检查一次（静默，失败不影响使用）；仓库发布 GitHub Release 后生效。
        </p>
      </section>
    </div>
  );
}
