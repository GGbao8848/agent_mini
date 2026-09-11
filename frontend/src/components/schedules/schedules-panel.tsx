import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Textarea } from "@/components/ui/textarea"
import { FolderControl } from "@/components/folder-control"
import { useScheduleManage, useSchedules, useSubmitTask } from "@/hooks/use-console"
import type { PermissionMode, Schedule, ScheduleType } from "@/lib/types"
import { ScheduleDetailDialog } from "@/components/schedules/schedule-detail-dialog"
import { ScheduleToggle } from "@/components/schedules/schedule-toggle"
import { getSelectedModel } from "@/components/chat/model-picker"
import {
  PermissionModePicker,
  permissionModeLabel,
} from "@/components/chat/permission-mode-picker"
import { describeCron } from "@/lib/schedule"
import { ArrowUpIcon, CalendarClockIcon, PlayIcon, PlusIcon, Trash2Icon } from "lucide-react"

const TYPE_LABELS: Record<ScheduleType, string> = {
  one_time: "仅一次（指定时刻）",
  cron: "重复执行（每天 / 每周 / 每月）",
  interval: "每隔一段时间",
}

/** Human-readable trigger for the schedule card: cron shows the friendly
 *  preset summary (falls back to the raw expression when it doesn't fit). */
function describeTrigger(schedule: Schedule): string {
  if (schedule.schedule_type === "interval") {
    return `每隔 ${schedule.interval_minutes} 分钟执行一次`
  }
  const friendly = describeCron(schedule.cron_expr)
  return friendly ?? `重复执行 · ${schedule.trigger_text}`
}


/** Natural-language schedule creation: the user describes what they want and
 *  sending it starts a fresh conversation — the avatar agent parses the
 *  request and creates the schedule itself (no manual form). */
function ScheduleRequestDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (taskId: string) => void
}) {
  const submit = useSubmitTask()
  const [input, setInput] = React.useState("")
  // The schedule the agent creates inherits this conversation's mode, so this
  // is where an unattended job picks 自动编辑/完全访问 instead of stalling on a
  // 变更前确认 prompt later.
  const [mode, setMode] = React.useState<PermissionMode>("auto")
  // The folder the schedule's runs will work in (null = the default folder).
  // The conversation that creates the schedule is bound here, so the agent
  // inherits it; scheduled runs then keep their files in that folder.
  const [projectId, setProjectId] = React.useState<string | null>(null)

  const close = () => {
    if (submit.isPending) return
    onOpenChange(false)
    setInput("")
  }

  const send = () => {
    const text = input.trim()
    if (!text || submit.isPending) return
    submit.mutate(
      {
        input: text,
        model: getSelectedModel(),
        permission_mode: mode,
        project_id: projectId,
      },
      {
        onSuccess: (task) => {
          setInput("")
          onOpenChange(false)
          onCreated(task.id)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && close()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建日程</DialogTitle>
          <DialogDescription>
            用一句话描述你想要的定时任务，发送后会开启一段新对话，由分身 AI 帮你解析并创建日程。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Textarea
            autoFocus
            rows={3}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            placeholder="例如：每天早上 9 点，把最新行业动态整理成摘要发我"
          />
          <p className="text-xs text-muted-foreground">
            支持一次性 / 每天 / 每周 / 每月等重复规则，也支持「每 2 小时」这类间隔。
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">日程权限模式</span>
            <PermissionModePicker value={mode} onChange={setMode} />
            <span className="ml-2 text-xs text-muted-foreground">工作文件夹</span>
            <FolderControl currentProjectId={projectId} onSelect={setProjectId} />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={send} disabled={!input.trim() || submit.isPending}>
            {submit.isPending ? (
              <span className="flex items-center gap-2">发起中…</span>
            ) : (
              <>
                发送
                <ArrowUpIcon data-icon="inline-end" />
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function SchedulesPanel({
  onOpenTask,
}: {
  onOpenTask?: (taskId: string) => void
}) {
  const schedules = useSchedules()
  const manage = useScheduleManage()
  const [requestOpen, setRequestOpen] = React.useState(false)
  const [detail, setDetail] = React.useState<Schedule | null>(null)
  const [removingId, setRemovingId] = React.useState<string | null>(null)
  const [runningId, setRunningId] = React.useState<string | null>(null)
  const [togglingId, setTogglingId] = React.useState<string | null>(null)

  const list = schedules.data ?? []

  const toggleEnabled = (schedule: Schedule, enabled: boolean) => {
    setTogglingId(schedule.id)
    manage.update.mutate(
      {
        scheduleId: schedule.id,
        payload: {
          name: schedule.name,
          task_input: schedule.task_input,
          schedule_type: schedule.schedule_type,
          run_at: schedule.run_at,
          cron_expr: schedule.cron_expr,
          interval_minutes: schedule.interval_minutes,
          enabled,
        },
      },
      { onSettled: () => setTogglingId(null) },
    )
  }

  const openRequest = () => setRequestOpen(true)
  const jumpToTask = (taskId: string) => {
    if (onOpenTask) {
      onOpenTask(taskId)
      return
    }
    window.dispatchEvent(new CustomEvent("console:open-task", { detail: { taskId } }))
  }

  // Empty state: a centered "描述并创建" button is the whole page.
  if (!schedules.isLoading && list.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <CalendarClockIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有日程</h2>
          <p className="text-sm text-muted-foreground">
            用一句话描述定时任务，分身 AI 会帮你创建日程；到点自动以新对话运行。
          </p>
        </div>
        <Button size="sm" onClick={openRequest}>
          <PlusIcon data-icon="inline-start" />
          描述并新建日程
        </Button>
        <ScheduleRequestDialog
          open={requestOpen}
          onOpenChange={setRequestOpen}
          onCreated={jumpToTask}
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">日程（{list.length} 个）</h2>
        <Button size="sm" onClick={openRequest}>
          <PlusIcon data-icon="inline-start" />
          新建日程
        </Button>
      </div>

      {schedules.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((schedule) => (
            <div
              key={schedule.id}
              role="button"
              tabIndex={0}
              onClick={() => setDetail(schedule)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  setDetail(schedule)
                }
              }}
              className="group/schedule flex h-full cursor-pointer flex-col gap-1.5 rounded-lg border p-4 outline-none transition-colors hover:border-foreground/25 hover:bg-accent/40 focus-visible:ring-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium" title={schedule.name}>
                  {schedule.name}
                </span>
                <Badge variant="secondary" className="shrink-0">
                  {TYPE_LABELS[schedule.schedule_type]}
                </Badge>
                <ScheduleToggle
                  schedule={schedule}
                  disabled={togglingId === schedule.id}
                  onToggle={toggleEnabled}
                />
              </div>
              <p className="text-sm font-medium">
                {schedule.schedule_type === "one_time"
                  ? `执行一次${schedule.run_at ? ` · ${new Date(schedule.run_at).toLocaleString()}` : ""}`
                  : describeTrigger(schedule)}
              </p>
              <p className="line-clamp-2 text-xs text-muted-foreground" title={schedule.task_input}>
                任务：{schedule.task_input}
              </p>
              <p className="text-xs text-muted-foreground">
                {schedule.last_run_at
                  ? `上次运行 ${new Date(schedule.last_run_at).toLocaleString()} · `
                  : ""}
                运行 {schedule.run_count} 次
                {schedule.next_run_at
                  ? ` · 下次 ${new Date(schedule.next_run_at).toLocaleString()}`
                  : ""}
                {" · "}
                {permissionModeLabel(schedule.permission_mode)}
              </p>
              <div className="mt-auto flex items-center gap-1 pt-1">
                <Button
                  size="xs"
                  variant="ghost"
                  disabled={runningId === schedule.id}
                  onClick={(e) => {
                    e.stopPropagation()
                    setRunningId(schedule.id)
                    manage.runNow.mutate(schedule.id, {
                      onSuccess: (data) => {
                        setRunningId(null)
                        if (data?.task_id) jumpToTask(data.task_id)
                      },
                      onError: () => setRunningId(null),
                    })
                  }}
                  title="运行一次"
                >
                  <PlayIcon data-icon="inline-start" />
                  运行一次
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  className="ml-auto text-destructive"
                  onClick={(e) => {
                    e.stopPropagation()
                    setRemovingId(schedule.id)
                  }}
                >
                  <Trash2Icon data-icon="inline-start" />
                  删除
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ScheduleRequestDialog
        open={requestOpen}
        onOpenChange={setRequestOpen}
        onCreated={jumpToTask}
      />

      <ScheduleDetailDialog schedule={detail} onClose={() => setDetail(null)} />

      <AlertDialog
        open={removingId !== null}
        onOpenChange={(isOpen) => !isOpen && setRemovingId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除日程？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后不再自动运行；已产生的任务对话保留在任务台。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removingId) manage.remove.mutate(removingId)
                setRemovingId(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
