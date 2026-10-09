import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { LearnerProfile } from "../../lib/types";

export const LearnerProfileSection: React.FC = () => {
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [summaryInput, setSummaryInput] = useState("");
  const [socraticMode, setSocraticMode] = useState(true);
  const [confirmReset, setConfirmReset] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const showFeedback = (type: "success" | "error", text: string) => {
    setFeedback({ type, text });
    setTimeout(() => {
      setFeedback((cur) => (cur?.text === text ? null : cur));
    }, 3500);
  };

  const fetchProfile = async () => {
    try {
      setLoading(true);
      const data = await api.profile.get();
      setProfile(data);
      setSummaryInput(data.background_summary || "");
      setSocraticMode(data.socratic_mode ?? true);
    } catch (err: any) {
      showFeedback("error", err.message || "获取学习者画像失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  const handleSave = async () => {
    try {
      setSaving(true);
      const updated = await api.profile.update({
        background_summary: summaryInput,
        socratic_mode: socraticMode,
      });
      setProfile(updated);
      showFeedback("success", "学习者认知画像与偏好已保存");
    } catch (err: any) {
      showFeedback("error", err.message || "保存画像失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteMisconception = async (id: string, topic: string) => {
    try {
      const updated = await api.profile.deleteMisconception(id);
      setProfile(updated);
      showFeedback("success", `已标记掌握并从画像移除「${topic}」`);
    } catch (err: any) {
      showFeedback("error", err.message || "移除失败");
    }
  };

  const handleReset = async () => {
    try {
      setResetting(true);
      const updated = await api.profile.reset();
      setProfile(updated);
      setSummaryInput("");
      setSocraticMode(true);
      setConfirmReset(false);
      showFeedback("success", "已重置学习者画像");
    } catch (err: any) {
      showFeedback("error", err.message || "重置失败");
    } finally {
      setResetting(false);
    }
  };

  const hasChanges =
    profile !== null &&
    (summaryInput !== (profile.background_summary || "") ||
      socraticMode !== (profile.socratic_mode ?? true));

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-gray-100 dark:border-gray-800">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">🧑‍🎓</span>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              学习者画像与认知档案
            </h2>
            <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-400 border border-brand-200/60 dark:border-brand-800/60">
              AI 动态演进
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            系统会在你阅读划线提问、伴学助教对话、题库错题答疑时无感提炼认知特征与薄弱盲区；并在生成讲义与答疑时因材施教。你可以随时查看并修正。
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <button
            type="button"
            onClick={fetchProfile}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300 transition-colors"
          >
            {loading ? "加载中..." : "🔄 刷新"}
          </button>
          {!confirmReset ? (
            <button
              type="button"
              onClick={() => setConfirmReset(true)}
              disabled={loading || resetting}
              className="text-xs px-3 py-1.5 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
            >
              清空重置
            </button>
          ) : (
            <div className="flex items-center gap-1.5 bg-rose-50 dark:bg-rose-950/50 p-1 rounded-lg border border-rose-200 dark:border-rose-900/60">
              <span className="text-xs text-rose-600 dark:text-rose-400 pl-1">确定清空？</span>
              <button
                type="button"
                onClick={handleReset}
                disabled={resetting}
                className="text-xs px-2 py-1 rounded bg-rose-600 text-white font-medium hover:bg-rose-700"
              >
                {resetting ? "..." : "是"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmReset(false)}
                className="text-xs px-2 py-1 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
              >
                否
              </button>
            </div>
          )}
        </div>
      </div>

      {feedback && (
        <div
          className={`mt-4 p-3 rounded-lg text-xs font-medium flex items-center justify-between ${
            feedback.type === "success"
              ? "bg-green-50 dark:bg-green-950/60 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800/60"
              : "bg-red-50 dark:bg-red-950/60 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800/60"
          }`}
        >
          <span>{feedback.text}</span>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-xs opacity-60 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {loading && !profile ? (
        <div className="py-8 text-center text-xs text-gray-400">正在读取你的专属认知画像...</div>
      ) : (
        <div className="space-y-6 mt-5">
          {/* 基础认知与背景描述 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label
                htmlFor="learner-summary"
                className="text-sm font-medium text-gray-700 dark:text-gray-200 flex items-center gap-1.5"
              >
                <span>📝</span> 认知背景与风格偏好
              </label>
              <span className="text-xs text-gray-400">
                可自由补充专业、基础、擅长领域或特定讲解喜好
              </span>
            </div>
            <textarea
              id="learner-summary"
              rows={4}
              value={summaryInput}
              onChange={(e) => setSummaryInput(e.target.value)}
              placeholder="例如：非计算机专业转码学习者，已有 Python 基础但指针与递归概念较弱；喜欢生活化的具象比喻，希望代码示例多标注边界条件与陷阱..."
              className="w-full text-xs leading-relaxed p-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-800/50 text-gray-800 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:focus:ring-brand-400 transition"
            />
          </div>

          {/* 引导模式偏好 */}
          <div className="bg-gray-50 dark:bg-gray-850 rounded-xl p-4 border border-gray-100 dark:border-gray-800">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-gray-800 dark:text-gray-200 flex items-center gap-1.5">
                  <span>💡</span> 助教引导风格：
                  <span className="text-brand-600 dark:text-brand-400 font-semibold">
                    {socraticMode ? "苏格拉底启发式引导" : "直接解答剖析"}
                  </span>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {socraticMode
                    ? "通过层层追问、线索提示启发你自主推导正确思路，不直接剧透完整答案。"
                    : "直接指出症结所在并提供详尽逻辑拆解，适合快速查漏补缺。"}
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setSocraticMode(true)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition ${
                    socraticMode
                      ? "bg-brand-600 border-brand-600 text-white font-medium shadow-sm"
                      : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                  }`}
                >
                  启发式
                </button>
                <button
                  type="button"
                  onClick={() => setSocraticMode(false)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition ${
                    !socraticMode
                      ? "bg-brand-600 border-brand-600 text-white font-medium shadow-sm"
                      : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                  }`}
                >
                  直解式
                </button>
              </div>
            </div>
          </div>

          {/* 保存修改栏 */}
          <div className="flex items-center justify-end gap-3 pt-1">
            {hasChanges && (
              <span className="text-xs text-amber-600 dark:text-amber-400">存在未保存的修改</span>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !hasChanges}
              className={`text-xs px-4 py-2 rounded-xl font-medium transition shadow-sm ${
                hasChanges
                  ? "bg-brand-600 hover:bg-brand-700 text-white"
                  : "bg-gray-100 dark:bg-gray-800 text-gray-400 cursor-not-allowed"
              }`}
            >
              {saving ? "保存中..." : "保存画像设置"}
            </button>
          </div>

          {/* 薄弱点与易错概念池 */}
          <div className="pt-2 border-t border-gray-100 dark:border-gray-800">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-sm">🎯</span>
                <h3 className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  高频盲区与易错概念池
                </h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 font-mono">
                  {profile?.misconceptions?.length || 0}
                </span>
              </div>
              <span className="text-xs text-gray-400">点击「掌握」可将已理解概念从画像中剔除</span>
            </div>

            {(!profile?.misconceptions || profile.misconceptions.length === 0) ? (
              <div className="py-6 px-4 rounded-xl border border-dashed border-gray-200 dark:border-gray-800 text-center">
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  暂无记录。随着你在课程划线提问、伴学助教对话或错题复盘，系统将自动汇总易错卡点。
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {profile.misconceptions.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col justify-between p-3.5 rounded-xl border border-gray-200/80 dark:border-gray-800 bg-white dark:bg-gray-900/60 shadow-xs hover:border-brand-300 dark:hover:border-brand-700/60 transition group"
                  >
                    <div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-gray-800 dark:text-gray-100 line-clamp-1">
                          {item.topic}
                        </span>
                        {item.tag && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 border border-amber-200/60 dark:border-amber-800/60 shrink-0">
                            {item.tag}
                          </span>
                        )}
                      </div>
                      {item.evidence && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 line-clamp-2 leading-relaxed">
                          {item.evidence}
                        </p>
                      )}
                    </div>

                    <div className="mt-3 pt-2.5 border-t border-gray-100 dark:border-gray-800/80 flex items-center justify-end">
                      <button
                        type="button"
                        onClick={() => handleDeleteMisconception(item.id, item.topic)}
                        className="text-[11px] text-brand-600 dark:text-brand-400 hover:text-brand-700 dark:hover:text-brand-300 flex items-center gap-1 font-medium transition"
                      >
                        <span>✓</span> 已掌握，移除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
};
