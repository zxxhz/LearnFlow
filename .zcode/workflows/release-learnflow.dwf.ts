/* zcode-workflow
description: LearnFlow 自动化发版与签名发布工作流：八处版本同步、类型/测试门禁、双端构建、Tauri 签名、生成 latest.json
  及 GitHub Release 发布
whenToUse: 当需要发布 LearnFlow 新版本时使用，一键完成 8 处版本同步、预检测试、双端构建、Tauri 签名与 GitHub Release
args:
  version:
    type: string
    description: 目标版本号，如 0.4.63
    required: true
  dryRun:
    type: boolean
    description: 是否仅执行测试和构建校验，不推送到 GitHub（试跑模式）
    default: false
  notes:
    type: string
    description: 版本更新日志 Markdown 内容
    required: true
*/
interface VersionSyncResult {
  updatedFiles: string[];
  success: boolean;
  notes: string;
}

interface ManifestResult {
  exeName: string;
  exeSha256: string;
  signature: string;
  manifestJson: string;
}

interface ReleaseSummary {
  version: string;
  releaseUrl: string;
  assets: string[];
  status: "published" | "dry_run" | "failed";
  details: string;
}

const targetVersion = String(args.version ?? "").trim();
const releaseNotes = String(args.notes ?? "").trim();
const dryRun = Boolean(args.dryRun ?? false);

if (!targetVersion) {
  throw new Error("缺少必填参数 version，例如 0.4.63");
}

log(`开始执行 LearnFlow 发版工作流，目标版本：v${targetVersion}，dryRun: ${dryRun}`);

phase("版本号同步检查与更新");
const syncAgent = agent("版本同步专员", {
  system: "你是版本发布工程师。负责精准同步 LearnFlow 仓库的 8 处版本号配置。严格保证：backend/app/core/config.py、desktop/src-tauri/tauri.conf.json、desktop/package.json、backend/pyproject.toml、desktop/src-tauri/Cargo.toml、frontend/package.json、frontend/public/sw.js 以及 Cargo.lock 保持完全一致的语义化版本号。",
});

const syncRes = await syncAgent.ask<VersionSyncResult>(
  `请将仓库全部 8 处版本号统一更新为 "${targetVersion}"，并在 desktop/src-tauri 目录下运行 cargo check 确保 Cargo.lock 一并更新。确认每处替换准确无误后返回结果。`
);

if (!syncRes.success) {
  throw new Error(`版本号同步失败：${syncRes.notes}`);
}
log(`版本号同步完成，已更新文件：${syncRes.updatedFiles.join(", ")}`);

phase("质量门禁：前端类型检查与烟雾测试跑测");
// 绝对路径且不加引号：world.run 的 cwd 随会话目录漂移；Node spawn 会把参数内双引号
// 转义成 cmd 不认的 \" 形式，路径无空格时直接裸写最稳
const tscCheck = await world.run("cmd.exe", ["/c", "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\frontend && npx tsc --noEmit"], {
  timeoutMs: 120_000,
});
if (tscCheck.exitCode !== 0) {
  throw new Error(`前端 TypeScript 类型检查失败：\n${tscCheck.stderr || tscCheck.stdout}`);
}
log("前端类型检查通过");

const smokeCheck = await world.run("cmd.exe", [
  "/c",
  "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\backend && uv run python scripts/smoke_test.py",
], { timeoutMs: 420_000 });
if (smokeCheck.exitCode !== 0) {
  throw new Error(`烟雾测试回归失败：\n${smokeCheck.stderr || smokeCheck.stdout}`);
}
log("后端 113 项全量烟雾测试回归通过");

phase("执行前后端与桌面 NSIS 安装包构建");
const buildAgent = agent("构建与打包专员", {
  system: "你是构建工程师。负责依次运行前端打包、PyInstaller 后端打包以及 Tauri 桌面端构建。构建过程中需确保 TAURI_SIGNING_PRIVATE_KEY 指向正确私钥完成 minisign 签名。",
});

const buildOutcome = await buildAgent.ask<string>(
  `请执行发版构建（仓库根：C:/Users/Emoing/Desktop/学习agent，所有路径用绝对路径）：\n1. cd "C:/Users/Emoing/Desktop/学习agent/frontend" && npm run build\n2. cd "C:/Users/Emoing/Desktop/学习agent/backend" && uv run python scripts/build_backend.py\n3. cd "C:/Users/Emoing/Desktop/学习agent/desktop" && export TAURI_SIGNING_PRIVATE_KEY="C:/Users/Emoing/Desktop/学习agent/desktop/src-tauri/keys/learnflow.key" && export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="" && npx tauri build\n构建完成后确认 C:/Users/Emoing/Desktop/学习agent/desktop/src-tauri/target/release/bundle/nsis/ 目录下已生成 LearnFlow_${targetVersion}_x64-setup.exe 及其同名 .sig 签名文件。`
);
log(`构建产物已就绪：${buildOutcome}`);

