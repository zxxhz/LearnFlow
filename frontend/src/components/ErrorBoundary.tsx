// 全局错误边界：捕获渲染期异常，避免整个应用白屏（PRD 工程规范）
// compact 模式：块级使用（如阅读页单段落），异常只降级当前块，不拖垮整页
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  compact?: boolean;
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
      if (this.props.compact) {
        return (
          <div className="my-2 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
            <span className="shrink-0">⚠️</span>
            <span className="flex-1 truncate" title={this.state.error.message}>
              该段落渲染失败：{this.state.error.message}
            </span>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="shrink-0 underline"
            >
              重试
            </button>
          </div>
        );
      }
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
