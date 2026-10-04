import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "katex/dist/katex.min.css";
import "./styles/index.css";
import { applyTheme, getTheme } from "./lib/theme";

// 主题在首帧前应用，避免闪白/闪黑
applyTheme(getTheme());

// 局域网访问：若 URL 携带 token，自动持久化便于后续 API 请求携带
if (typeof window !== "undefined") {
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get("token");
  if (token) {
    try {
      localStorage.setItem("lf_access_token", token);
    } catch {}
  }
}

// PWA Service Worker 注册（非桌面壳环境下生效）
if (
  typeof window !== "undefined" &&
  "serviceWorker" in navigator &&
  !("__TAURI_INTERNALS__" in window)
) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((reg) => {
        reg.onupdatefound = () => {
          const installingWorker = reg.installing;
          if (installingWorker) {
            installingWorker.onstatechange = () => {
              if (
                installingWorker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                console.log("[PWA] 新版本资源已准备就绪");
              }
            };
          }
        };
      })
      .catch((err) => {
        console.warn("[PWA] Service Worker 注册失败:", err);
      });
  });
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
