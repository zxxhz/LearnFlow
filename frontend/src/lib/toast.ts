// 全局事件驱动式轻量 Toast 通知机制

export interface ToastPayload {
  message: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function showToast(
  message: string,
  options?: {
    duration?: number;
    action?: {
      label: string;
      onClick: () => void;
    };
  }
) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent<ToastPayload>("learnflow:toast", {
        detail: { message, ...options },
      })
    );
  }
}
