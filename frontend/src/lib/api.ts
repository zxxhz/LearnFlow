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
  FeynmanSession,
  FeynmanSessionDetail,
  ImportAnalysis,
  ImportSpec,
  KnowledgePoint,
  LLMConfig,
  LLMTestResult,
  Message,
  OutlineItem,
  Preferences,
  ReviewCard,
  ReviewQueue,
  ReviewStats,
  SceneLLMConfig,
  SceneName,
  SettingsData,
  InstallStatus,
  RuntimeComponentName,
  RuntimeStatus,
  UpdateCheckResult,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  const res = await fetch(BASE + path, {
    ...opts,
    headers: isForm ? opts.headers : { "Content-Type": "application/json", ...opts.headers },
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
    generate: (id: string) =>
      request<Course>(`/courses/${id}/generate`, { method: "POST" }),
    list: () => request<CourseListItem[]>("/courses"),
    get: (id: string) => request<CourseDetail>(`/courses/${id}`),
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
    regenerate: (id: string, instruction?: string) =>
      request<{ ok: boolean }>(`/documents/${id}/regenerate`, {
        method: "POST",
        ...jsonBody({ instruction: instruction ?? null }),
      }),
    executions: (id: string) =>
      request<CodeExecution[]>(`/documents/${id}/executions`),
  },
  executions: {
    run: (body: { document_id: string; section_id: string; language: string; code: string }) =>
      request<CodeExecution>("/executions", { method: "POST", ...jsonBody(body) }),
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
  feynman: {
    start: (body: { knowledge_point_id: string; explanation: string }) =>
      request<FeynmanSessionDetail>("/feynman/sessions", {
        method: "POST",
        ...jsonBody(body),
      }),
    kpContext: (kpId: string) =>
      request<{
        knowledge_point: KnowledgePoint;
        document_id: string;
        document_title: string;
        course_id: string;
        course_title: string;
      }>(`/feynman/kp-context/${kpId}`),
    list: (knowledgePointId?: string) =>
      request<FeynmanSession[]>(
        `/feynman/sessions${
          knowledgePointId ? `?knowledge_point_id=${knowledgePointId}` : ""
        }`
      ),
    get: (id: string) => request<FeynmanSessionDetail>(`/feynman/sessions/${id}`),
    evaluate: (id: string) =>
      request<FeynmanSessionDetail>(`/feynman/sessions/${id}/evaluate`, {
        method: "POST",
      }),
  },
  review: {
    queueToday: () => request<ReviewQueue>("/review/queue/today"),
    grade: (cardId: string, quality: 1 | 3 | 4 | 5) =>
      request<ReviewCard>(`/review/cards/${cardId}/grade`, {
        method: "POST",
        ...jsonBody({ quality }),
      }),
    createCard: (body: {
      front: string;
      back?: string;
      knowledge_point_id?: string | null;
      annotation_id?: string | null;
    }) => request<ReviewCard>("/review/cards", { method: "POST", ...jsonBody(body) }),
    updateCard: (id: string, body: { front?: string; back?: string; suspended?: boolean }) =>
      request<ReviewCard>(`/review/cards/${id}`, { method: "PATCH", ...jsonBody(body) }),
    deleteCard: (id: string) =>
      request<void>(`/review/cards/${id}`, { method: "DELETE" }),
    stats: () => request<ReviewStats>("/review/stats"),
  },
  dashboard: {
    summary: () => request<DashboardSummary>("/dashboard/summary"),
  },
};
