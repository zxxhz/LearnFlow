// 字号调节器组件（A- / 当前字号重置 / A+，紧凑微型组件，支持浅色/深色主题）
interface FontSizeControlProps {
  value: number;
  onChange: (val: number | ((prev: number) => number)) => void;
  min?: number;
  max?: number;
  defaultValue?: number;
  className?: string;
  label?: string;
}

export function FontSizeControl({
  value,
  onChange,
  min = 13,
  max = 24,
  defaultValue = 16,
  className = "",
  label,
}: FontSizeControlProps) {
  return (
    <div
      className={`inline-flex items-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white/90 dark:bg-gray-800/90 p-0.5 text-xs shadow-sm backdrop-blur transition-all ${className}`}
      title={`字号调节：当前 ${value}px（点击中间数字恢复默认 ${defaultValue}px）`}
    >
      {label && (
        <span className="hidden sm:inline pl-1.5 pr-0.5 text-[11px] text-gray-400 dark:text-gray-500 select-none">
          {label}
        </span>
      )}
      <button
        type="button"
        disabled={value <= min}
        onClick={() => onChange((prev) => Math.max(min, prev - 1))}
        className="flex h-6 w-6 items-center justify-center rounded text-[11px] font-bold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:pointer-events-none transition"
        title={`缩小字号 (A-)，当前 ${value}px`}
      >
        A-
      </button>
      <button
        type="button"
        onClick={() => onChange(defaultValue)}
        className="min-w-[34px] px-1 text-center font-semibold text-gray-700 dark:text-gray-200 hover:text-brand-600 dark:hover:text-brand-400 transition"
        title={`点击恢复默认字号 (${defaultValue}px)`}
      >
        {value}px
      </button>
      <button
        type="button"
        disabled={value >= max}
        onClick={() => onChange((prev) => Math.min(max, prev + 1))}
        className="flex h-6 w-6 items-center justify-center rounded text-[11px] font-bold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:pointer-events-none transition"
        title={`放大字号 (A+)，当前 ${value}px`}
      >
        A+
      </button>
    </div>
  );
}

export default FontSizeControl;
