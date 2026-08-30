import * as React from "react"
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
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useSkillManage, useSkills } from "@/hooks/use-console"
import { PlusIcon, Trash2Icon } from "lucide-react"

const EMPTY_FORM = { id: "", name: "", version: "0.1.0", description: "", path: "" }

function InstallSkillDialog() {
  const skills = useSkillManage()
  const [open, setOpen] = React.useState(false)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const [error, setError] = React.useState("")

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
      onSuccess: () => {
        setForm(EMPTY_FORM)
        setOpen(false)
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PlusIcon data-icon="inline-start" />
        安装技能
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>安装技能</DialogTitle>
          <DialogDescription>
            技能目录约定：目录内放 SKILL.md（+ references/ scripts/）。文件先放到服务器磁盘，再在这里登记。
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
        </div>
        <DialogFooter>
          <Button disabled={skills.install.isPending} onClick={submit}>
            安装
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function SkillsPanel() {
  const skills = useSkills()
  const manage = useSkillManage()
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const skillList = skills.data ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">Skills 技能</CardTitle>
        <InstallSkillDialog />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {skills.isLoading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : skillList.length === 0 ? (
          <p className="text-sm text-muted-foreground">（尚未安装任何技能）</p>
        ) : (
          skillList.map((skill) => (
            <div key={skill.id} className="flex flex-col gap-1 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{skill.name}</span>
                <Badge variant="secondary">v{skill.version}</Badge>
                <Button
                  size="xs"
                  variant="ghost"
                  className="ml-auto text-destructive"
                  onClick={() => setRemovingId(skill.id)}
                >
                  <Trash2Icon data-icon="inline-start" />
                  删除
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">{skill.description || "无描述"}</p>
              <p className="truncate text-xs text-muted-foreground">
                路径：{skill.path || "—"} · id: {skill.id}
              </p>
            </div>
          ))
        )}
      </CardContent>

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
    </Card>
  )
}
