/* 记忆面板: the human's curation surface for long-term memory.
 *
 * Unlike the first (rolled-back) design, entries are NOT dumped into every
 * prompt — retrieval picks the few relevant to each request. So the list can
 * grow without bloating context; the panel is for curation (add / edit /
 * forget), and the agent writes through its `remember` tool. */
import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useMemories, useMemoryActions } from "@/hooks/use-console"
import { fmtDateTime } from "@/lib/format"
import type { Memory } from "@/lib/types"
import { BrainIcon, Loader2Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"

const SOURCE_LABEL: Record<string, string> = { manual: "手动", agent: "分身" }
const SCOPES = [
  { value: "user", label: "用户" },
  { value: "project", label: "项目" },
  { value: "agent", label: "分身" },
  { value: "org", label: "组织" },
]
const TYPES = [
  { value: "fact", label: "事实" },
  { value: "preference", label: "偏好" },
  { value: "decision", label: "决策" },
  { value: "lesson", label: "经验" },
  { value: "constraint", label: "约束" },
  { value: "error_fix", label: "纠错" },
]

function labelOf(options: { value: string; label: string }[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value
}

function MemoryRow({ memory }: { memory: Memory }) {
  const actions = useMemoryActions()
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(memory.content)

  const save = () => {
    const content = draft.trim()
    if (!content) return
    actions.update.mutate({ id: memory.id, content }, { onSuccess: () => setEditing(false) })
  }

  return (
    <div className="group flex flex-col gap-1.5 rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">{labelOf(SCOPES, memory.scope)}</Badge>
        <Badge variant="outline">{labelOf(TYPES, memory.type)}</Badge>
        <span className="rounded bg-muted px-1.5 py-0.5 font-medium text-foreground/70">
          {SOURCE_LABEL[memory.source] ?? memory.source}
        </span>
        <span title={memory.updated_at}>{fmtDateTime(memory.updated_at)}</span>
        <span className="min-w-0 flex-1" />
        <span className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          <Button
            variant="ghost"
            size="icon-sm"
            title="编辑"
            onClick={() => {
              setDraft(memory.content)
              setEditing(true)
            }}
          >
            <PencilIcon />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            title="删除"
            disabled={actions.remove.isPending}
            onClick={() => actions.remove.mutate(memory.id)}
          >
            <Trash2Icon />
          </Button>
        </span>
      </div>
      {editing ? (
        <div className="flex flex-col gap-1.5">
          <Textarea
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="text-sm"
            autoFocus
          />
          <div className="flex justify-end gap-1.5">
            <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
              取消
            </Button>
            <Button
              size="sm"
              disabled={!draft.trim() || actions.update.isPending}
              onClick={save}
            >
              {actions.update.isPending && (
                <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
              )}
              保存
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm leading-relaxed break-words whitespace-pre-wrap">
          {memory.content}
        </p>
      )}
    </div>
  )
}

export function MemoryView() {
  const { data: memories, isLoading } = useMemories()
  const actions = useMemoryActions()
  const [draft, setDraft] = React.useState("")
  const [scope, setScope] = React.useState("user")
  const [type, setType] = React.useState("fact")

  const add = () => {
    const content = draft.trim()
    if (!content) return
    actions.add.mutate({ content, scope, type }, { onSuccess: () => setDraft("") })
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-base font-medium">
          <BrainIcon className="size-4" />
          长期记忆
        </h2>
        <p className="text-xs text-muted-foreground">
          分身只检索与当前问题相关的记忆，不会把整份列表塞进每次对话，所以可以放心积累。
          分身也会用 remember 工具自己记录；删除与修改由你把关。
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Textarea
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="记一条长期记忆，例如：项目统一用 pnpm，不要用 npm…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add()
          }}
        />
        <div className="flex items-center gap-2">
          <Select value={scope} onValueChange={(v) => setScope(v ?? "user")} items={SCOPES}>
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCOPES.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={type} onValueChange={(v) => setType(v ?? "fact")} items={TYPES}>
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="flex-1" />
          <Button size="sm" disabled={!draft.trim() || actions.add.isPending} onClick={add}>
            {actions.add.isPending ? (
              <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
            ) : (
              <PlusIcon data-icon="inline-start" />
            )}
            添加记忆
          </Button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : !memories?.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center">
          <BrainIcon className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            还没有记忆。写下第一条，或让分身在对话里用 remember 记住重要的事。
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {memories.map((m) => (
            <MemoryRow key={m.id} memory={m} />
          ))}
        </div>
      )}
    </div>
  )
}
