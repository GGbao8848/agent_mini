/* 记忆面板: the human's curation surface for long-term memory.
 *
 * Every entry here is injected into every conversation's system prompt, so
 * the list stays deliberately small and curated — the agent can propose
 * entries via save_memory; editing and deletion are human-only. */
import * as React from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useMemoryActions, useMemories } from "@/hooks/use-console"
import { fmtDateTime } from "@/lib/format"
import { BrainIcon, Loader2Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"

const SOURCE_LABEL: Record<string, string> = {
  manual: "手动",
  agent: "分身",
}

function MemoryRow({ id }: { id: string }) {
  const { data: memories } = useMemories()
  const memory = memories?.find((m) => m.id === id)
  const actions = useMemoryActions()
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(memory?.content ?? "")

  if (!memory) return null

  const save = () => {
    const content = draft.trim()
    if (!content) return
    actions.update.mutate(
      { id: memory.id, content },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <div className="group flex flex-col gap-1.5 rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
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
              {actions.update.isPending && <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />}
              保存
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed break-words">{memory.content}</p>
      )}
    </div>
  )
}

export function MemoryView() {
  const { data: memories, isLoading } = useMemories()
  const actions = useMemoryActions()
  const [draft, setDraft] = React.useState("")

  const add = () => {
    const content = draft.trim()
    if (!content) return
    actions.add.mutate(content, { onSuccess: () => setDraft("") })
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-base font-medium">
          <BrainIcon className="size-4" />
          长期记忆
        </h2>
        <p className="text-xs text-muted-foreground">
          这里的每一条都会注入分身的每次对话。分身也可以通过 save_memory
          工具自己记录；删除与修改由你把关，保持精炼。
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
        <div className="flex justify-end">
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
            还没有记忆。写下第一条，或让分身在对话里用 save_memory 记住重要的事。
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {memories.map((m) => (
            <MemoryRow key={m.id} id={m.id} />
          ))}
        </div>
      )}
    </div>
  )
}
