// localStorage / sessionStorage 安全封装：受限 WebView / 隐私模式下访问存储可能直接抛错，
// 裸调用会在启动或交互时白屏。统一 try 包裹：读失败返回 null，写失败静默并 console.warn。
// 口径与 lib/theme.ts 的手动 try/catch 一致。
function warn(op: string, key: string, e: unknown): void {
  console.warn(`[safeStorage] ${op}失败（key=${key}）:`, e);
}

function createSafeStorage(getStore: () => Storage | null) {
  return {
    get(key: string): string | null {
      const store = getStore();
      if (!store) return null;
      try {
        return store.getItem(key);
      } catch (e) {
        warn("读取", key, e);
        return null;
      }
    },
    set(key: string, value: string): void {
      const store = getStore();
      if (!store) return;
      try {
        store.setItem(key, value);
      } catch (e) {
        // 隐私模式 / 配额满：持久化失败仅影响记忆，不中断交互
        warn("写入", key, e);
      }
    },
    remove(key: string): void {
      const store = getStore();
      if (!store) return;
      try {
        store.removeItem(key);
      } catch (e) {
        warn("删除", key, e);
      }
    },
    getJSON<T = unknown>(key: string): T | null {
      const raw = this.get(key);
      if (raw == null) return null;
      try {
        return JSON.parse(raw) as T;
      } catch (e) {
        warn("解析", key, e);
        return null;
      }
    },
    setJSON(key: string, value: unknown): void {
      try {
        this.set(key, JSON.stringify(value));
      } catch (e) {
        warn("序列化", key, e);
      }
    },
  };
}

const getLocalStorage = (): Storage | null => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

const getSessionStorage = (): Storage | null => {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
};

/** localStorage 安全封装（跨会话持久化） */
export const safeStorage = createSafeStorage(getLocalStorage);

/** sessionStorage 安全封装（会话级标记，如更新弹窗「稍后提醒」） */
export const safeSessionStorage = createSafeStorage(getSessionStorage);
