/* Permission-mode picker for the composer: how much the agent may do
   unattended. Mirrors the editor-agent convention — 变更前确认 asks before each
   file change, 自动编辑 writes freely, 计划模式 forbids writes until the plan is
   approved, 完全访问 also lifts tool-approval prompts. The choice travels with
   each turn, so it can change mid-conversation. */
import * as React from "react"

import { Button } from "@/components/ui/button"
import type { PermissionMode } from "@/lib/types"
import { cn } from "@/lib/utils"
import { HandIcon, NotebookPenIcon, ShieldCheckIcon, ShieldIcon } from "lucide-react"

type Option = {
  value: PermissionMode
  label: string
  hint: string
  Icon: React.ComponentType<{ className?: string }>
}

export const PERMISSION_MODES: Option[] = [
  {
    value: "confirm",
    label: "变更前确认",
    hint: "改文件前先问我。",
    Icon: HandIcon,
  },
  {
    value: "auto",
    label: "自动编辑",
    hint: "自动编辑文件。",
    Icon: ShieldCheckIcon,
  },
  {
    value: "plan",
    label: "计划模式",
    hint: "编辑前先出计划。",
    Icon: NotebookPenIcon,
  },
  {
    value: "full",
    label: "完全访问",
    hint: "减少确认次数。",
    Icon: ShieldIcon,
  },
]

export function permissionModeLabel(mode: PermissionMode): string {
  return PERMISSION_MODES.find((m) => m.value === mode)?.label ?? "变更前确认"
}

export function PermissionModePicker({
  value,
  onChange,
}: {
  value: PermissionMode
  onChange: (mode: PermissionMode) => void
}) {
  const [open, setOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)
  const current = PERMISSION_MODES.find((m) => m.value === value) ?? PERMISSION_MODES[0]
  const CurrentIcon = current.Icon

  React.useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("mousedown", close)
    return () => window.removeEventListener("mousedown", close)
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 px-2 text-xs text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
        title="选择分身的权限模式"
      >
        <CurrentIcon className="size-3.5" />
        <span className="max-w-40 truncate">{current.label}</span>
      </Button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-72 overflow-hidden rounded-xl border bg-popover p-1 text-popover-foreground shadow-md">
          {PERMISSION_MODES.map(({ value: mode, label, hint, Icon }) => {
            const selected = mode === value
            return (
              <button
                key={mode}
                type="button"
                onClick={() => {
                  onChange(mode)
                  setOpen(false)
                }}
                className={cn(
                  "flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                  selected ? "bg-muted" : "hover:bg-accent",
                )}
              >
                <Icon className="mt-0.5 size-5 shrink-0 text-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{label}</span>
                  <span className="block text-xs text-muted-foreground">{hint}</span>
                </span>
                {selected && (
                  <svg
                    viewBox="0 0 24 24"
                    className="mt-0.5 size-4 shrink-0 text-foreground"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
