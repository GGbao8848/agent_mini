import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useAgents, useScheduleManage, useSchedules } from "@/hooks/use-console"
import type { Schedule, SchedulePayload, ScheduleType } from "@/lib/types"
import { PencilIcon, PlayIcon, PlusIcon, Trash2Icon } from "lucide-react"

const TYPE_LABELS: Record<ScheduleType, string> = {
  one_time: "一次性",
  cron: "循环（cron）",
  interval: "间隔",
}

type FormState = {
  name: string
  agent_id: string
  task_input: string
  schedule_type: ScheduleType
  run_at: string
  cron_expr: string
  interval_minutes: string
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  name: "",
  agent_id: "",
  task_input: "",
  schedule_type: "interval",
  run_at: "",
  cron_expr: "",
  interval_minutes: "60",
  enabled: true,
}

function toPayload(form: FormState): SchedulePayload {
  return {
    name: form.name.trim(),
    agent_id: form.agent_id,
    task_input: form.task_input.trim(),
    schedule_type: form.schedule_type,
    run_at: form.schedule_type === "one_time" && form.run_at ? form.run_at : null,
    cron_expr: form.schedule_type === "cron" && form.cron_expr.trim() ? form.cron_expr.trim() : null,
    interval_minutes:
      form.schedule_type === "interval" && form.interval_minutes
        ? Number(form.interval_minutes)
        : null,
    enabled: form.enabled,
  }
}

