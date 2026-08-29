import { artifactUrl } from "@/lib/api"
import { fmtSize } from "@/lib/format"
import type { Artifact } from "@/lib/types"
import { FileIcon } from "lucide-react"

const IMAGE_RE = /\.(png|jpe?g|webp|gif)$/i

function ArtifactRow({ runId, artifact }: { runId: string; artifact: Artifact }) {
  const url = artifactUrl(runId, artifact.path)
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
          {artifact.path} · {fmtSize(artifact.size)}
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
      <span className="ml-auto shrink-0 text-xs text-muted-foreground">{fmtSize(artifact.size)}</span>
    </a>
  )
}

export function ArtifactsPanel({ runId, artifacts }: { runId: string; artifacts: Artifact[] }) {
  if (!artifacts.length) {
    return <p className="p-2 text-sm text-muted-foreground">（无）</p>
  }
  return (
    <div className="flex flex-col gap-2">
      {artifacts.map((artifact) => (
        <ArtifactRow key={artifact.path} runId={runId} artifact={artifact} />
      ))}
    </div>
  )
}
