// 局域网令牌失效（401）自救：监听 api 层广播，弹出粘贴新地址/令牌的统一入口。
// PWA / 已收藏页面拿不到后端的 HTML 引导页（XHR 401 只有 JSON），必须由 SPA 自己承接。
import { useEffect, useState } from "react";
import { Button, Input, Modal } from "./ui";
import { getAccessToken } from "../lib/api";

function extractToken(input: string): string | null {
  const t = input.trim();
  if (!t) return null;
  // 直接粘贴令牌
  if (/^[A-Za-z0-9_-]{16,}$/.test(t)) return t;
  // 粘贴完整地址 http://host:port/?token=xxx
  try {
    const u = new URL(t);
    const token = u.searchParams.get("token");
    if (token) return token;
  } catch {
    /* 非完整地址 */
  }
  const m = t.match(/token=([A-Za-z0-9_-]+)/);
  return m ? m[1] : null;
}

export default function AuthGate() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    const onExpired = () => {
      setOpen(true);
      setErr("");
      setValue("");
    };
    window.addEventListener("learnflow:auth-expired", onExpired);
    return () => window.removeEventListener("learnflow:auth-expired", onExpired);
  }, []);

  if (!open) return null;

  const submit = () => {
    const token = extractToken(value);
    if (!token) {
      setErr("未能识别令牌：请粘贴完整访问地址（含 ?token=…）或令牌本身");
      return;
    }
    try {
      localStorage.setItem("lf_access_token", token);
    } catch {
      /* ignore */
    }
    setOpen(false);
    // 重新拉取当前页数据（清空缓存确保旧 401 结果不残留）
    window.location.reload();
  };

  return (
    <Modal open={open} onClose={() => setOpen(false)} title="🔑 访问令牌已失效" width="max-w-md">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        局域网访问令牌已被更换或过期。请在运行 LearnFlow 的电脑上打开
        「设置 → 局域网访问」，复制最新访问地址（或令牌）粘贴到下方。
      </p>
      <Input
        className="mt-3"
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
        }}
        placeholder="http://192.168.x.x:8420/?token=… 或直接粘贴令牌"
        aria-label="新的访问令牌或地址"
      />
      {err && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{err}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={() => setOpen(false)}>
          稍后
        </Button>
        <Button onClick={submit}>保存并刷新</Button>
      </div>
      <p className="mt-3 text-[11px] text-gray-400 dark:text-gray-500">
        当前缓存令牌：{getAccessToken() ? "已保存（已失效）" : "无"}
      </p>
    </Modal>
  );
}