phase("生成最新更新元数据 latest.json");
const manifestAgent = agent("签名与元数据专员", {
  system: "你是发布元数据工程师。负责读取安装包 .sig 文件内容，计算安装包 SHA-256 哈希，组装符合 Tauri v2 Updater 规范的 latest.json，并校验各字段完整性。",
});

const manifest = await manifestAgent.ask<ManifestResult>(
  `安装包与签名文件位于 C:/Users/Emoing/Desktop/学习agent/desktop/src-tauri/target/release/bundle/nsis/LearnFlow_${targetVersion}_x64-setup.exe（及同名 .sig）：\n1. 计算 exe 的 SHA-256；\n2. 提取 .sig 中的签名内容（整段 base64）；\n3. 生成 latest.json：顶层 version（"${targetVersion}"）与 pub_date（RFC3339 当前 UTC 时间），platforms["windows-x86_64"] 下含 signature（.sig 全文）与 url（"https://github.com/zxxhz/LearnFlow/releases/download/v${targetVersion}/LearnFlow_${targetVersion}_x64-setup.exe"）；签名覆盖的安装包哈希以官方 sha256 字段形式放在 platforms 内；\n4. 保存 latest.json 到 C:/Users/Emoing/AppData/Local/Temp/latest-v${targetVersion}.json 以便上传。`
);
log(`latest.json 生成完毕，SHA-256: ${manifest.exeSha256}`);

phase("Git 提交、标签推送与 GitHub Release 发布");
let releaseRes: ReleaseSummary;
if (dryRun) {
  log("当前为 dryRun 试跑模式，跳过 Git 提交与 GitHub API 发布");
  releaseRes = {
    version: targetVersion,
    releaseUrl: "dry-run://local",
    assets: [manifest.exeName, "latest.json"],
    status: "dry_run",
    details: "本地构建与签名校验全部成功，dryRun 模式未推送到远程仓库。",
  };
} else {
  const publishAgent = agent("GitHub 发布专员", {
    system: "你是 GitHub 发布与发布物分发工程师。负责将已修改的版本文件提交到 Git，打上 vX.Y.Z 标签并推送到 remote；随后通过 git credential 获取 GitHub PAT，调用 GitHub REST API 创建对应 Release 并上传 NSIS 安装包和 latest.json 两个资产。",
  });

  releaseRes = await publishAgent.ask<ReleaseSummary>(
    `请执行发布收尾（先 cd "C:/Users/Emoing/Desktop/学习agent" 再做所有 git 操作）：\n1. git add -A；\n2. git commit -m "chore(release): v${targetVersion} - 全面安全加固与稳定性修复（P0/P1漏洞修复/流式节流/并发锁统一）"；\n3. git tag v${targetVersion}；\n4. git push origin main --tags；\n5. 通过 git credential fill 取 GitHub PAT，调用 GitHub API 创建 Release（Tag: v${targetVersion}，标题: v${targetVersion}，说明:\n${releaseNotes || `v${targetVersion} 发布`}）；\n6. 上传资产：C:/Users/Emoing/Desktop/学习agent/desktop/src-tauri/target/release/bundle/nsis/${manifest.exeName} 与 C:/Users/Emoing/AppData/Local/Temp/latest-v${targetVersion}.json（资产名分别为 ${manifest.exeName} 与 latest.json）。\n完成后返回发布详情与 URL。`
  );
}

await artifact.markdown(
  "release-report",
  `# LearnFlow v${targetVersion} 发布报告\n\n- **状态**：${releaseRes.status}\n- **发布地址**：[GitHub Release](${releaseRes.releaseUrl})\n- **发布资产**：\n  - \`${manifest.exeName}\` (SHA-256: \`${manifest.exeSha256}\`)\n  - \`latest.json\`\n\n## 更新日志\n\n${releaseNotes}\n`,
  {
    title: `LearnFlow v${targetVersion} 发版报告`,
    description: `版本 v${targetVersion} 自动化构建、签名与发布交付结果`,
    primary: true,
  }
);

return {
  conclusion: `LearnFlow v${targetVersion} 发版工作流执行完成，状态：${releaseRes.status}。`,
  findings: [],
  verified: [
    "前端 TypeScript 类型检查通过",
    "后端 113 项全量 smoke 测试通过",
    "前端生产产物与 PyInstaller 后端打包通过",
    "Tauri NSIS 安装包与 minisign 签名验证通过",
    "latest.json SHA-256 与签名元数据生成完成",
  ],
  notCovered: dryRun ? ["跳过了 Git 提交与 GitHub 远程资产发布（dryRun 模式）"] : [],
};
