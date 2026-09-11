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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSkillManage, useSkills } from "@/hooks/use-console"
import { PackageIcon, PlusIcon, Trash2Icon } from "lucide-react"

const EMPTY_FORM = { id: "", name: "", version: "0.1.0", description: "", path: "" }

/** Register dialog: point the registry at a skill directory already on the server disk.
 *
 * Installing a *new* skill is the agent's job — it authors the directory and
 * calls `install_skill`. This dialog only covers the case where the directory
 * already exists outside the workspace and just needs a manifest. */
function RegisterSkillDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const skills = useSkillManage()
  const [form, setForm] = React.useState(EMPTY_FORM)
  const [error, setError] = React.useState("")

  const close = () => {
    onOpenChange(false)
    setError("")
    setForm(EMPTY_FORM)
  }

  const submit = () => {
    setError("")
    const payload = {
      id: form.id.trim(),
      name: form.name.trim(),
      version: form.version.trim() || "0.1.0",
      description: form.description.trim(),
      path: form.path.trim(),
    }
    if (!payload.id || !payload.name || !payload.path) {
      setError("id、名称、目录路径必填")
      return
    }
    skills.install.mutate(payload, {
      onSuccess: close,
    })
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>登记技能目录</DialogTitle>
          <DialogDescription>
            登记一个已在服务器磁盘上的技能目录（目录内需有 SKILL.md，+ references/ scripts/ 可选）。
            安装新技能请直接在对话里让分身来做。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="sk-id">id</Label>
              <Input id="sk-id" placeholder="my-skill" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sk-name">名称</Label>
              <Input id="sk-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="sk-version">版本</Label>
              <Input id="sk-version" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sk-desc">描述</Label>
              <Input id="sk-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="sk-path">服务器上的目录路径</Label>
            <Input
              id="sk-path"
              placeholder="/home/user/skills/my-skill（目录内需有 SKILL.md）"
              value={form.path}
              onChange={(e) => setForm({ ...form, path: e.target.value })}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button disabled={skills.install.isPending} onClick={submit}>
              登记
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function SkillsPanel() {
  const skills = useSkills()
  const manage = useSkillManage()
  const [installOpen, setInstallOpen] = React.useState(false)
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const skillList = skills.data ?? []

  // Empty state: tell the user the agent is the install path; the dialog below
  // only covers registering a directory that is already on the server disk.
  if (!skills.isLoading && skillList.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <PackageIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有安装任何技能</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            直接在对话里让分身安装即可：它会把技能目录写好并注册进技能库。
            若技能目录已经放在服务器磁盘上，也可以用下面的按钮直接登记。
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setInstallOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          登记服务器目录路径
        </Button>
        <RegisterSkillDialog open={installOpen} onOpenChange={setInstallOpen} />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Skills 技能（{skillList.length} 个）</h2>
        <Button size="sm" variant="outline" onClick={() => setInstallOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          登记技能目录
        </Button>
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

      <RegisterSkillDialog open={installOpen} onOpenChange={setInstallOpen} />

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
