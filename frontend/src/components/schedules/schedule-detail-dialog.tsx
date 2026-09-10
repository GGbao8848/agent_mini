/* Schedule detail dialog (MCP-card style): click a schedule card to open its
   full details, then edit inline — task input, enable state and the model its
   runs use (two-level provider → model picker). */
import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useModelConfig, useScheduleManage } from "@/hooks/use-console"
import type { Schedule } from "@/lib/types"
import { CalendarClockIcon, PencilIcon } from "lucide-react"

const TYPE_LABELS: Record<string, string> = {
  one_time: "仅一次（指定时刻）",
  cron: "重复执行（每天 / 每周 / 每月）",
  interval: "每隔一段时间",
}

/** Two-level model select (endpoint → model) for forms; "默认模型" clears. */
export function ScheduleModelSelect({
  value,
  onChange,
}: {
  value: string | null
  onChange: (spec: string | null) => void
}) {
  const config = useModelConfig()
  const options = config.data?.available_models ?? []
  const groups = options.reduce<Record<string, typeof options>>((acc, option) => {
    ;(acc[option.provider] ??= []).push(option)
    return acc
  }, {})
  return (
    <Select
      value={value ?? "__default"}
      onValueChange={(v) => onChange(v === "__default" ? null : v)}
    >
      <SelectTrigger className="w-full font-mono text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="__default">
          默认模型{config.data?.effective_model ? `（${config.data.effective_model}）` : ""}
        </SelectItem>
        {Object.entries(groups).map(([provider, models]) => (
          <SelectGroup key={provider}>
            <SelectLabel className="font-mono text-xs">{provider}</SelectLabel>
            {models.map((option) => (
              <SelectItem key={option.spec} value={option.spec} className="font-mono text-xs">
                {option.model}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}

export function ScheduleDetailDialog({
  schedule,
  onClose,
}: {
  schedule: Schedule | null
  onClose: () => void
}) {
  const manage = useScheduleManage()
  const [editing, setEditing] = React.useState(false)
  const [name, setName] = React.useState("")
  const [taskInput, setTaskInput] = React.useState("")
  const [model, setModel] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (schedule) {
      setEditing(false)
      setName(schedule.name)
      setTaskInput(schedule.task_input)
      setModel(schedule.model ?? null)
    }
  }, [schedule])

  const save = () => {
    if (!schedule || !name.trim() || !taskInput.trim()) return
    manage.update.mutate(
      {
        scheduleId: schedule.id,
        payload: {
          name: name.trim(),
          task_input: taskInput.trim(),
          schedule_type: schedule.schedule_type,
          run_at: schedule.run_at,
          cron_expr: schedule.cron_expr,
          interval_minutes: schedule.interval_minutes,
          enabled: schedule.enabled,
          model,
        },
      },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <Dialog open={schedule !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 overflow-y-auto sm:max-w-xl">
        {schedule && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <CalendarClockIcon className="size-4" />
                {editing ? "编辑日程" : schedule.name}
              </DialogTitle>
              {!editing && (
                <DialogDescription className="flex items-center gap-2">
                  <Badge variant="secondary">{TYPE_LABELS[schedule.schedule_type]}</Badge>
                  <Badge variant={schedule.enabled ? "default" : "outline"}>
                    {schedule.enabled ? "启用" : "停用"}
                  </Badge>
                </DialogDescription>
              )}
            </DialogHeader>

            {!editing ? (
              <div className="flex flex-col gap-2 text-sm">
                <Detail label="触发" value={schedule.trigger_text} mono />
                {schedule.run_at && (
                  <Detail label="运行时刻" value={new Date(schedule.run_at).toLocaleString()} />
                )}
                {schedule.cron_expr && (
                  <Detail label="cron 表达式" value={schedule.cron_expr} mono />
                )}
                {schedule.interval_minutes != null && (
                  <Detail label="间隔（分钟）" value={String(schedule.interval_minutes)} />
                )}
                <Detail label="任务输入" value={schedule.task_input} multiline />
                <Detail label="使用模型" value={schedule.model ?? "默认模型"} mono />
                <div className="grid grid-cols-2 gap-x-2 gap-y-1 pt-1 text-xs text-muted-foreground">
                  <span>
                    上次运行：
                    {schedule.last_run_at ? new Date(schedule.last_run_at).toLocaleString() : "—"}
                  </span>
                  <span>已运行 {schedule.run_count} 次</span>
                  <span>
                    下次运行：
                    {schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : "—"}
                  </span>
                  <span>创建于：{new Date(schedule.created_at).toLocaleString()}</span>
                </div>
                <div className="flex gap-2 pt-2">
                  <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                    <PencilIcon data-icon="inline-start" />
                    编辑
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="sd-name">名称</Label>
                  <Input id="sd-name" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="sd-input">任务输入</Label>
                  <Textarea
                    id="sd-input"
                    rows={3}
                    value={taskInput}
                    onChange={(e) => setTaskInput(e.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label>使用模型</Label>
                  <ScheduleModelSelect value={model} onChange={setModel} />
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={save} disabled={manage.update.isPending || !name.trim() || !taskInput.trim()}>
                    保存
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                    取消
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Detail({
  label,
  value,
  mono,
  multiline,
}: {
  label: string
  value: string
  mono?: boolean
  multiline?: boolean
}) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-2">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span
        className={`min-w-0 break-words text-sm ${mono ? "font-mono text-xs" : ""} ${
          multiline ? "whitespace-pre-wrap" : ""
        }`}
      >
        {value}
      </span>
    </div>
  )
}
