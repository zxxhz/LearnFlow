/* zcode-workflow
description: LearnFlow 全链路质量门禁与回归验证工作流：前端类型检查、生产构建测试、后端语法编译与 113 项全量烟雾跑测
whenToUse: 每次提交代码、完成功能开发或在发版前，需要一键验证前后端完整质量状态时使用
args: {}
*/
interface GateItem {
  gate: string;
  status: "PASS" | "FAIL";
  details: string;
}

interface Finding {
  where: string;
  what: string;
  evidence: string;
  severity: "high" | "medium" | "low";
  status: "verified" | "unconfirmed";
}

interface WorkflowReport {
  conclusion: string;
  findings: Finding[];
  verified: string[];
  notCovered: string[];
}

log("开始执行 LearnFlow 全链路质量门禁与回归验证工作流");
const items: GateItem[] = [];

phase("前端 TypeScript 类型检查");
const tsc = await world.run("cmd.exe", ["/c", "cd frontend && npx tsc --noEmit"], {
  timeoutMs: 120_000,
});
items.push({
  gate: "前端 TypeScript 静态类型检查",
  status: tsc.exitCode === 0 ? "PASS" : "FAIL",
  details: tsc.exitCode === 0 ? "全部类型校验通过，零编译错误" : (tsc.stderr || tsc.stdout),
});
log(`前端类型检查: ${tsc.exitCode === 0 ? "通过" : "失败"}`);

phase("前端 Vite 生产构建测试");
const feBuild = await world.run("cmd.exe", ["/c", "cd frontend && npm run build"], {
  timeoutMs: 180_000,
});
items.push({
  gate: "前端 Vite 生产包构建打包",
  status: feBuild.exitCode === 0 ? "PASS" : "FAIL",
  details: feBuild.exitCode === 0 ? "静态产物打包成功并输出至 backend/app/static" : (feBuild.stderr || feBuild.stdout),
});
log(`前端生产构建: ${feBuild.exitCode === 0 ? "通过" : "失败"}`);

phase("后端 Python 字节码全量编译检查");
const pyCompile = await world.run("cmd.exe", ["/c", "python -m compileall -q backend/app"], {
  timeoutMs: 60_000,
});
items.push({
  gate: "后端 Python 字节码语法检查",
  status: pyCompile.exitCode === 0 ? "PASS" : "FAIL",
  details: pyCompile.exitCode === 0 ? "backend/app 下全部 Python 源码语法编译无错" : (pyCompile.stderr || pyCompile.stdout),
});
log(`后端源码编译: ${pyCompile.exitCode === 0 ? "通过" : "失败"}`);

phase("隔离环境 113 项全量烟雾测试回归");
const smoke = await world.run("cmd.exe", [
  "/c",
  "cd backend && uv run python scripts/smoke_test.py",
], { timeoutMs: 300_000 });
items.push({
  gate: "后端 113 项自动化 Smoke 跑测",
  status: smoke.exitCode === 0 ? "PASS" : "FAIL",
  details: smoke.exitCode === 0 ? "113 项业务与安全断言全数通过" : (smoke.stderr || smoke.stdout),
});
log(`烟雾测试跑测: ${smoke.exitCode === 0 ? "通过" : "失败"}`);

phase("门禁状态判定与诊断分析");
const allPassed = items.every((i) => i.status === "PASS");
let diagnosisText = "全部门禁项目均绿灯通过，代码处于可发布健康状态。";

if (!allPassed) {
  const failureSummary = items
    .filter((i) => i.status === "FAIL")
    .map((i) => `【${i.gate}】失败日志：\n${i.details}`)
    .join("\n\n");

  const analyst = agent("门禁分析诊断员", {
    system: "你是资深质量与 DevOps 架构师。负责分析前后端门禁失败的根本原因，给出清晰、可执行的代码修复指引。",
  });

  diagnosisText = await analyst.ask<string>(
    `以下检查项未通过：\n${failureSummary}\n请分析失败根因并给出精准的修复建议。`
  );
} else {
  const reporter = agent("质量验证员");
  diagnosisText = await reporter.ask<string>(
    "四项质量门禁全部顺利通过，请用简练专业的语言生成本次质量验收的评定总结。"
  );
}

for (const item of items) {
  report(item);
}

const markdownReport = [
  "# LearnFlow 质量门禁与回归验证报告",
  "",
  `**总体评定**：${allPassed ? "✅ 全部通过 (HEALTHY)" : "❌ 存在阻断项 (BLOCKED)"}`,
  "",
  "### 检查项明细",
  ...items.map((i) => `- [${i.status === "PASS" ? "x" : " "}] **${i.gate}**：${i.status === "PASS" ? "通过" : "失败"}`),
  "",
  "### 诊断与建议",
  diagnosisText,
].join("\n");

await artifact.markdown("quality-report", markdownReport, {
  title: "LearnFlow 质量门禁验证报告",
  description: `四项前后端全链路质量检查：${allPassed ? "全部通过" : "发现不合格项"}`,
  primary: true,
});

return {
  conclusion: allPassed ? "全链路质量门禁全部通过，代码健康可靠。" : "质量门禁存在失败项，请根据报告建议修复后再行合并或发版。",
  findings: items.filter((i) => i.status === "FAIL").map((i) => ({
    where: i.gate,
    what: "检查项未通过门禁",
    evidence: i.details.slice(0, 500),
    severity: "high" as const,
    status: "verified" as const,
  })),
  verified: items.filter((i) => i.status === "PASS").map((i) => i.gate),
  notCovered: [],
};
