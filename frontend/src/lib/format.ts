// 通用格式化工具函数

/**
 * 将 ISO 时间戳或日期字符串格式化为本地可读的 "YYYY-MM-DD HH:mm:ss"
 * 例如将 "2026-11-11T03:28:03.691230+00:00" 转换为用户本地时区的 "2026-11-11 11:28:03"
 */
export function formatSyncTime(dateStr?: string | null): string {
  if (!dateStr) return "尚未同步";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
}
