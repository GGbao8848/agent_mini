/* MCP config normalization — same contract the old console enforced:
 * 1. standard client config {mcpServers: {name: {command|url, args, env, headers}}}
 * 2. array of our definitions
 * 3. single our-definition object (id/name/transport/endpoint/...) */

export interface McpServerPayload {
  id: string
  name: string
  transport: string
  endpoint: string
  description: string
  auth_ref?: string | null
  metadata: Record<string, unknown>
}

type ConvertResult = { server: McpServerPayload } | { error: string }

function convertStdEntry(key: string, cfg: Record<string, unknown>): ConvertResult {
  if (!cfg || typeof cfg !== "object") {
    return { error: `mcpServers.${key} 不是对象` }
  }
  const metadata: Record<string, unknown> = {}
  if (cfg.env && typeof cfg.env === "object") metadata.env = cfg.env
  if (cfg.headers && typeof cfg.headers === "object") metadata.headers = cfg.headers

  const asRecord = cfg as {
    id?: string
    name?: string
    command?: string
    args?: string[]
    url?: string
    description?: string
  }
  if (asRecord.command) {
    return {
      server: {
        id: asRecord.id || key,
        name: asRecord.name || key,
        transport: "stdio",
        endpoint: [asRecord.command, ...(asRecord.args || [])].join(" "),
        description: asRecord.description || "",
        metadata,
      },
    }
  }
  if (asRecord.url) {
    return {
      server: {
        id: asRecord.id || key,
        name: asRecord.name || key,
        transport: "streamable_http",
        endpoint: asRecord.url,
        description: asRecord.description || "",
        metadata,
      },
    }
  }
  return { error: `mcpServers.${key}：需要 command（stdio）或 url（http/sse）字段` }
}

export function normalizeMcpConfig(parsed: unknown): { servers: McpServerPayload[] } | { error: string } {
  if (Array.isArray(parsed)) {
    const servers: McpServerPayload[] = []
    for (const item of parsed) {
      const key = String((item as { id?: string; name?: string })?.id ?? "mcp-server")
      const converted = convertStdEntry(key, item as Record<string, unknown>)
      if ("error" in converted) return converted
      servers.push(converted.server)
    }
    return { servers }
  }
  if (parsed && typeof parsed === "object" && "mcpServers" in parsed) {
    const entries = (parsed as { mcpServers: Record<string, unknown> }).mcpServers
    const servers: McpServerPayload[] = []
    for (const [key, cfg] of Object.entries(entries)) {
      const converted = convertStdEntry(key, cfg as Record<string, unknown>)
      if ("error" in converted) return converted
      servers.push(converted.server)
    }
    return { servers }
  }
  if (parsed && typeof parsed === "object") {
    const obj = parsed as { id?: string; name?: string; command?: string; url?: string }
    const key = obj.id || obj.name || "mcp-server"
    if (obj.id || obj.command || obj.url) {
      const converted = convertStdEntry(key, parsed as Record<string, unknown>)
      if ("error" in converted) return converted
      return { servers: [converted.server] }
    }
  }
  return { error: "无法识别的格式：支持标准 {mcpServers:{…}} 配置，或包含 id/name/transport/endpoint 的定义" }
}

export const MCP_JSON_TEMPLATE = `{
  "id": "demo",
  "name": "Demo MCP",
  "transport": "streamable_http",
  "endpoint": "http://127.0.0.1:8931/mcp",
  "description": "通过 JSON 粘贴注册的 MCP 服务器"
}

// 也支持标准 mcpServers 配置（Claude Desktop / Cherry Studio 同款）：
// { "mcpServers": { "fs": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fs"] } } }`

export function validateServerPayload(payload: McpServerPayload): string | null {
  if (!payload.id || !payload.name) return `缺少必填字段 id / name（收到：${JSON.stringify(Object.keys(payload))}）`
  if (!["streamable_http", "stdio"].includes(payload.transport)) return `${payload.id}: transport 必须是 streamable_http 或 stdio`
  if (!payload.endpoint) return `${payload.id}: endpoint 必填`
  return null
}
