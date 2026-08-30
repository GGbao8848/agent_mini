import { SkillsPanel } from "@/components/toolbox/skills-panel"

export function SkillsView() {
  return (
    <div className="grid items-start gap-4 p-4 lg:grid-cols-2 xl:grid-cols-3">
      <div className="lg:col-span-2 xl:col-span-1">
        <SkillsPanel />
      </div>
    </div>
  )
}
