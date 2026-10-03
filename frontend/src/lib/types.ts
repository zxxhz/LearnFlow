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

export interface CourseDetail extends Course {
  documents: ChapterProgress[];
}

export interface CourseListItem extends Course {
  done_chapters: number;
  total_chapters: number;
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

export interface Preferences {
  chapter_length: number;
  exercises_per_kp: number;
  highlight_colors: Partial<Record<AnnotationColor, string>>;
}

export interface SceneLLMConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export type SceneName = "generation" | "chat";

export interface ScenesConfig {
  generation: SceneLLMConfig;
  chat: SceneLLMConfig;
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

export type ExerciseKind = "code" | "concept" | "choice" | "fill";

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
  notes?: string;
  repo?: string;
  error?: string;
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
  type: "delta" | "done" | "error";
  text?: string;
  message_id?: string;
  detail?: string;
  suggest_evaluate?: boolean;
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
}

export interface BankWrongQuestion extends BankQuestion {
  answer: string;
  answer_raw: string;
  explanation: string;
}

export interface BankAttemptResult {
  attempt_id: string;
  passed: boolean;
  answer: string;
  correct_answer: string;
  answer_raw: string;
  explanation: string;
}

export interface BankStats {
  question_count: number;
  answered: number;
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
  mode: "random" | "wrong";
  questions: BankQuestion[];
  wrong_pool_size: number;
}
