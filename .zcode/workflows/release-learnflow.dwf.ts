/* zcode-workflow
description: LearnFlow 自动化发版工作流（全确定性）：预检、八处版本同步、类型/烟雾门禁、双端构建、latest.json、
  GitHub 发布与发布后核验——全部由 world.run 门禁脚本完成，零子代理消耗
whenToUse: 当需要发布 LearnFlow 新版本时使用，一键完成发布预检、8 处版本同步、质量门禁、双端构建、Tauri 签名、
  latest.json 生成、GitHub Release 发布与发布后确定性核验
args:
  version:
    type: string
    description: 目标版本号，如 0.4.67
    required: true
  notes:
    type: string
    description: 版本更新日志 Markdown 内容
    required: true
  dryRun:
    type: boolean
    description: 是否只做预检、同步、门禁、构建与本地元数据，不推送（试跑模式）
    default: false
  commitMessage:
    type: string
    description: "发布提交信息，缺省为 chore(release): vX.Y.Z"
    required: false
*/

const targetVersion = String(args.version ?? "").trim();
const releaseNotes = String(args.notes ?? "").trim();
const dryRun = Boolean(args.dryRun ?? false);
const commitMessage = String(args.commitMessage ?? "").trim() || `chore(release): v${targetVersion}`;

if (!targetVersion) {
  throw new Error("缺少必填参数 version，例如 0.4.67");
}
if (!releaseNotes) {
  throw new Error("缺少必填参数 notes（版本更新日志 Markdown）");
}

// 仓库根 = 会话工作目录；脚本经 venv python 直跑（不经 cmd），含换行的 notes 可安全走 argv
const TAIL = { tail: 16384 };

log(`开始执行 LearnFlow 发版工作流，目标版本：v${targetVersion}，dryRun: ${dryRun}`);

phase("发布预检：版本格式、标签冲突与工作树");
const pre = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",["-X", "utf8", "backend/scripts/preflight_release.py", targetVersion], {
  timeoutMs: 120_000,
  output: TAIL,
});
if (pre.exitCode !== 0) {
  throw new Error(`发布预检未通过：\n${pre.stdout || pre.stderr}`);
}
log(`预检通过：v${targetVersion} 可发布`);

phase("同步八处版本号");
const sync = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",["-X", "utf8", "backend/scripts/sync_versions.py", targetVersion], {
  timeoutMs: 60_000,
  output: TAIL,
});
if (sync.exitCode !== 0) {
  throw new Error(`版本号同步失败：\n${sync.stdout || sync.stderr}`);
}
log("八处版本号已同步（APP_VERSION/pyproject/两个 package.json/tauri.conf/Cargo.toml/sw.js/Cargo.lock）");

phase("质量门禁：前端类型检查与全量烟雾测试");
const tscCheck = await world.run(
  "cmd.exe",
  ["/c", "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\frontend && npx tsc --noEmit"],
  { timeoutMs: 120_000, output: TAIL }
);
if (tscCheck.exitCode !== 0) {
  throw new Error(`前端 TypeScript 类型检查失败：\n${tscCheck.stderr || tscCheck.stdout}`);
}
log("前端类型检查通过");

const smokeCheck = await world.run(
  "cmd.exe",
  ["/c", "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\backend && uv run python scripts/smoke_test.py"],
  { timeoutMs: 420_000, output: TAIL }
);
if (smokeCheck.exitCode !== 0) {
  throw new Error(`烟雾测试回归失败：\n${smokeCheck.stderr || smokeCheck.stdout}`);
}
log("后端全量烟雾测试回归通过");

phase("双端构建：前端产物、PyInstaller 后端与 Tauri 签名安装包");
const feBuild = await world.run(
  "cmd.exe",
  ["/c", "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\frontend && npm run build"],
  { timeoutMs: 300_000, output: TAIL }
);
if (feBuild.exitCode !== 0) {
  throw new Error(`前端生产构建失败：\n${feBuild.stderr || feBuild.stdout}`);
}
log("前端生产产物构建完成");

const beBuild = await world.run(
  "cmd.exe",
  ["/c", "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\backend && uv run python scripts/build_backend.py"],
  { timeoutMs: 600_000, output: TAIL }
);
if (beBuild.exitCode !== 0) {
  throw new Error(`PyInstaller 后端打包失败：\n${beBuild.stderr || beBuild.stdout}`);
}
log("PyInstaller 后端打包完成");

// set 值与 && 之间不留空格（cmd 会把尾随空格算进值内）；路径无空格可不加引号
const tauriBuild = await world.run(
  "cmd.exe",
  [
    "/c",
    "cd /d C:\\Users\\Emoing\\Desktop\\学习agent\\desktop && set TAURI_SIGNING_PRIVATE_KEY=C:\\Users\\Emoing\\Desktop\\学习agent\\desktop\\src-tauri\\keys\\learnflow.key&& set TAURI_SIGNING_PRIVATE_KEY_PASSWORD=&& npx tauri build",
  ],
  { timeoutMs: 900_000, output: TAIL }
);
if (tauriBuild.exitCode !== 0) {
  throw new Error(`Tauri NSIS 构建失败：\n${tauriBuild.stderr || tauriBuild.stdout}`);
}
log(`Tauri NSIS 安装包与 minisign 签名完成：LearnFlow_${targetVersion}_x64-setup.exe`);