function ScheduleDialog({
  open,
  onOpenChange,
  editing,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: Schedule | null
  onSaved: (scheduleId: string) => void
}) {
  const agents = useAgents()
  const manage = useScheduleManage()
  const agentList = agents.data ?? []
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM)
  const [error, setError] = React.useState("")

  React.useEffect(() => {
    if (open) {
      if (editing) {
        setForm({
          name: editing.name,
          agent_id: editing.agent_id,
          task_input: editing.task_input,
          schedule_type: editing.schedule_type,
          run_at: editing.run_at ?? "",
          cron_expr: editing.cron_expr ?? "",
          interval_minutes: editing.interval_minutes != null ? String(editing.interval_minutes) : "60",
          enabled: editing.enabled,
        })
      } else {
        setForm({
          ...EMPTY_FORM,
          agent_id: agentList[0]?.id ?? "",
        })
      }
      setError("")
    }
  }, [open, editing, agentList])

  const submit = () => {
    setError("")
    if (!form.name.trim() || !form.task_input.trim() || !form.agent_id) {
      setError("名称、任务输入、agent 必填")
      return
    }
    const payload = toPayload(form)
    if (editing) {
      manage.update.mutate(
        { scheduleId: editing.id, payload },
        { onSuccess: () => onSaved(editing.id) },
      )
    } else {
      manage.create.mutate(payload, {
        onSuccess: (created) => {
          onSaved(created.id)
          setForm(EMPTY_FORM)
        },
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PlusIcon data-icon="inline-start" />
        新建日程
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑日程" : "新建日程"}</DialogTitle>
          <DialogDescription>
            到点后会以一条新对话运行任务，之后可以点进对话继续。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="sc-name">名称</Label>
              <Input
                id="sc-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="每日早报"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sc-agent">agent</Label>
              <Select
                value={form.agent_id}
                onValueChange={(v) => setForm({ ...form, agent_id: v ?? "" })}
              >
                <SelectTrigger id="sc-agent" className="w-full" disabled={!agentList.length}>
                  <SelectValue placeholder="选择 agent" />
                </SelectTrigger>
                <SelectContent>
                  {agentList.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="sc-input">任务输入</Label>
            <Textarea
              id="sc-input"
              rows={2}
              value={form.task_input}
              onChange={(e) => setForm({ ...form, task_input: e.target.value })}
              placeholder="例：把 workspace/album 的图片压缩一半并汇报"
            />
          </div>
          <div className="grid gap-1.5">
            <Label>触发类型</Label>
            <Select
              value={form.schedule_type}
              onValueChange={(v) => setForm({ ...form, schedule_type: (v ?? "interval") as ScheduleType })}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(TYPE_LABELS) as ScheduleType[]).map((t) => (
                  <SelectItem key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {form.schedule_type === "one_time" && (
            <div className="grid gap-1.5">
              <Label htmlFor="sc-runat">运行时刻（本地时间）</Label>
              <Input
                id="sc-runat"
                type="datetime-local"
                value={form.run_at}
                onChange={(e) => setForm({ ...form, run_at: e.target.value })}
              />
            </div>
          )}
          {form.schedule_type === "cron" && (
            <div className="grid gap-1.5">
              <Label htmlFor="sc-cron">cron 表达式（分 时 日 月 周）</Label>
              <Input
                id="sc-cron"
                value={form.cron_expr}
                onChange={(e) => setForm({ ...form, cron_expr: e.target.value })}
                placeholder="0 9 * * 1"
              />
              <p className="text-xs text-muted-foreground">
                5 段：分钟 小时 日 月 星期，例如 0 9 * * 1 = 每周一 09:00
              </p>
            </div>
          )}
          {form.schedule_type === "interval" && (
            <div className="grid gap-1.5">
              <Label htmlFor="sc-interval">间隔（分钟）</Label>
              <Input
                id="sc-interval"
                type="number"
                min={1}
                value={form.interval_minutes}
                onChange={(e) => setForm({ ...form, interval_minutes: e.target.value })}
              />
            </div>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button disabled={manage.create.isPending || manage.update.isPending} onClick={submit}>
            {editing ? "保存" : "创建"}
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
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<Schedule | null>(null)
  const [removingId, setRemovingId] = React.useState<string | null>(null)
  const [runningId, setRunningId] = React.useState<string | null>(null)

  const list = schedules.data ?? []

  const openNew = () => {
    setEditing(null)
    setDialogOpen(true)
  }
  const openEdit = (schedule: Schedule) => {
    setEditing(schedule)
    setDialogOpen(true)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">日程</CardTitle>
        <ScheduleDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          editing={editing}
          onSaved={() => setDialogOpen(false)}
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {schedules.isLoading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <p className="text-sm text-muted-foreground">还没有日程。</p>
            <Button size="sm" variant="outline" onClick={openNew}>
              <PlusIcon data-icon="inline-start" />
              新建日程
            </Button>
          </div>
        ) : (
          list.map((schedule) => (
            <div key={schedule.id} className="flex flex-col gap-1.5 rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{schedule.name}</span>
                <Badge variant="secondary">{TYPE_LABELS[schedule.schedule_type]}</Badge>
                <Badge variant={schedule.enabled ? "default" : "outline"}>
                  {schedule.enabled ? "启用" : "停用"}
                </Badge>
                <span className="ml-auto flex items-center gap-1">
                  <Button
                    size="xs"
                    variant="ghost"
                    disabled={runningId === schedule.id}
                    onClick={() => {
                      setRunningId(schedule.id)
                      manage.runNow.mutate(schedule.id, {
                        onSuccess: (data) => {
                          setRunningId(null)
                          if (onOpenTask && data?.task_id) onOpenTask(data.task_id)
                        },
                        onError: () => setRunningId(null),
                      })
                    }}
                    title="运行一次"
                  >
                    <PlayIcon data-icon="inline-start" />
                    运行一次
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => openEdit(schedule)}>
                    <PencilIcon data-icon="inline-start" />
                    编辑
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    className="text-destructive"
                    onClick={() => setRemovingId(schedule.id)}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    删除
                  </Button>
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {schedule.trigger_text} · agent {schedule.agent_id}
              </p>
              <p className="line-clamp-2 text-xs text-muted-foreground">
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
              </p>
            </div>
          ))
        )}
      </CardContent>

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
    </Card>
  )
}
