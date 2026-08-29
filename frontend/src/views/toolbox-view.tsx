import { AgentBindingsPanel } from "@/components/toolbox/agent-bindings-panel"
import { McpPanel } from "@/components/toolbox/mcp-panel"
import { SkillsPanel } from "@/components/toolbox/skills-panel"

export function ToolboxView() {
  return (
    <div className="grid items-start gap-4 p-4 lg:grid-cols-2 xl:grid-cols-3">
      <McpPanel />
      <SkillsPanel />
      <div className="lg:col-span-2 xl:col-span-1">
        <AgentBindingsPanel />
      </div>
    </div>
  )
}
