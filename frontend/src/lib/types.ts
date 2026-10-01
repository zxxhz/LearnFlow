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
  temperature: number;
}

export interface Preferences {
  daily_new_cards: number;
  chapter_length: number;
  feynman_max_rounds: number;
  auto_create_cards: boolean;
  highlight_colors: Partial<Record<AnnotationColor, string>>;
  github_repo: string;
}

export interface SceneLLMConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export type SceneName = "generation" | "chat" | "feynman";

export interface ScenesConfig {
  generation: SceneLLMConfig;
  chat: SceneLLMConfig;
  feynman: SceneLLMConfig;
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

export interface FeynmanGap {
  desc: string;
  severity: "high" | "medium" | "low";
  section_id: string | null;
}

export interface FeynmanEvaluation {
  score: number;
  strengths: string[];
  gaps: FeynmanGap[];
  advice: string;
}

export type FeynmanStatus = "explaining" | "questioning" | "evaluating" | "done";

export interface FeynmanSession {
  id: string;
  knowledge_point_id: string;
  knowledge_point_title: string | null;
  document_id: string;
  conversation_id: string;
  status: FeynmanStatus;
  round_count: number;
  evaluation: FeynmanEvaluation | null;
  created_at: string;
  updated_at: string;
}

export interface FeynmanSessionDetail extends FeynmanSession {
  messages: Message[];
}

export type ReviewCardState = "new" | "learning" | "review" | "relearning";

export interface ReviewCard {
  id: string;
  source_type: "knowledge_point" | "annotation" | "feynman_gap" | "manual";
  knowledge_point_id: string | null;
  annotation_id: string | null;
  front: string;
  back: string;
  state: ReviewCardState;
  due_at: string;
  interval_days: number;
  easiness_factor: number;
  repetitions: number;
  lapses: number;
  suspended: boolean;
  created_at: string;
  last_reviewed_at: string | null;
}

export interface ReviewQueue {
  cards: ReviewCard[];
  new_quota_remaining: number;
  due_total: number;
}

export interface DayCount {
  date: string;
  count: number;
}

export interface ReviewStats {
  today_reviewed: number;
  due_remaining: number;
  streak_days: number;
  total_cards: number;
  total_reviews: number;
  due_next_7_days: DayCount[];
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
  lapses: number;
  gap_count: number;
}

export interface DashboardSummary {
  courses: DashboardCourse[];
  today: { due_reviews: number; feynman_active: number };
  weak_points: WeakPoint[];
  heatmap: DayCount[];
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
