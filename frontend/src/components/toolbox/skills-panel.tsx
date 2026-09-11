import * as React from "react"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { useSkillManage, useSkills } from "@/hooks/use-console"
import { PackageIcon, Trash2Icon } from "lucide-react"

/** The skills page: list, enable/disable, delete.
 *
 * Installing a skill has no console control at all — the agent authors the
 * skill directory and registers it through its `install_skill` tool (behind
 * approval). This page only shows and manages what is already registered.
 */
export function SkillsPanel() {
  const skills = useSkills()
  const manage = useSkillManage()
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const skillList = skills.data ?? []

  if (!skills.isLoading && skillList.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <PackageIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有安装任何技能</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            直接在对话里让分身安装即可：它会写好技能目录并注册进技能库，安装动作会请你确认。
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
        安装新技能：在对话里描述你要的能力，分身会写技能目录并注册（安装动作需你确认）。
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
              <div className="mt-auto flex items-center justify-between pt-1">
                <span
                  className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground"
                  title={skill.enabled ? "已启用：注入分身的技能清单" : "已停用：对分身不可见"}
                >
                  <Switch
                    size="sm"
                    checked={skill.enabled}
                    disabled={manage.update.isPending}
                    onCheckedChange={(checked) =>
                      manage.update.mutate({ id: skill.id, enabled: checked === true })
                    }
                  />
                  启用
                </span>
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-destructive"
                  onClick={() => setRemovingId(skill.id)}
                >
                  <Trash2Icon data-icon="inline-start" />
                  删除
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <AlertDialog open={removingId !== null} onOpenChange={(isOpen) => !isOpen && setRemovingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除技能 {removingId}？</AlertDialogTitle>
            <AlertDialogDescription>
              技能目录仍保留在服务器磁盘上，但不再对 agent 生效。
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
    </div>
  )
}
