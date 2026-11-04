// 通用 UI 原语：全应用一致的轻量组件集
import { ReactNode, useEffect, useRef, useState } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  children,
  variant = "primary",
  className = "",
  disabled,
  onClick,
  type = "button",
  title,
}: {
  children: ReactNode;
  variant?: ButtonVariant;
  className?: string;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
  title?: string;
}) {
  const styles: Record<ButtonVariant, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-200",
    secondary:
      "border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/50 disabled:opacity-50",
    danger: "bg-red-600 text-white hover:bg-red-700 disabled:opacity-50",
    ghost: "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50",
  };
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium transition ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm outline-none focus:border-brand-500 dark:focus:border-brand-400 focus:ring-1 focus:ring-brand-500 ${className}`}
    />
  );
}

export function Textarea(
  props: React.TextareaHTMLAttributes<HTMLTextAreaElement>
) {
  const { className = "", ...rest } = props;
  return (
    <textarea
      {...rest}
      className={`w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm outline-none focus:border-brand-500 dark:focus:border-brand-400 focus:ring-1 focus:ring-brand-500 ${className}`}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return (
    <select
      {...rest}
      className={`w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm outline-none focus:border-brand-500 dark:focus:border-brand-400 ${className}`}
    />
  );
}

export function Badge({
  children,
  color = "gray",
  className = "",
  title,
}: {
  children: ReactNode;
  color?: "gray" | "green" | "blue" | "red" | "amber" | "purple";
  className?: string;
  title?: string;
}) {
  const styles = {
    gray: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400",
    green: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400",
    blue: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400",
    red: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
    amber: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
    purple: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-400",
  };

  return (
    <span
      title={title}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${styles[color]} ${className}`}
    >
      {children}
    </span>
  );
}


export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 dark:border-gray-600 border-t-brand-600 ${className}`}
    />
  );
}

// 全站统一的 Esc 关闭栈：只有最后打开的层（模态框/菜单）响应 Esc。
// 本监听在模块加载时注册，早于阅读页抽屉等各自挂的 Esc 监听，
// 因此栈非空时 stopImmediatePropagation 能可靠阻止它们在同一次按键里被同时触发；
// 栈为空时直接放行，不影响阅读页抽屉等原有 Esc 行为。
type EscEntry = { token: symbol; onEsc: () => void };
const _escStack: EscEntry[] = [];
if (typeof window !== "undefined") {
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Escape" || _escStack.length === 0) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      _escStack[_escStack.length - 1].onEsc();
    },
    true,
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: string;
}) {
  // 进出场动画：render 控制是否挂载（出场过渡完成后再卸载），shown 控制过渡目标态。
  // 20ms 延迟与项目内抽屉（ExerciseDrawer 等）一致：先绘制初始态，过渡才会生效。
  const [render, setRender] = useState(open);
  const [shown, setShown] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const prevActiveRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    prevActiveRef.current = document.activeElement as HTMLElement | null;
    setRender(true);
    const t = setTimeout(() => {
      setShown(true);
      if (panelRef.current) {
        const focusable = panelRef.current.querySelector<HTMLElement>(
          'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]):not([aria-label="关闭"]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable) {
          focusable.focus();
        } else {
          panelRef.current.focus();
        }
      }
    }, 20);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (open) return;
    setShown(false);
    const t = setTimeout(() => {
      setRender(false);
      prevActiveRef.current?.focus?.();
    }, 200);
    return () => clearTimeout(t);
  }, [open]);

  // Tab 焦点循环陷阱：防止 Tab 键穿透至背景层
  useEffect(() => {
    if (!open || !shown) return;
    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusables = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleTab);
    return () => window.removeEventListener("keydown", handleTab);
  }, [open, shown]);

  // Esc 关闭栈顶模态框（栈机制见 _escStack 注释）
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const token = Symbol("modal");
    const entry: EscEntry = { token, onEsc: () => onCloseRef.current() };
    _escStack.push(entry);
    return () => {
      const i = _escStack.findIndex((x) => x.token === token);
      if (i >= 0) _escStack.splice(i, 1);
    };
  }, [open]);

  if (!render) return null;
  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center transition-colors duration-200 ease-out ${
        shown ? "bg-black/40" : "bg-black/0"
      }`}
      role="dialog"
      aria-modal="true"
      aria-hidden={!open}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`w-full ${width} rounded-xl bg-white dark:bg-gray-900 p-5 shadow-xl transition-all duration-200 ease-out outline-none ${
          shown ? "translate-y-0 scale-100 opacity-100" : "translate-y-2 scale-95 opacity-0"
        }`}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title} width="max-w-sm">
      <p className="text-sm text-gray-600 dark:text-gray-400">{message}</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          取消
        </Button>
        <Button variant="danger" onClick={onConfirm}>
          确认
        </Button>
      </div>
    </Modal>
  );
}

