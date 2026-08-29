import { STATUS_DOT } from "@/lib/format"
import { cn } from "@/lib/utils"

/** Tiny colored circle summarizing a run status (sidebar list). */
export function StatusDot({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn("size-2 shrink-0 rounded-full", STATUS_DOT[status] ?? "bg-zinc-400 dark:bg-zinc-600", className)}
    />
  )
}
