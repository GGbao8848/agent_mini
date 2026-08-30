import { Badge } from "@/components/ui/badge"
import { STATUS_LABELS, STATUS_STYLES } from "@/lib/format"

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={STATUS_STYLES[status] ?? STATUS_STYLES.created}>
      {STATUS_LABELS[status] ?? status}
    </Badge>
  )
}
