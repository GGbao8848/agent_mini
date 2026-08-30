import * as React from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useResolveApproval } from "@/hooks/use-console"
import { fmtTime } from "@/lib/format"
import type { Approval } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, HandIcon, WrenchIcon } from "lucide-react"

function approvalTitle(approval: Approval): string {
  return approval.kind === "task_help"
    ? `求助 · ${approval.agent_id}`
    : `工具审批 · ${approval.tool_name} (${approval.risk_level})`
}

export function ApprovalCard({ approval }: { approval: Approval }) {
  const resolve = useResolveApproval()
  const [note, setNote] = React.useState("")

  const decide = (decision: "approved" | "rejected") =>
    resolve.mutate({
      approvalId: approval.id,
      decision,
      note: note.trim() || null,
    })

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3">
      <p className="text-sm font-medium break-words">
        {approval.question || approval.reason || approvalTitle(approval)}
      </p>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {approval.kind === "task_help" ? <HandIcon className="size-3.5" /> : <WrenchIcon className="size-3.5" />}
        {approvalTitle(approval)} · run {approval.run_id.slice(0, 8)} · {fmtTime(approval.created_at)}
      </p>
      <div className="flex gap-2">
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="给分身的答复（可空）"
        />
        <Button
          size="sm"
          disabled={resolve.isPending}
          onClick={() => decide("approved")}
        >
          <CircleCheckIcon />
          批准
        </Button>
        <Button
          size="sm"
          variant="destructive"
          disabled={resolve.isPending}
          onClick={() => decide("rejected")}
        >
          <CircleXIcon />
          驳回
        </Button>
      </div>
    </div>
  )
}
