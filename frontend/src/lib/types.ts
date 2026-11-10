// 与后端 app/schemas/* 一一对应的 API 类型契约
export type BlockType =
  | "heading"
  | "paragraph"
  | "code"
  | "list"
  | "table"
  | "quote"
  | "math";

export type AnnotationColor = "yellow" | "green" | "blue" | "pink";

export interface OutlineItem {
  index: number;
  title: string;
  points: string[];
}

export type CourseStatus = "draft" | "generating" | "ready" | "archived";
export type DocStatus = "pending" | "generating" | "done" | "failed";

export interface Course {
  id: string;
  title: string;
  topic: string;
  level: string | null;
  scope: string | null;
  outline: OutlineItem[];
  status: CourseStatus;
  discipline?: "coding" | "math" | "theory";
  course_settings: { auto_create_cards?: boolean } | null;
  created_at: string;
  updated_at: string;
}

export interface ChapterProgress {
  document_id: string;
  chapter_index: number;
  title: string;
  status: DocStatus;
  version: number;
  error: string | null;
  source: "generated" | "imported";
}

export interface CompareHighlightItem {
  section_id: string;
  exact: string;
  prefix: string;
  suffix: string;
  start_offset: number;
  end_offset: number;
  note: string;
  color: AnnotationColor;
  is_matched: boolean;
}

export interface HighlightComparisonOut {
  user_highlight_count: number;
  ai_candidate_count: number;
  matched_count: number;
  missed_count: number;
  summary: string;
  candidates: CompareHighlightItem[];
}

export interface SectionReviseRequest {
  instruction: string;
  apply?: boolean;
  revised_markdown?: string | null;
}

export interface SectionPracticeImpact {
  kp_id: string;
  kp_title: string;
  exercise_count: number;
  language: string;
}

export interface SectionReviseResponse {
  section_id: string;
  original_markdown: string;
  verification_status: "confirmed_error" | "improved" | "verified_correct" | string;
  explanation: string;
  revised_markdown: string;
  applied: boolean;
  updated_full_markdown?: string | null;
  /** apply 成功后返回：该段落挂载的知识点及其练习数量（空 = 无下游练习） */
  affected_practice?: SectionPracticeImpact[];
}

export interface CourseDetail extends Course {
  documents: ChapterProgress[];
}

export interface CourseListItem extends Course {
  done_chapters: number;
  total_chapters: number;
  first_document_id?: string | null;
}

export interface DocumentMeta {
  id: string;
  course_id: string;
  chapter_index: number;
  title: string;
  version: number;
  status: DocStatus;
  source: "generated" | "imported";
  summary: string | null;
  updated_at: string;
}

export interface SectionBlock {
  id: string;
  order_index: number;
  block_type: BlockType;
  heading_path: string[];
}

export interface DocumentContent {
  document: DocumentMeta;
  markdown: string;
  blocks: SectionBlock[];
}

export interface Anchor {
  section_id: string;
  exact: string;
  prefix: string;
  suffix: string;
  start_offset: number;
  end_offset: number;
}

export interface Annotation extends Anchor {
  id: string;
  document_id: string;
  version: number;
  color: AnnotationColor;
  note: string | null;
  status: "active" | "orphan";
  created_at: string;
  updated_at: string;
}

