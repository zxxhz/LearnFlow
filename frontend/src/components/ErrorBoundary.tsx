// 全局错误边界：捕获渲染期异常，避免整个应用白屏（PRD 工程规范）
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("渲染异常被 ErrorBoundary 捕获:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
          <div className="text-4xl">⚠️</div>
          <div className="text-base font-semibold text-gray-800 dark:text-gray-200">
            页面渲染出现问题
          </div>
          <pre className="max-w-xl overflow-auto rounded-lg bg-gray-50 dark:bg-gray-800/60 p-3 text-xs text-red-600 dark:text-red-400">
            {this.state.error.message}
          </pre>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              重试
            </button>
            <button
              type="button"
              onClick={() => (window.location.href = "/")}
              className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm text-white hover:bg-brand-700"
            >
              返回首页
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