phase("生成更新元数据 latest.json");
const latest = await world.run(
  "C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",
  ["-X", "utf8", "backend/scripts/build_latest.py", targetVersion, "--notes", releaseNotes],
  { timeoutMs: 120_000, output: TAIL }
);
if (latest.exitCode !== 0) {
  throw new Error(`latest.json 生成失败：\n${latest.stdout || latest.stderr}`);
}
const shaMatch = /SHA256=([a-f0-9]{64})/.exec(latest.stdout);
const notesLenMatch = /NOTES_LEN=(\d+)/.exec(latest.stdout);
const exeSha256 = shaMatch?.[1] ?? "";
const notesLen = notesLenMatch ? Number(notesLenMatch[1]) : 0;
if (!exeSha256 || notesLen < 30) {
  throw new Error(`latest.json 元数据解析异常：SHA256=${exeSha256} NOTES_LEN=${notesLen}`);
}
log(`latest.json 生成完毕，安装包 SHA-256: ${exeSha256}，notes ${notesLen} 字符`);

phase("发布到 GitHub：提交、打标、推送与资产上传");
// 发布脚本内部按 --dry-run 分流：dryRun 只做凭据/资产/连通性检查，不写 git、不调 API
const publishArgs = [
  "-X",
  "utf8",
  "backend/scripts/publish_release.py",
  targetVersion,
  "--notes",
  releaseNotes,
  "--commit-msg",
  commitMessage,
];
if (dryRun) publishArgs.push("--dry-run");
const publish = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",publishArgs, { timeoutMs: 900_000, output: TAIL });
if (publish.exitCode !== 0) {
  throw new Error(`发布失败：\n${publish.stdout || publish.stderr}`);
}
const urlMatch = /RELEASE_URL=(\S+)/.exec(publish.stdout);
const releaseUrl = urlMatch?.[1] ?? (dryRun ? "dry-run://local" : "");
log(dryRun ? "dryRun 发布检查通过（未推送）" : `GitHub Release 已发布：${releaseUrl}`);

phase("发布后确定性核验");
const verifyArgs = ["-X", "utf8", "backend/scripts/verify_release.py", targetVersion];
if (dryRun) verifyArgs.push("--local");
const verify = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",verifyArgs, { timeoutMs: 600_000, output: TAIL });
if (verify.exitCode !== 0) {
  throw new Error(`发布核验未通过：\n${verify.stdout || verify.stderr}`);
}
const passCount = /全部通过（(\d+) 项）/.exec(verify.stdout)?.[1] ?? "0";
log(`发布核验 ${passCount} 项全部通过`);

await artifact.markdown(
  "release-report",
  `# LearnFlow v${targetVersion} 发布报告\n\n- **状态**：${dryRun ? "dry_run（未推送）" : "published"}\n${
    releaseUrl ? `- **发布地址**：[GitHub Release](${releaseUrl})\n` : ""
  }- **发布资产**：\n  - \`LearnFlow_${targetVersion}_x64-setup.exe\` (SHA-256: \`${exeSha256}\`)\n  - \`latest.json\`（notes ${notesLen} 字符）\n\n## 更新日志\n\n${releaseNotes}\n\n## 确定性核验\n\n\`\`\`\n${verify.stdout.trim()}\n\`\`\`\n`,
  {
    title: `LearnFlow v${targetVersion} 发版报告`,
    description: dryRun
      ? "dryRun 模式：本地构建与校验全部成功，未推送 GitHub"
      : "版本自动化构建、签名、发布与发布后确定性核验结果",
    primary: true,
  }
);

return {
  conclusion: dryRun
    ? `LearnFlow v${targetVersion} dryRun 试跑完成：预检、版本同步、门禁、双端构建、本地元数据与本地核验全部通过，未推送 GitHub。`
    : `LearnFlow v${targetVersion} 发版完成并经 ${passCount} 项确定性核验全部通过，发布地址：${releaseUrl}。`,
  findings: [],
  verified: [
    "preflight_release.py：版本格式/标签冲突/工作树清洁检查",
    "sync_versions.py：八处版本号替换并字节级回读断言",
    "cmd: npx tsc --noEmit 前端类型检查",
    "cmd: uv run python scripts/smoke_test.py 后端全量烟雾测试",
    "cmd: npm run build / build_backend.py / npx tauri build 双端构建与 minisign 签名",
    "build_latest.py：安装包 SHA-256 与 latest.json（notes ≥30 字符）",
    dryRun
      ? "publish_release.py --dry-run：PAT/资产/API 连通性检查"
      : "publish_release.py：git 提交/打标/推送 + GitHub Release 创建与资产上传",
    `verify_release.py${dryRun ? " --local" : ""}：${passCount} 项发布核验全部通过`,
  ],
  notCovered: dryRun ? ["跳过 git 提交/推送、GitHub Release 创建与远程资产上传（dryRun 模式）"] : [],
};