export interface AnnotationCreated {
  annotation: Annotation;
  conversation_id: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface LLMConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export type AdhdMode = "off" | "a" | "b";

export interface Preferences {
  chapter_length: number;
  exercises_per_kp: number;
  highlight_colors: Partial<Record<AnnotationColor, string>>;
  auto_highlight?: boolean;
  adhd_mode?: AdhdMode;
  course_font_size?: number;
  drill_font_size?: number;
}


export interface SceneLLMConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export type SceneName = "generation" | "chat" | "task";

export interface ScenesConfig {
  generation: SceneLLMConfig;
  chat: SceneLLMConfig;
  task: SceneLLMConfig;
}

export interface SettingsData {
  llm: LLMConfig;
  scenes: ScenesConfig;
  preferences: Preferences;
}

export interface LLMTestResult {
  ok: boolean;
  model_reply: string | null;
  latency_ms: number | null;
  error: string | null;
}

export interface KnowledgePoint {
  id: string;
  document_id: string;
  title: string;
  summary: string;
  section_ids: string[];
  tags: string[];
  created_at: string;
}

export type ExerciseKind = "code" | "concept" | "choice" | "fill" | "math";

export interface ExerciseAttempt {
  id: string;
  exercise_id: string;
  content: string;
  status: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number | null;
  passed: boolean | null;
  is_doubtful?: boolean;
  feedback: string;
  created_at: string;
}

export interface Exercise {
  id: string;
  knowledge_point_id: string;
  document_id: string;
  kind: ExerciseKind;
  title: string;
  task_md: string;
  language: string;
  skeleton_code: string;
  expected_output: string;
  reference_answer: string;
  reference_code: string;
  options: string;
  answer: string;
  quiz_id: string;
  order_index: number;
  hints: string[];
  is_hard_bone?: boolean;
  parent_exercise_id?: string;
  /** 落库前沙箱自验结果：0 存量未验 / 1 已实测 / 2 输出已校准 */
  self_verified?: number;
  created_at: string;
  /** 闯关：同一知识点内前一关通过后才可作答（小测题/非代码题恒为 true） */
  unlocked: boolean;
  /** 闯关：曾通过过（任一次作答 passed） */
  ever_passed: boolean;
  kp_title: string | null;
  latest_attempt: ExerciseAttempt | null;
}

export interface Quiz {
  id: string;
  document_id: string;
  course_id: string;
  title: string;
  kp_ids: string[];
  created_at: string;
  items: Exercise[];
  total: number;
  correct: number;
}

export interface DayCount {
  date: string;
  count: number;
}

export interface DashboardCourse {
  id: string;
  title: string;
  status: CourseStatus;
  done_chapters: number;
  total_chapters: number;
  updated_at: string;
}

export interface WeakPoint {
  knowledge_point_id: string;
  title: string;
  document_id: string;
  exercise_fail: number;
  mastery: number;
}

export interface StudyDayOut {
  date: string;
  minutes: number;
}

export interface SceneUsage {
  scene: string;
  calls: number;
  tokens: number;
}

export interface LLMUsageSummary {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  by_scene: SceneUsage[];
}

export interface DashboardSummary {
  courses: DashboardCourse[];
  weak_points: WeakPoint[];
  heatmap: DayCount[];
  study_days: StudyDayOut[];
  study_minutes_7d: number;
  llm_usage: LLMUsageSummary | null;
}

export interface SearchHit {
  course_id: string;
  course_title: string;
  document_id: string;
  document_title: string;
  section_id: string;
  heading: string;
  snippet: string;
}

export interface BackupItem {
  name: string;
  size: number;
  mtime: number;
}

export interface AccessInfo {
  host: string;
  port: number;
  lan_mode: boolean;
  lan_enabled?: boolean;
  lan_urls: string[];
  token: string;
  lan_urls_with_token: string[];
}

export type ExecStatus =
  | "success"
  | "runtime_error"
  | "timeout"
  | "compile_error"
  | "compiler_missing"
  | "error";

export interface CodeExecution {
  id: string;
  document_id: string;
  section_id: string;
  document_version: number;
  language: string;
  code: string;
  status: ExecStatus;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number | null;
  created_at: string;
}

// ===== Markdown 导入 =====
export interface ImportChapter {
  file_index: number;
  title: string;
  start_line: number;
  end_line: number;
  points: string[];
}

export interface ImportAnalysis {
  title: string;
  title_from_llm: boolean;
  llm_available: boolean;
  files: { name: string }[];
  chapters: ImportChapter[];
}

export interface ImportSpec {
  title: string;
  chapters: { file_index: number; title: string; start_line: number; end_line: number }[];
}

export interface UpdateCheckResult {
  has_update: boolean;
  current: string;
  latest?: string;
  url?: string;
  accelerated_url?: string;
  active_mirror?: string;
  notes?: string;
  repo?: string;
  error?: string;
}

export interface DownloadMirrorItem {
  id: string;
  name: string;
  prefix: string;
  desc: string;
  is_custom?: boolean;
  ok: boolean | null;
  latency_ms: number | null;
  error: string | null;
}

export interface MirrorsStatus {
  tested_at: number;
  mode: "auto" | "manual";
  selected_id: string;
  fastest_id: string;
  active_mirror: {
    id: string;
    name: string;
    prefix: string;
    desc: string;
  };
  results: DownloadMirrorItem[];
}

// ===== 运行环境（代码沙箱工具链检测与便携安装） =====
export type RuntimeSource = "bundled" | "managed" | "system" | "none";
export type RuntimeComponentName = "python" | "cpp";

export interface RuntimeComponentInfo {
  installed: boolean;
  source: RuntimeSource;
  path: string;
  version: string;
}

export interface RuntimeStatus {
  python: RuntimeComponentInfo;
  cpp: RuntimeComponentInfo;
  platform: string;
  installable: boolean;
  toolchains_dir: string;
}

export type InstallPhase = "idle" | "downloading" | "extracting" | "done" | "error";

export interface InstallState {
  state: InstallPhase;
  percent: number;
  message: string;
  error: string | null;
  log: string[];
}

export interface InstallStatus {
  components: Record<RuntimeComponentName, InstallState>;
  active: RuntimeComponentName | null;
}

// ===== SSE 事件负载 =====
export interface ChatSSEEvent {
  type: "user_ack" | "delta" | "done" | "error";
  text?: string;
  message_id?: string;
  detail?: string;
  content?: string;              // done 事件携带完整回复
  message?: { id: string };      // user_ack 事件回传已持久化的用户消息（乐观气泡对齐 ID）
  suggest_evaluate?: boolean;
}

/** 助教伴学诊断 SSE：含工具调用事件（tool_result.result 可能携带 render_math_plot 的 svg） */
export interface TutorSSEEvent {
  type: "tool_call" | "tool_result" | "delta" | "done" | "error";
  name?: string;
  args?: Record<string, unknown>;
  result?: { svg?: string; [key: string]: unknown };
  text?: string;
  detail?: string;
}

/** 拍照解题 SSE 事件（/solve/photo） */
export interface SolveSSEEvent {
  type: "delta" | "done" | "error";
  text?: string;
  detail?: string;
}

export interface ProgressSSEEvent {
  type:
    | "snapshot"
    | "chapter_start"
    | "chapter_done"
    | "chapter_failed"
    | "course_done"
    | "error";
  index?: number;
  title?: string;
  document_id?: string;
  error?: string;
  status?: string;
  documents?: {
    document_id: string;
    chapter_index: number;
    title: string;
    status: string;
    version: number;
    source?: string;
  }[];
}

/** 题库 AI 错题深度解析 SSE（/banks/questions/:id/ai-explain） */
export interface BankExplainSSEEvent {
  type: "delta" | "done" | "error";
  text?: string;
  detail?: string;
}

/** 应用内更新安装 SSE（/update/in-app-install）：下载进度 → 就绪 → 静默安装 */
export interface InAppInstallSSEEvent {
  type: "start" | "progress" | "retry" | "ready" | "installing" | "error";
  downloaded?: number;
  total?: number;
  percent?: number;
  speed_mb?: number;
  message?: string;
  detail?: string;
}

// ===== 题库刷题（独立模块） =====

export type BankQuestionType = "single" | "multi" | "judge";

export interface BankQuestion {
  id: string;
  seq: number;
  qtype: BankQuestionType;
  title: string;
  /** 按列位的选项数组（含空串），字母 = A + 下标；判断题为 [] */
  options: string[];
  difficulty: string;
  ai_explanation?: string;
}

export interface BankWrongQuestion extends BankQuestion {
  answer: string;
  answer_raw: string;
  explanation: string;
}

export interface BankAttemptResult {
  attempt_id: string;
  passed: boolean;
  is_doubtful?: boolean;
  user_answer?: string;
  answer: string;
  correct_answer: string;
  answer_raw: string;
  explanation: string;
  ai_explanation?: string;
}

export interface BankStats {
  question_count: number;
  answered: number;
  new_count?: number;
  attempts: number;
  correct: number;
  accuracy: number;
  wrong_count: number;
  by_type: Record<string, { total: number; wrong: number }>;
}

export interface Bank {
  id: string;
  name: string;
  source_file: string;
  question_count: number;
  ai_prompt: string;
  created_at: string;
  stats: BankStats;
}

export interface BankAnalysis {
  name: string;
  source_file: string;
  question_count: number;
  skipped_total: number;
  skipped: { row: number; reason: string }[];
  by_type: Record<string, number>;
  by_difficulty: Record<string, number>;
  samples: BankQuestion[];
}

export interface BankRound {
  bank_id: string;
  mode: "new" | "all" | "random" | "wrong";
  questions: BankQuestion[];
  wrong_pool_size: number;
}

export interface ParsedTextQuestionItem {
  qtype: "single" | "multi" | "judge";
  title: string;
  options: string[];
  answer: string;
  difficulty: string;
  explanation: string;
}

export interface BankQuestionUpdateIn {
  title?: string;
  options?: string[];
  answer?: string;
  explanation?: string;
  difficulty?: string;
  recalibrate_attempts?: boolean;
}

export interface BankQuestionUpdateOut {
  ok: boolean;
  question: BankWrongQuestion;
  recalibrated_result?: BankAttemptResult | null;
}

export interface BankReplaceSampleItem {
  title: string;
  qtype: string;
  old_answer?: string | null;
  new_answer?: string | null;
  user_answer?: string | null;
  recalibrated_passed?: boolean | null;
}

export interface BankReplaceAnalyzeOut {
  bank_id: string;
  bank_name: string;
  new_source_file: string;
  current_total: number;
  new_total: number;
  matched_count: number;
  answered_retained: number;
  unanswered_retained: number;
  recalibrated_count: number;
  removed_count: number;
  added_count: number;
  skipped_total: number;
  samples_recalibrated: BankReplaceSampleItem[];
  samples_removed: string[];
  samples_added: string[];
}

export interface PasteParseResponse {
  bank_title: string;
  questions: ParsedTextQuestionItem[];
}

// ===== 学习者画像与认知特征 =====
export interface LearnerMisconception {
  id: string;
  topic: string;
  tag?: string | null;
  evidence?: string | null;
  status: string;
  created_at?: string;
  scope?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  source_label?: string | null;
  source_href?: string | null;
}

export interface LearnerProfile {
  id: string;
  background_summary: string;
  socratic_mode: boolean;
  misconceptions: LearnerMisconception[];
}

export interface LearnerProfileUpdate {
  background_summary?: string;
  socratic_mode?: boolean;
}

export interface LastReadChapter {
  course_id: string;
  course_title: string;
  document_id: string;
  chapter_index: number;
  chapter_title: string;
}

export interface HardBoneItem {
  id: string;
  title: string;
  document_id: string;
  kind: string;
}

export interface ActiveMisconceptionItem {
  id: string;
  topic: string;
  tag?: string | null;
}

export interface TodayStudyHubOut {
  last_read?: LastReadChapter | null;
  hard_bones: HardBoneItem[];
  active_misconceptions: ActiveMisconceptionItem[];
  bank_wrong_count: number;
  today_read_seconds: number;
}

// ===== 思维导图 (Mind Map 独立模块) =====
export interface MindMapNode {
  id: string;
  title: string;
  summary?: string;
  detail?: string;
  children?: MindMapNode[];
  collapsed?: boolean;
}

export interface MindMapSummary {
  id: string;
  title: string;
  topic: string;
  node_count: number;
  source?: "manual" | "import" | "generate" | "course";
  course_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MindMapCrossLink {
  id: string;
  sourceId: string;
  targetId: string;
  label: string;
}

export interface MindMapDetail {
  id: string;
  title: string;
  topic: string;
  root: MindMapNode;
  settings: {
    layout?: "lr" | "radial";
    zoom?: number;
    cross_links?: MindMapCrossLink[];
    [key: string]: any;
  };
  source?: "manual" | "import" | "generate" | "course";
  course_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MindMapCreateInput {
  title?: string;
  topic?: string;
  root?: MindMapNode | Record<string, any>;
  settings?: Record<string, any>;
}

export interface MindMapUpdateInput {
  title?: string;
  topic?: string;
  root?: MindMapNode | Record<string, any>;
  settings?: Record<string, any>;
}

export interface MindMapGenerateInput {
  prompt?: string;
  depth?: number;
  import_content?: string;
  course_id?: string;
  include_details?: boolean;
}

export interface MindMapImportInput {
  title?: string;
  content: string;
  format?: "auto" | "markdown" | "json";
}

export interface MindMapAgentChatInput {
  message: string;
  selected_node_id?: string | null;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface MindMapAgentSSEEvent {
  type: "tool_call" | "tool_result" | "tree_update" | "delta" | "done" | "error";
  name?: string;
  args?: any;
  text?: string;
  tree?: MindMapNode;
  detail?: string;
}

export interface MindMapNodeDetailSSEEvent {
  type: "delta" | "done" | "error";
  text?: string;
  detail?: string;
  node_id?: string;
}

export interface MindMapNodeQASSEEvent {
  type: "delta" | "done" | "error";
  text?: string;
}

// ===== 云端自建中转 (Cloud Relay) =====

export type RelayConnectionState = "connected" | "connecting" | "disconnected" | "error";

export type RelayAiMode = "cloud" | "local" | "auto";

export interface RelayConfig {
  enabled: boolean;
  server_url: string;
  token?: string;
  auto_sync?: boolean;
  ai_mode?: RelayAiMode;
  effective_ai_mode?: "cloud" | "local";
  status?: RelayConnectionState;
  last_sync_at?: string | null;
  last_error?: string | null;
  latency_ms?: number | null;
}

export interface RelayStatus {
  enabled: boolean;
  status: RelayConnectionState;
  server_url?: string;
  connected?: boolean;
  ai_mode?: RelayAiMode;
  effective_ai_mode?: "cloud" | "local";
  last_sync_at?: string | null;
  last_error?: string | null;
  latency_ms?: number | null;
  message?: string;
}

export interface RelayTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number;
}

export interface RelaySyncResult {
  ok: boolean;
  message: string;
  synced_at?: string;
  pulled_count?: number;
  pushed_count?: number;
  details?: Record<string, any>;
  action?: "pull" | "push" | "both";
}

export interface RelayAiModeResult {
  ok: boolean;
  ai_mode: RelayAiMode;
  effective_ai_mode?: "cloud" | "local";
  message?: string;
}

export interface ServerSystemVersion {
  current_version: string;
  latest_version: string;
  has_update: boolean;
  release_title?: string;
  release_notes?: string;
  published_at?: string;
  html_url?: string;
  in_container: boolean;
  can_auto_update: boolean;
  update_driver: "watchtower" | "docker_socket" | "command" | "manual";
  check_error?: string | null;
}

export interface ServerUpdateTriggerResult {
  status: string;
  message: string;
  driver: string;
  estimated_seconds: number;
}

export interface ServerLLMConfig {
  ai_mode: RelayAiMode;
  server_llm_configured: boolean;
  server_llm_model: string;
  server_llm_base_url: string;
  server_llm_api_key_masked?: string;
  worker_online?: boolean;
}

export interface ServerLLMTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number;
  model_reply?: string;
}


