/* Human-friendly helpers for cron schedule types (5-field: minute hour
   day-of-month month day-of-week, APScheduler crontab). The console hides raw
   cron from non-technical users: these convert between a readable
   daily/weekly/monthly description and the underlying expression. */

export type CronFreq = "daily" | "weekly" | "monthly"

export interface ParsedCron {
  freq: CronFreq
  hour: number
  minute: number
  /** 0 = Sunday … 6 = Saturday (cron day-of-week values). */
  weekday?: number
  monthday?: number
}

/** Parse a simple cron expression into readable parts; null when the
 *  expression is too complex to represent with the presets (lists, ranges,
 *  multiple days, …). */
export function parseCron(expr: string | null | undefined): ParsedCron | null {
  if (!expr) return null
  const fields = expr.trim().split(/\s+/)
  if (fields.length !== 5) return null
  const [minuteField, hourField, domField, monthField, dowField] = fields
  const toInt = (s: string) => (/^\d+$/.test(s) ? Number(s) : null)
  const minute = toInt(minuteField)
  const hour = toInt(hourField)
  if (minute === null || hour === null || minute > 59 || hour > 23) return null
  if (monthField !== "*") return null
  if (domField === "*" && dowField === "*") {
    return { freq: "daily", hour, minute }
  }
  if (domField === "*" && dowField !== "*") {
    const weekday = toInt(dowField)
    if (weekday !== null && weekday <= 6) return { freq: "weekly", hour, minute, weekday }
    return null
  }
  if (domField !== "*" && dowField === "*") {
    const monthday = toInt(domField)
    if (monthday !== null && monthday >= 1 && monthday <= 31) {
      return { freq: "monthly", hour, minute, monthday }
    }
    return null
  }
  return null
}

function pad(n: number): string {
  return String(n).padStart(2, "0")
}

export function formatTime(hour: number, minute: number): string {
  return `${pad(hour)}:${pad(minute)}`
}

const WEEKDAY_NAMES = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

/** "每天 09:00" / "每周一 09:00" / "每月 1 号 09:00"; null when the expression
 *  can't be summarized (fall back to showing the raw expression). */
export function describeCron(expr: string | null | undefined): string | null {
  const parsed = parseCron(expr)
  if (!parsed) return null
  const time = formatTime(parsed.hour, parsed.minute)
  if (parsed.freq === "daily") return `每天 ${time}`
  if (parsed.freq === "weekly") return `每周${WEEKDAY_NAMES[parsed.weekday ?? 1].slice(1)} ${time}`
  return `每月 ${parsed.monthday} 号 ${time}`
}
