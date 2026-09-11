import { Badge } from "@/components/ui/badge"
import { useSkills } from "@/hooks/use-console"
import { PackageIcon } from "lucide-react"

/** The skills page: a read-only view of the skills directory.
 *
 * A skill is a directory under `<workspace>/skills` — the single source of
 * truth. The agent adds, edits, and deletes skills with its ordinary file
 * tools (ask it in the conversation); there is no console control here, because
 * a console write would be reverted by the next directory sync.
 */
export function SkillsPanel() {
  const skills = useSkills()
  const skillList = skills.data ?? []

  if (!skills.isLoading && skillList.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <PackageIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有任何技能</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            技能就是 <code className="text-xs">skills/</code> 目录下的一个普通文件夹。
            直接在对话里让分身写一个即可——它会建目录、写 SKILL.md（YAML frontmatter 含
            name/description），下次运行生效。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Skills 技能（{skillList.length} 个）</h2>
      </div>

      <p className="text-xs text-muted-foreground">
        技能是 <code className="text-xs">skills/</code> 目录下的文件夹，分身用文件工具增删改。
        在对话里说“加一个 XX 技能”即可；这里只读展示。
      </p>

      {skills.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {skillList.map((skill) => (
            <div key={skill.id} className="flex h-full flex-col gap-2 rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium" title={skill.name}>
                  {skill.name}
                </span>
                <Badge variant="secondary" className="shrink-0">
                  v{skill.version}
                </Badge>
              </div>
              <p
                className="line-clamp-2 min-h-8 text-xs text-muted-foreground"
                title={skill.description || "无描述"}
              >
                {skill.description || "无描述"}
              </p>
              <p className="truncate text-xs text-muted-foreground" title={`id: ${skill.id}`}>
                id: {skill.id}
              </p>
              {skill.path && (
                <p className="truncate text-xs text-muted-foreground" title={skill.path}>
                  {skill.path}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
