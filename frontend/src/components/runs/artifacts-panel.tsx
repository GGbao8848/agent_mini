import { artifactUrl } from "@/lib/api"
import { fmtSize, fmtTime } from "@/lib/format"
import type { Artifact } from "@/lib/types"
import { FileIcon } from "lucide-react"

const IMAGE_RE = /\.(png|jpe?g|webp|gif)$/i

function ArtifactRow({ runId, artifact }: { runId: string; artifact: Artifact }) {
  // Aggregated artifacts carry the run that produced them; the panel's runId
  // is the fallback for per-run queries.
  const url = artifactUrl(artifact.run_id ?? runId, artifact.path)
  const time = artifact.mtime ? fmtTime(artifact.mtime) : "—"
  if (IMAGE_RE.test(artifact.path)) {
    return (
      <div className="flex flex-col gap-1">
        <a href={url} target="_blank" rel="noreferrer">
          <img
            src={url}
            alt={artifact.path}
            loading="lazy"
            className="max-h-48 w-full rounded-lg border object-contain"
          />
        </a>
        <p className="truncate text-xs text-muted-foreground" title={artifact.path}>
          {artifact.path} · {fmtSize(artifact.size)} · {time}
        </p>
      </div>
    )
  }
  return (
    <a
      href={url}
      download
      className="flex items-center gap-2 rounded-lg border p-2 text-sm transition-colors hover:bg-muted"
    >
      <FileIcon className="size-4 shrink-0 text-muted-foreground" />
      <span className="truncate" title={artifact.path}>
        {artifact.path}
      </span>
      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
        {fmtSize(artifact.size)} · {time}
      </span>
    </a>
  )
}

/** Group the conversation's artifacts by the run that produced them, so the
 * panel reads "this turn made these files" instead of one flat list. Runs that
 * made nothing are omitted; a single run's rows render ungrouped. */
function grouped(artifacts: Artifact[]): { runId: string; items: Artifact[] }[] {
  const order: string[] = []
  const byRun = new Map<string, Artifact[]>()
  for (const artifact of artifacts) {
    const runId = artifact.run_id ?? ""
    if (!byRun.has(runId)) {
      byRun.set(runId, [])
      order.push(runId)
    }
    byRun.get(runId)!.push(artifact)
  }
  return order.map((runId) => ({ runId, items: byRun.get(runId)! }))
}

export function ArtifactsPanel({ runId, artifacts }: { runId: string; artifacts: Artifact[] }) {
  if (!artifacts.length) {
    return <p className="p-2 text-sm text-muted-foreground">（无）</p>
  }
  const groups = grouped(artifacts)
  if (groups.length <= 1) {
    return (
      <div className="flex flex-col gap-2">
        {groups[0]?.items.map((artifact) => (
          <ArtifactRow key={artifact.path} runId={runId} artifact={artifact} />
        ))}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group, index) => (
        <div key={group.runId} className="flex flex-col gap-1.5">
          <p className="text-[11px] font-medium text-muted-foreground">
            第 {index + 1} 轮 · {group.runId.slice(0, 8)}
          </p>
          <div className="flex flex-col gap-2">
            {group.items.map((artifact) => (
              <ArtifactRow key={artifact.path} runId={runId} artifact={artifact} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
