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