/** 轻量操作反馈 toast：进场 slideUp，出计时后 200ms 淡出再回调 onDone（通常用于清空 message）。 */
export function Toast({
  message,
  onDone,
  duration = 3500,
}: {
  message: string;
  onDone?: () => void;
  duration?: number;
}) {
  const [closing, setClosing] = useState(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!message) return;
    setClosing(false);
    const t = setTimeout(() => setClosing(true), duration);
    return () => clearTimeout(t);
  }, [message, duration]);

  useEffect(() => {
    if (!closing || !message) return;
    const t = setTimeout(() => onDoneRef.current?.(), 200);
    return () => clearTimeout(t);
  }, [closing, message]);

  if (!message) return null;
  return (
    <div
      role="status"
      className={`fixed bottom-6 right-6 z-50 max-w-sm rounded-xl bg-gray-900 px-4 py-3 text-sm text-white shadow-xl animate-slideUp transition-all duration-200 ease-out dark:bg-gray-800 ${
        closing ? "translate-y-2 opacity-0" : "translate-y-0 opacity-100"
      }`}
    >
      {message}
    </div>
  );
}

export interface MenuItem {
  label: string;
  /** 可选的 emoji/字符前缀 */
  icon?: string;
  /** 危险操作（删除等）以红字呈现 */
  danger?: boolean;
  onSelect: () => void;
}

/** 轻量下拉菜单：面板常驻渲染 + opacity/scale 过渡（无需卸载即有出场动画）；
 *  点外部或 Esc 关闭。Esc 走全站统一 _escStack：叠在 Modal 内时先关菜单再关模态框。 */
export function DropdownMenu({
  label,
  items,
  triggerClassName = "",
  align = "right",
  title,
}: {
  /** 触发按钮内容（文字或图标） */
  label: ReactNode;
  items: MenuItem[];
  triggerClassName?: string;
  align?: "left" | "right";
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const token = Symbol("menu");
    const entry: EscEntry = { token, onEsc: () => setOpen(false) };
    _escStack.push(entry);
    document.addEventListener("mousedown", onDown);
    return () => {
      const i = _escStack.findIndex((x) => x.token === token);
      if (i >= 0) _escStack.splice(i, 1);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={triggerClassName}
      >
        {label}
      </button>
      <div
        role="menu"
        aria-hidden={!open}
        className={`absolute top-full z-40 mt-1.5 min-w-[10rem] rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-1.5 shadow-lg transition-all duration-150 ease-out ${
          align === "right" ? "right-0 origin-top-right" : "left-0 origin-top-left"
        } ${open ? "scale-100 opacity-100 visible" : "pointer-events-none scale-95 opacity-0 invisible"}`}
      >
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              item.onSelect();
            }}
            className={`flex w-full items-center gap-2 whitespace-nowrap px-3.5 py-2 text-left text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800 ${
              item.danger
                ? "text-red-600 dark:text-red-400"
                : "text-gray-700 dark:text-gray-300"
            }`}
          >
            {item.icon && (
              <span aria-hidden className="shrink-0">
                {item.icon}
              </span>
            )}
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function EmptyState({
  icon = "📭",
  title,
  hint,
  action,
}: {
  icon?: string;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <div className="text-4xl">{icon}</div>
      <div className="text-sm font-medium text-gray-700 dark:text-gray-300">{title}</div>
      {hint && <div className="max-w-sm text-xs text-gray-400 dark:text-gray-500">{hint}</div>}
      {action}
    </div>
  );
}

export function ErrorText({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return <p className="mt-1 text-xs text-red-600 dark:text-red-400">{children}</p>;
}
