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

// v0.4.69 发版参数已固化进脚本（AmendWorkflow 走 path 不携带 args，v0.4.63 踩坑教训）
const targetVersion = "0.4.69";
const releaseNotes = `# v0.4.69 吸收 DeepTutor 六大机制

对标 HKUDS/DeepTutor（arXiv:2604.26962）取长补短，全面强化出题可信度、认知画像与资料导入：

## 1. 出题落库前沙箱自验闭环（Critic-Guided 验证）
- 代码关参考实现生成后先在本地沙箱实测：输出与预期一致才入库；
- 输出不符自动按实际运行结果校准（或经 LLM 带报错修正一次）；编译/运行失败修正一次仍不过直接丢弃，绝不让坏题卡死学习者；
- 数学关答案表达式先过 SymPy 安全解析校验；
- 新增 🧪 已实测 / 🧪 输出已校准 徽章；搭桥支线小题同链路自验；生成失败不再误删已有练习与作答。

## 2. 认知画像分学科隔离 + 证据链回溯 + 自动闭环
- 盲区按学科域（💻 编程 / ∑ 数理 / 📖 理论 / 🌐 通用）过滤注入：学高数不再被 C++ 盲区串味；
- 盲区新增证据溯源：设置页点击出处直达原始闯关练习 / 题库题目 / 划线问答；
- 证据闭环：来源题独立做对（未存疑）后对应盲区自动标记已解决；
- 活跃盲区超 25 条自动后台归并同类项（吸收 DeepTutor Memory consolidator）；
- 新增「后台轻模型」场景槽位：画像演进等静默任务可指定便宜快速模型，留空自动回落主配置，省钱不拖慢主对话。

## 3. 讲义修订 → 下游练习一致性提醒
- 单段「质疑有误」手术式替换成功后，自动检测该段挂载的练习并提醒一键按新讲义重新生成本节练习（明示将替换旧练习与作答记录）。

## 4. plot 绘图块一键 AI 自修
- 讲义 / 错题解析 / 全站 Markdown 卡片里的函数图像渲染失败时，一键让 AI 根据报错只修正函数表达式并当场重绘，修正结果先过与普通绘图完全相同的解析校验。

## 5. 轻量 PDF 导入建课（pypdfium2）
- 导入页新增 📑 PDF 入口：有文字层的 PDF 直接抽取全文（零 AI 零消耗）；扫描版/图片型 PDF 自动逐页栅格化走视觉转写（≤16 页/文件，≤5MB/个，最多 3 个），转写稿可手动修正后走既有切章建课全链路。

## 6. 工程与健壮性
- C++ 工具链非 ASCII 路径新增 8.3 短路径兜底（硬链接镜像不可建时的第二道防线）；
- 新增 dev 工具 scripts/eval_tutor_prompts.py：学生模拟器离线评测助教 Prompt（剧透/寒暄/启发性三维回归）；
- 冒烟测试新增 15 项断言（画像隔离/证据闭环/自验/修订联动/task 槽位/绘图自修/PDF 全链路）。`;
const dryRun = false;
const commitMessage = "feat(v0.4.69): 吸收 DeepTutor 六大机制（出题自验/画像分学科/修订联动/绘图自修/后台轻模型/PDF 导入）";

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
const pre = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",["-X", "utf8", "C:/Users/Emoing/Desktop/学习agent/backend/scripts/preflight_release.py", targetVersion], {
  timeoutMs: 180_000,
  output: TAIL,
});
if (pre.exitCode !== 0) {
  throw new Error(`发布预检未通过：\n${pre.stdout || pre.stderr}`);
}
log(`预检通过：v${targetVersion} 可发布`);

phase("同步八处版本号");
const sync = await world.run("C:\\Users\\Emoing\\Desktop\\学习agent\\backend\\.venv\\Scripts\\python.exe",["-X", "utf8", "C:/Users/Emoing/Desktop/学习agent/backend/scripts/sync_versions.py", targetVersion], {
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
  ["-X", "utf8", "C:/Users/Emoing/Desktop/学习agent/backend/scripts/build_latest.py", targetVersion, "--notes", releaseNotes],
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
  "C:/Users/Emoing/Desktop/学习agent/backend/scripts/publish_release.py",
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
const verifyArgs = ["-X", "utf8", "C:/Users/Emoing/Desktop/学习agent/backend/scripts/verify_release.py", targetVersion];
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
