// 统一 API 客户端：错误统一抛 Error(detail 中文消息)
import type {
  Anchor,
  Annotation,
  AnnotationColor,
  AnnotationCreated,
  CodeExecution,
  Course,
  CourseDetail,
  CourseListItem,
  DashboardSummary,
  DocumentContent,
  Exercise,
  ExerciseAttempt,
  ImportAnalysis,
  ImportSpec,
  KnowledgePoint,
  LLMConfig,
  LLMTestResult,
  Message,
  OutlineItem,
  Preferences,
  SceneLLMConfig,
  SceneName,
  SettingsData,
  InstallStatus,
  RuntimeComponentName,
  RuntimeStatus,
  UpdateCheckResult,
  BackupItem,
  AccessInfo,
  Quiz,
  SearchHit,
  Bank,
  BankAnalysis,
  BankAttemptResult,
  BankRound,
  BankStats,
  BankWrongQuestion,
} from "./types";
import { streamSSE } from "./sse";

const BASE = "/api";

export function getAccessToken(): string {
  if (typeof window === "undefined") return "";
  try {
    const fromStorage = localStorage.getItem("lf_access_token");
    if (fromStorage) return fromStorage;
    const params = new URLSearchParams(window.location.search);
    return params.get("token") || "";
  } catch {
    return "";
  }
}

