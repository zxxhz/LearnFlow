/* zcode-workflow
description: 多 Agent 协同代码体检与安全审查工作流：并行分发安全、并发数据、多模态与前端专项审查并汇聚分级交付
whenToUse: 当需要对项目进行全量或增量代码审查、寻找安全漏洞与并发/数据隐患时使用
args:
  scope:
    type: string
    description: 审查范围：'all'（全量）或 'recent'（近期版本/改动）
    default: recent
*/
interface Finding {
  /** 文件路径与行号，例如 backend/app/main.py:45 */
  where: string;
  /** 缺陷或隐患概述 */
  what: string;
  /** 触发路径或代码证据 */
  evidence: string;
  /** 严重级别 */
  severity: "high" | "medium" | "low";
  /** 确认状态 */
  status: "verified" | "unconfirmed";
  /** 修复建议 */
  recommendation?: string;
}

interface DomainAudit {
  summary: string;
  findings: Finding[];
  reviewedFiles: string[];
}

interface FinalSynthesis {
  conclusion: string;
  findings: Finding[];
  verified: string[];
  notCovered: string[];
  reportMarkdown: string;
}

const auditScope = String(args.scope ?? "recent");
log(`开始执行 LearnFlow 深度代码体检工作流，审查范围：${auditScope}`);

phase("收集近期改动与审查上下文");
const gitStatus = await git.status();
const recentCommits = await git.log(10);
const changedFiles = await git.changedFiles();
const contextSummary = `当前分支: ${gitStatus.branch ?? "main"}, 树干净: ${gitStatus.clean}\n近期 10 次提交: ${recentCommits.map((c) => `${c.hash.slice(0, 7)} ${c.subject}`).join(" | ")}\n当前改动文件数: ${changedFiles.length}`;

phase("并行分发四大专业领域深度审查");
const secReviewer = agent("安全与防线审查员", {
  system: "你是资深安全架构师。专门审查 LearnFlow 的网络与系统安全。重点覆盖：backend/app/main.py 的 _AccessGuard（CSRF/Origin/Host/IPv6 括号格式校验）、services/update.py（镜像加速源白名单限制、下载包 SHA-256 完整性强校验、安装器启动与进程清理）、services/images.py（反解压炸弹 MAX_PIXELS 像素上限、路径穿越防护）、执行沙箱的安全边界。不要修改代码，只指出确切的代码缺陷与风险。",
});

const dbReviewer = agent("并发与数据一致性审查员", {
  system: "你是资深数据库与高并发架构师。专门审查 LearnFlow 的数据一致性与并发安全。重点覆盖：SQLite WAL 模式与并发事务处理、_bank_lock / _mm_lock 进程内互斥锁、题目替换/修剪时的 Jaccard 相似度对齐与做题历史（Attempt/WrongPool）重算、批量删除分批（500 限额规避 SQLite 变量超限）。不要修改代码，只指出确切的代码缺陷与风险。",
});

const aiReviewer = agent("多模态与流式响应审查员", {
  system: "你是资深 AI 工程与多模态架构师。专门审查 LearnFlow 的视觉处理与流式生成链路。重点覆盖：Pillow 图像压缩与 EXIF 方向纠正、SSE 确定性释放（finally 释放 deltas.aclose()）、KaTeX 批量节流渲染避免页面卡死、提示词系统规则与防对抗设计。不要修改代码，只指出确切的代码缺陷与风险。",
});

const feReviewer = agent("前端交互与健壮性审查员", {
  system: "你是资深前端架构师。专门审查 LearnFlow 的 React 前端实现。重点覆盖：Layout 响应式折叠（Tab 键盘无障碍焦点不可见、快捷键防冲突）、路由完整性与错误边界、Blob URL 内存生命周期泄漏（URL.revokeObjectURL 及时释放）、模态框在异常网络/空材料状态下的容错与用户反馈。不要修改代码，只指出确切的代码缺陷与风险。",
});

const [secAudit, dbAudit, aiAudit, feAudit] = await Promise.all([
  secReviewer.ask<DomainAudit>(`请对【安全与网络防线】进行深度代码审查。\n审查范围: ${auditScope}\n背景: ${contextSummary}\n请给出具体的文件行号、证据与缺陷。`),
  dbReviewer.ask<DomainAudit>(`请对【并发与数据一致性】进行深度代码审查。\n审查范围: ${auditScope}\n背景: ${contextSummary}\n请给出具体的文件行号、证据与缺陷。`),
  aiReviewer.ask<DomainAudit>(`请对【多模态与流式响应】进行深度代码审查。\n审查范围: ${auditScope}\n背景: ${contextSummary}\n请给出具体的文件行号、证据与缺陷。`),
  feReviewer.ask<DomainAudit>(`请对【前端交互与健壮性】进行深度代码审查。\n审查范围: ${auditScope}\n背景: ${contextSummary}\n请给出具体的文件行号、证据与缺陷。`),
]);

phase("汇聚审查成果并出具分级交付报告");
const leadJudge = agent("审查汇总裁判", {
  system: "你是代码审查委员会主席。请汇总四大维度的审查发现，去除重复项，按 P0（致命故障/安全漏洞）、P1（严重缺陷/数据丢失）、P2（边缘 Bug/偶发异常）、P3（体验/代码异味）统一分级，给出总体结论与 Markdown 格式的完整交付报告。",
});

const allAuditsJson = JSON.stringify({
  security: secAudit,
  database: dbAudit,
  ai_pipeline: aiAudit,
  frontend: feAudit,
});

const synthesis = await leadJudge.ask<FinalSynthesis>(
  `请综合评估并汇总以下审查结果：\n${allAuditsJson}\n输出结构化的整体结论、去重后的 findings 清单以及格式完备的 Markdown 报告。`
);

for (const finding of synthesis.findings) {
  report(finding);
}

await artifact.markdown("review-report", synthesis.reportMarkdown, {
  title: "LearnFlow 代码体检与安全审查报告",
  description: `覆盖安全、数据库、多模态与前端的深度审查，共发现 ${synthesis.findings.length} 项关注点`,
  primary: true,
});

return {
  conclusion: synthesis.conclusion,
  findings: synthesis.findings,
  verified: synthesis.verified,
  notCovered: synthesis.notCovered,
};
