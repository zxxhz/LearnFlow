// 设置页：LLM 配置（OpenAI 兼容）+ 学习偏好 + 数据目录（PRD §5.7）
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { LLMConfig, Preferences } from "../../lib/types";
import { Button, Input, Spinner } from "../../components/ui";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [llm, setLlm] = useState<LLMConfig>({ base_url: "", api_key: "", model: "", temperature: 0.7 });
  const [prefs, setPrefs] = useState<Preferences>({
    daily_new_cards: 20,
    chapter_length: 3000,
    feynman_max_rounds: 4,
    auto_create_cards: true,
  });
  const [saveMsg, setSaveMsg] = useState("");

  useEffect(() => {
    if (settings) {
      setLlm({ ...settings.llm, api_key: "" }); // key 留空 = 不修改
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
  const testLlm = async () => {
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
        </div>
      </section>

      {/* 学习偏好 */}
      <section className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">学习偏好</h2>
        <div className="mt-4 grid grid-cols-3 gap-3">
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
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={prefs.auto_create_cards}
            onChange={(e) => setPrefs({ ...prefs, auto_create_cards: e.target.checked })}
          />
          文档生成后自动为知识点创建复习卡
        </label>
        <Button className="mt-4" disabled={savePrefs.isPending} onClick={() => savePrefs.mutate()}>
          保存偏好
        </Button>
      </section>

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
    </div>
  );
}
