import * as React from "react"
import { ApprovalCard } from "@/components/runs/approval-card"
import { RunChatHeader } from "@/components/runs/run-detail"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  useApprovals,
  useRun,
  useRunEvents,
  useSendFollowup,
  useSubmitTask,
  useTask,
  useTasks,
} from "@/hooks/use-console"
import type { Task } from "@/lib/types"
import { ArrowUpIcon, BotIcon } from "lucide-react"

function Bubble({ role, text }: { role: "user" | "avatar"; text: string }) {
  return (
    <div className={role === "user" ? "flex justify-end" : "flex justify-start"}>
      <div
        data-role={role}
        className="max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap break-words bg-muted text-foreground data-[role=user]:bg-primary data-[role=user]:text-primary-foreground"
      >
        <div className="mb-0.5 text-[0.7rem] opacity-70">{role === "user" ? "你" : "分身"}</div>
        {text}
      </div>
    </div>
  )
}

function Composer({
  placeholder,
  pending,
  onSubmit,
  children,
}: {
  placeholder: string
  pending: boolean
  onSubmit: (text: string) => void
  children?: React.ReactNode
}) {
  const [text, setText] = React.useState("")

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || pending) return
    setText("")
    onSubmit(trimmed)
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-xl border bg-card p-2 shadow-sm">
      {children}
      <Textarea
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={placeholder}
        className="resize-none border-0 shadow-none focus-visible:ring-0"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Enter 发送 · Shift+Enter 换行</span>
        <Button size="icon-sm" disabled={pending || !text.trim()} onClick={submit}>
          <ArrowUpIcon />
          <span className="sr-only">发送</span>
        </Button>
      </div>
    </div>
  )
}

function NewTaskComposer({
  pending,
  onSubmit,
}: {
  pending: boolean
  onSubmit: (text: string) => void
}) {
  return (
    <Composer
      placeholder="给分身派个任务，例如：把画册的冬天板块加两张图…"
      pending={pending}
      onSubmit={onSubmit}
    />
  )
}

function EmptyState({
  onSubmitted,
}: {
  onSubmitted: (task: Task) => void
}) {
  const submit = useSubmitTask()
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
          <BotIcon className="size-6 text-muted-foreground" />
        </div>
        <h2 className="text-lg font-medium">给分身派个任务</h2>
        <p className="text-sm text-muted-foreground">
          在左侧选择历史任务，可以继续那条对话
        </p>
      </div>
      <div className="w-full max-w-2xl">
        <NewTaskComposer
          pending={submit.isPending}
          onSubmit={(text) =>
            submit.mutate({ input: text }, { onSuccess: onSubmitted })
          }
        />
      </div>
    </div>
  )
}

/** One conversation: the active run's header, every turn, and a follow-up box. */
function ChatThread({ task }: { task: Task }) {
  const { data: fresh } = useTask(task.id)
  const current = fresh ?? task
  const activeRun = useRun(current.active_run_id)
  const runStatus = activeRun.data?.status ?? current.status
  const events = useRunEvents(current.active_run_id, runStatus)
  const approvals = useApprovals()
  const followup = useSendFollowup()

  // Run ids referenced by this conversation (approvals may sit on any of them).
  const runIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const turn of current.turns) {
      const runId = turn.metadata?.run_id
      if (typeof runId === "string") ids.add(runId)
    }
    if (current.active_run_id) ids.add(current.active_run_id)
    return ids
  }, [current])
  const pendingHere = (approvals.data ?? []).filter((a) => runIds.has(a.run_id))

  const bottomRef = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [current.turns.length, events.length])

  return (
    <>
      {activeRun.data && <RunChatHeader run={activeRun.data} events={events} />}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col-reverse gap-3 p-4">
          <div ref={bottomRef} />
          {/* flex-col-reverse renders DOM order bottom-up: bottomRef pins the
              view to the bottom; each pair lists avatar before user so the
              visual top-down order is user → avatar, oldest first. */}
          {[...current.turns].reverse().map((turn) => (
            <React.Fragment key={turn.id}>
              {turn.role === "assistant" && <Bubble role="avatar" text={turn.content} />}
              {turn.role === "user" && <Bubble role="user" text={turn.content} />}
            </React.Fragment>
          ))}
          {!current.turns.length && (
            <p className="text-center text-sm text-muted-foreground">这条对话还没有内容</p>
          )}
        </div>
      </div>
      {pendingHere.length > 0 && (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pb-2">
          {pendingHere.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} />
          ))}
        </div>
      )}
      <div className="border-t p-3">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            placeholder="继续这条对话…（分身带着全部上下文）"
            pending={followup.isPending}
            onSubmit={(text) =>
              followup.mutate({ taskId: current.id, input: text })
            }
          />
        </div>
      </div>
    </>
  )
}

export function TasksView({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (taskId: string | null) => void
}) {
  const tasks = useTasks()
  const taskList = tasks.data ?? []
  const listTask = taskList.find((t) => t.id === selectedId) ?? null

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {listTask ? (
        <ChatThread key={listTask.id} task={listTask} />
      ) : (
        <EmptyState onSubmitted={(task) => onSelect(task.id)} />
      )}
    </div>
  )
}
