import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { KeyRoundIcon, TriangleAlertIcon } from "lucide-react"
import type { ConnState } from "@/hooks/use-console"

const CONN_BADGE: Record<ConnState, { label: string; className: string }> = {
  connecting: {
    label: "连接中…",
    className: "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  live: {
    label: "实时",
    className: "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  },
  offline: {
    label: "已断开",
    className: "border-red-500/30 bg-red-500/15 text-red-700 dark:text-red-400",
  },
}

export function SiteHeader({
  title,
  conn,
  pendingApprovals,
  onOpenTokenDialog,
}: {
  title: string
  conn: ConnState
  pendingApprovals: number
  onOpenTokenDialog: () => void
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b">
      <div className="flex flex-1 items-center gap-2 px-3">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
        <span className="text-sm font-medium">{title}</span>
      </div>
      <div className="flex items-center gap-2 px-3">
        {pendingApprovals > 0 && (
          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400">
            <TriangleAlertIcon />
            {pendingApprovals} 待审批
          </Badge>
        )}
        <Badge variant="outline" className={CONN_BADGE[conn].className}>
          {CONN_BADGE[conn].label}
        </Badge>
        <Button variant="ghost" size="icon" title="控制台令牌" onClick={onOpenTokenDialog}>
          <KeyRoundIcon />
        </Button>
      </div>
    </header>
  )
}