/** 触发浏览器下载后端导出的文件（Content-Disposition 命名）。 */
export async function downloadFile(path: string): Promise<void> {
  const token = getAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["x-access-token"] = token;
  const res = await fetch(BASE + path, { headers });
  if (!res.ok) {
    let detail = `下载失败（HTTP ${res.status}）`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : detail;
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  const dispo = res.headers.get("content-disposition") || "";
  const m = dispo.match(/filename\*=UTF-8''([^;]+)/);
  const name = m ? decodeURIComponent(m[1]) : "export";
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  const token = getAccessToken();
  const baseHeaders: Record<string, string> = {};
  if (!isForm) {
    baseHeaders["Content-Type"] = "application/json";
  }
  if (token) {
    baseHeaders["x-access-token"] = token;
  }
  const res = await fetch(BASE + path, {
    ...opts,
    headers: { ...baseHeaders, ...opts.headers },
  });
  if (!res.ok) {
    let detail = `请求失败（HTTP ${res.status}）`;
    try {
      const j = await res.json();
      if (j?.detail) {
        detail =
          typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function jsonBody(body: unknown): RequestInit {
  return { body: JSON.stringify(body) };
}

export const api = {
  settings: {
    get: () => request<SettingsData>("/settings"),
    update: (body: {
      llm?: Partial<LLMConfig>;
      scenes?: Partial<Record<SceneName, Partial<SceneLLMConfig>>>;
      preferences?: Partial<Preferences>;
    }) => request<SettingsData>("/settings", { method: "PUT", ...jsonBody(body) }),
    testLlm: () => request<LLMTestResult>("/settings/llm/test", { method: "POST" }),
    openDataDir: () =>
      request<{ ok: boolean }>("/settings/open-data-dir", { method: "POST" }),
    ollamaModels: () => request<{ models: string[] }>("/settings/llm/ollama/models"),
  },
  math: {
    render: (body: { expressions: string; x_min?: number; x_max?: number }) =>
      request<{ svg: string }>("/math/render", { method: "POST", ...jsonBody(body) }),
  },
  update: {
    version: () => request<{ version: string }>("/version"),
    check: (force = false) =>
      request<UpdateCheckResult>(`/update/check${force ? "?force=1" : ""}`, {
        method: "POST",
      }),
  },
  runtime: {
    status: () => request<RuntimeStatus>("/runtime/status"),
    installStatus: () => request<InstallStatus>("/runtime/install/status"),
    install: (component: RuntimeComponentName) =>
      request<InstallStatus>("/runtime/install", {
        method: "POST",
        ...jsonBody({ component }),
      }),
  },
  courses: {
    create: (body: {
      topic: string;
      level?: string | null;
      scope?: string | null;
      chapter_count?: number | null;
    }) => request<{ course: Course; outline: OutlineItem[] }>("/courses", {
      method: "POST",
      ...jsonBody(body),
    }),
    saveOutline: (id: string, outline: OutlineItem[]) =>
      request<Course>(`/courses/${id}/outline`, {
        method: "PUT",
        ...jsonBody({ outline }),
      }),
    rename: (id: string, title: string) =>
      request<Course>(`/courses/${id}`, {
        method: "PATCH",
        ...jsonBody({ title }),
      }),
    generate: (id: string, options?: { auto_highlight?: boolean }) =>
      request<Course>(`/courses/${id}/generate`, {
        method: "POST",
        ...(options ? jsonBody(options) : {}),
      }),
    list: () => request<CourseListItem[]>("/courses"),
    get: (id: string) => request<CourseDetail>(`/courses/${id}`),
    exportMd: (id: string) => downloadFile(`/courses/${id}/export.md`),
    exportHtml: (id: string) => downloadFile(`/courses/${id}/export.html`),
    ask: (id: string, question: string, onDelta: (text: string) => void, onDone: (err?: string) => void) => {
      const ctrl = new AbortController();
      fetch(`${BASE}/courses/${id}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: ctrl.signal,
      })
        .then(async (res) => {
          if (!res.ok || !res.body) {
            let detail = `请求失败（HTTP ${res.status}）`;
            try {
              const j = await res.json();
              if (j?.detail) detail = j.detail;
            } catch {
              /* ignore */
            }
            onDone(detail);
            return;
          }
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buf = "";
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split("\n\n");
            buf = parts.pop() ?? "";
            for (const p of parts) {
              const line = p.trim();
              if (!line.startsWith("data: ")) continue;
              try {
                const ev = JSON.parse(line.slice(6));
                if (ev.type === "delta") onDelta(ev.text);
                else if (ev.type === "error") onDone(ev.detail);
                else if (ev.type === "done") onDone();
              } catch {
                /* 忽略坏帧 */
              }
            }
          }
          onDone();
        })
        .catch((e) => {
          if ((e as Error).name !== "AbortError") onDone((e as Error).message);
        });
      return () => ctrl.abort();
    },
    update: (id: string, body: { auto_create_cards?: boolean }) =>
      request<Course>(`/courses/${id}`, { method: "PATCH", ...jsonBody(body) }),
    importAnalyze: (files: File[]) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      return request<ImportAnalysis>("/courses/import/analyze", {
        method: "POST",
        body: fd,
      });
    },
    importConfirm: (files: File[], spec: ImportSpec) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("spec", JSON.stringify(spec));
      return request<Course>("/courses/import", { method: "POST", body: fd });
    },
    delete: (id: string) =>
      request<void>(`/courses/${id}`, { method: "DELETE" }),
  },
  documents: {
    getContent: (id: string) =>
      request<DocumentContent>(`/documents/${id}/content`),
    regenerate: (id: string, instruction?: string, auto_highlight?: boolean) =>
      request<{ ok: boolean }>(`/documents/${id}/regenerate`, {
        method: "POST",
        ...jsonBody({
          instruction: instruction ?? null,
          ...(auto_highlight !== undefined ? { auto_highlight } : {}),
        }),
      }),
    executions: (id: string) =>
      request<CodeExecution[]>(`/documents/${id}/executions`),
  },
  executions: {
    run: (body: { document_id: string; section_id: string; language: string; code: string }) =>
      request<CodeExecution>("/executions", { method: "POST", ...jsonBody(body) }),
  },
  exercises: {
    generate: (body: { knowledge_point_id: string; language: string; count?: number }) =>
      request<Exercise[]>("/exercises/generate", { method: "POST", ...jsonBody(body) }),
    list: (documentId: string) =>
      request<Exercise[]>(`/exercises?document_id=${documentId}`),
    wrongbook: () => request<Exercise[]>("/exercises/wrongbook"),
    submit: (id: string, content: string) =>
      request<ExerciseAttempt>(`/exercises/${id}/submit`, {
        method: "POST",
        ...jsonBody({ content }),
      }),
    remove: (id: string) => request<{ ok: boolean }>(`/exercises/${id}`, { method: "DELETE" }),
  },
  quizzes: {
    generate: (body: { document_id: string; kp_ids: string[]; language: string; per_kp?: number }) =>
      request<Quiz>("/quizzes/generate", { method: "POST", ...jsonBody(body) }),
    list: (documentId: string) => request<Quiz[]>(`/quizzes?document_id=${documentId}`),
    remove: (id: string) => request<{ ok: boolean }>(`/quizzes/${id}`, { method: "DELETE" }),
  },
  search: (q: string) => request<{ query: string; results: SearchHit[] }>(`/search?q=${encodeURIComponent(q)}`),
  banks: {
    analyze: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<BankAnalysis>("/banks/import/analyze", { method: "POST", body: fd });
    },
    import: (file: File, name?: string) => {
      const fd = new FormData();
      fd.append("file", file);
      if (name) fd.append("name", name);
      return request<Bank>("/banks/import", { method: "POST", body: fd });
    },
    list: () => request<Bank[]>("/banks"),
    stats: (id: string) => request<BankStats>(`/banks/${id}/stats`),
    round: (id: string, mode: "random" | "wrong", size: number) =>
      request<BankRound>(`/banks/${id}/round`, {
        method: "POST",
        ...jsonBody({ mode, size }),
      }),
    attempt: (questionId: string, content: string[]) =>
      request<BankAttemptResult>("/banks/attempts", {
        method: "POST",
        ...jsonBody({ question_id: questionId, content }),
      }),
    wrong: (id: string) => request<BankWrongQuestion[]>(`/banks/${id}/wrong`),
    rename: (id: string, name: string) =>
      request<{ ok: boolean }>(`/banks/${id}`, {
        method: "PATCH",
        ...jsonBody({ name }),
      }),
    remove: (id: string) => request<{ ok: boolean }>(`/banks/${id}`, { method: "DELETE" }),
  },
  study: {
    ping: (seconds: number) => request<{ ok: boolean }>("/study/ping", { method: "POST", ...jsonBody({ seconds }) }),
  },
  system: {
    accessInfo: () => request<AccessInfo>("/system/access-info"),
    setLanAccess: (enabled: boolean) =>
      request<AccessInfo>(`/system/lan-access?enabled=${enabled}`, { method: "POST" }),
    rotateToken: () => request<AccessInfo>("/system/access-token/rotate", { method: "POST" }),
    backup: () => request<BackupItem>("/system/backup", { method: "POST" }),
    backups: () => request<BackupItem[]>("/system/backups"),
    restore: (name: string) =>
      request<{ ok: boolean; message: string }>(`/system/backups/${name}/restore`, { method: "POST" }),
    deleteBackup: (name: string) => request<{ ok: boolean }>(`/system/backups/${name}`, { method: "DELETE" }),
    openUrl: (url: string) =>
      request<{ ok: boolean }>("/system/open-url", { method: "POST", ...jsonBody({ url }) }),
  },
  annotations: {
    listForDoc: (docId: string) =>
      request<Annotation[]>(`/documents/${docId}/annotations`),
    create: (docId: string, body: Anchor & { color: AnnotationColor }) =>
      request<AnnotationCreated>(`/documents/${docId}/annotations`, {
        method: "POST",
        ...jsonBody(body),
      }),
    update: (
      id: string,
      body: {
        color?: AnnotationColor;
        note?: string | null;
        status?: string;
        anchor?: Anchor;
      }
    ) => request<Annotation>(`/annotations/${id}`, {
      method: "PATCH",
      ...jsonBody(body),
    }),
    remove: (id: string) =>
      request<void>(`/annotations/${id}`, { method: "DELETE" }),
    conversation: (id: string) =>
      request<{ conversation_id: string }>(`/annotations/${id}/conversation`),
  },
  conversations: {
    messages: (id: string) =>
      request<Message[]>(`/conversations/${id}/messages`),
  },
  knowledgePoints: {
    forDoc: (docId: string) =>
      request<KnowledgePoint[]>(`/documents/${docId}/knowledge-points`),
  },
  dashboard: {
    summary: () => request<DashboardSummary>("/dashboard/summary"),
  },
  tutor: {
    diagnoseSSE: (
      body: { exercise_id: string; content: string; question?: string; mode?: "socratic" | "direct" },
      onEvent: (payload: any) => void,
      signal?: AbortSignal
    ) => streamSSE("/tutor/diagnose", body, onEvent, signal),
  },
};


