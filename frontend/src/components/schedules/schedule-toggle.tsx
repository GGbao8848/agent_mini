/** Enable/disable switch for a schedule (shared: sidebar rows + panel cards). */
import { cn } from "@/lib/utils"
import type { Schedule } from "@/lib/types"

export function ScheduleToggle({
  schedule,
  disabled,
  onToggle,
}: {
  schedule: Schedule
  disabled: boolean
  onToggle: (schedule: Schedule, enabled: boolean) => void
}) {
  const enabled = schedule.enabled
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={enabled ? "停用日程" : "启用日程"}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation()
        onToggle(schedule, !enabled)
      }}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 outline-none disabled:cursor-not-allowed disabled:opacity-50",
        enabled ? "bg-primary" : "bg-muted-foreground/30",
      )}
    >
      <span
        className={cn(
          "pointer-events-none block size-4 rounded-full bg-background shadow-sm transition-transform",
          enabled ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  )
}
