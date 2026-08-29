import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useAgents, useSkills, useTools, useUpdateAgent } from "@/hooks/use-console"
import { PlusIcon, XIcon } from "lucide-react"

function BindingRow({
  kind,
  values,
  options,
  onAdd,
  onRemove,
}: {
  kind: "工具" | "技能"
  values: string[]
  options: { value: string; label: string }[]
  onAdd: (value: string) => void
  onRemove: (value: string) => void
}) {
  const [selected, setSelected] = React.useState("")

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="w-8 shrink-0 text-xs text-muted-foreground">{kind}</span>
        {values.length === 0 && <span className="text-xs text-muted-foreground">无</span>}
        {values.map((value) => (
          <Badge key={value} variant="secondary" className="gap-1">
            {value}
            <button onClick={() => onRemove(value)} className="hover:text-destructive">
              <XIcon className="size-3" />
              <span className="sr-only">移除 {value}</span>
            </button>
          </Badge>
        ))}
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-8 shrink-0 text-xs text-muted-foreground">添加</span>
        <Select value={selected} onValueChange={(v) => setSelected(v ?? "")}>
          <SelectTrigger size="sm" className="flex-1" disabled={!options.length}>
            <SelectValue placeholder={options.length ? "选择…" : "无可选项"} />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="icon"
          variant="outline"
          disabled={!selected}
          onClick={() => {
            onAdd(selected)
            setSelected("")
          }}
        >
          <PlusIcon />
          <span className="sr-only">添加绑定</span>
        </Button>
      </div>
    </div>
  )
}

export function AgentBindingsPanel() {
  const agents = useAgents()
  const tools = useTools()
  const skills = useSkills()
  const updateAgent = useUpdateAgent()

  const agentList = agents.data ?? []
  const toolOptions = (tools.data ?? []).map((t) => ({ value: t.name, label: t.name }))
  const skillOptions = (skills.data ?? []).map((s) => ({
    value: s.id,
    label: `${s.id} v${s.version}`,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          Agents 工具绑定 <span className="text-xs font-normal text-muted-foreground">（即点即生效）</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {agents.isLoading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : agentList.length === 0 ? (
          <p className="text-sm text-muted-foreground">（无 agent）</p>
        ) : (
          agentList.map((agent) => (
            <div key={agent.id} className="flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{agent.id}</span>
                <span className="text-xs text-muted-foreground">{agent.name}</span>
              </div>
              <BindingRow
                kind="工具"
                values={agent.tools}
                options={toolOptions}
                onAdd={(value) =>
                  updateAgent.mutate({
                    agentId: agent.id,
                    patch: { tools: agent.tools.includes(value) ? agent.tools : [...agent.tools, value] },
                  })
                }
                onRemove={(value) =>
                  updateAgent.mutate({
                    agentId: agent.id,
                    patch: { tools: agent.tools.filter((v) => v !== value) },
                  })
                }
              />
              <BindingRow
                kind="技能"
                values={agent.skills}
                options={skillOptions}
                onAdd={(value) =>
                  updateAgent.mutate({
                    agentId: agent.id,
                    patch: { skills: agent.skills.includes(value) ? agent.skills : [...agent.skills, value] },
                  })
                }
                onRemove={(value) =>
                  updateAgent.mutate({
                    agentId: agent.id,
                    patch: { skills: agent.skills.filter((v) => v !== value) },
                  })
                }
              />
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
