import * as React from "react"
import { ApprovalCard } from "@/components/runs/approval-card"
import { RunChatHeader } from "@/components/runs/run-detail"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  useAgents,
  useApprovals,
  useRun,
  useRunEvents,
  useRuns,
  useSendFollowup,
  useSubmitTask,
} from "@/hooks/use-console"
import { STATUS_LABELS } from "@/lib/format"
import { threadKey, threadRuns } from "@/lib/runs"
import type { Run } from "@/lib/types"
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
  onSubmit: (agentId: string, text: string) => void
}) {
  const agents = useAgents()
  const [agentId, setAgentId] = React.useState("")
  const agentList = agents.data ?? []

  React.useEffect(() => {
    if (!agentId && agentList.length) {
      const preferred = agentList.find((a) => a.id === "avatar")
      setAgentId((preferred ?? agentList[0]).id)
    }
  }, [agentList, agentId])

  return (
    <Composer
      placeholder="给分身派个任务，例如：把画册的冬天板块加两张图…"
      pending={pending || !agentId}
      onSubmit={(text) => onSubmit(agentId, text)}
    >
      <Select value={agentId} onValueChange={(v) => setAgentId(v ?? "")}>
        <SelectTrigger className="w-full" disabled={!agentList.length}>
          <SelectValue placeholder={agents.isLoading ? "加载中…" : "选择分身"} />
        </SelectTrigger>
        <SelectContent>
          {agentList.map((agent) => (
            <SelectItem key={agent.id} value={agent.id}>
              {agent.id}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Composer>
  )
}

function EmptyState({
  onSubmitted,
}: {
  onSubmitted: (run: Run) => void
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
          onSubmit={(agentId, text) =>
            submit.mutate({ agentId, input: text }, { onSuccess: onSubmitted })
          }
        />
      </div>
    </div>
  )
}

function ChatThread({
  initialRun,
  runs,
  onClose,
  onSwitch,
}: {
  initialRun: Run
  runs: Run[]
  onClose: () => void
  onSwitch: (runId: string) => void
}) {
  const { data: fresh } = useRun(initialRun.id)
  const run = fresh ?? initialRun
  const events = useRunEvents(run.id, run.status)
  const approvals = useApprovals()
  const followup = useSendFollowup()

  const chain = threadRuns(runs, run)
  const display = chain.length ? chain : [run]
  const chainIds = new Set(display.map((r) => r.id))
  const pendingHere = (approvals.data ?? []).filter((a) => chainIds.has(a.run_id))

  const bottomRef = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [display.length, events.length])

  return (
    <>
      <RunChatHeader run={run} events={events} onNewTask={onClose} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col-reverse gap-3 p-4">
          <div ref={bottomRef} />
          {/* flex-col-reverse renders DOM order bottom-up: bottomRef pins the
              view to the bottom; each pair lists avatar before user so the
              visual top-down order is user → avatar, oldest pair first. */}
          {[...display].reverse().map((r) => (
            <React.Fragment key={r.id}>
              <Bubble
                role="avatar"
                text={
                  r.output
                    ? String(r.output)
                    : `（${STATUS_LABELS[r.status] ?? r.status}${r.error ? `：${r.error}` : ""}）`
                }
              />
              <Bubble role="user" text={r.input || "（无文本）"} />
            </React.Fragment>
          ))}
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
              followup.mutate(
                { runId: run.id, input: text },
                { onSuccess: (next) => onSwitch(next.id) },
              )
            }
          />
        </div>
      </div>
    </>
  )
}

export function RunsView({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (runId: string | null) => void
}) {
  const runs = useRuns()
  const runList = runs.data ?? []
  const listRun = runList.find((r) => r.id === selectedId) ?? null

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {listRun ? (
        <ChatThread
          key={threadKey(listRun)}
          initialRun={listRun}
          runs={runList}
          onClose={() => onSelect(null)}
          onSwitch={onSelect}
        />
      ) : (
        <EmptyState onSubmitted={(run) => onSelect(run.id)} />
      )}
    </div>
  )
}
