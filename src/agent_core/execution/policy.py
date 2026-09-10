"""Execution policy (R24): the explicit answers to "what may run_code touch?".

``sandbox="host"`` vs ``"podman"`` was a single boolean-ish switch, and the
container's network mode was hard-coded to ``host`` inside the argv builder.
Nothing could state, or check, the actual execution envelope:

    which files?   which network?   which env?   how long?   how much CPU/RAM?

:class:`ExecutionPolicy` is that statement. It is derived from settings and is
the single description used by the run_code argv builder, the console, and the
acceptance report — so the documented envelope and the enforced one cannot
drift. It is deliberately honest about limits: destination-level network
filtering is *not* enforced under ``host`` networking, and the policy says so
rather than implying a boundary it does not have.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agent_core.config.settings import Settings


class ExecutionMode(StrEnum):
    """Backend that runs a command."""

    HOST = "host"
    """Full-trust: runs on the host with the agent venv, no filesystem isolation."""

    PODMAN = "podman"
    """Rootless container: only the task root (and read-only skills) are mounted."""


class NetworkMode(StrEnum):
    HOST = "host"
    """Share the host netstack — unrestricted outbound, required for LAN services."""

    PRIVATE = "private"
    """Container-private netns (slirp4netns/pasta): outbound only, no LAN exposure."""

    NONE = "none"
    """No networking at all."""


class FilesystemPolicy(BaseModel):
    readable: list[str] = Field(default_factory=list)
    writable: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)
    isolated: bool = False
    """True when the backend confines the filesystem (podman); False = host."""


class NetworkPolicy(BaseModel):
    mode: NetworkMode = NetworkMode.HOST
    allow: list[str] = Field(default_factory=list)
    """Intended destinations (host:port). Documentation under ``host`` mode."""
    enforced: bool = False
    """True when the backend can actually filter destinations (never under host)."""
    note: str = ""


class EnvPolicy(BaseModel):
    forwarded: list[str] = Field(default_factory=list)
    """Environment variable names passed into the sandbox (never secrets by default)."""
    host_secrets_visible: bool = False
    """True for the host backend, where the process inherits the full environment."""


class ResourcePolicy(BaseModel):
    memory_mb: int
    cpus: float
    pids_limit: int
    timeout_seconds: float
    timeout_max_seconds: float


class ExecutionPolicy(BaseModel):
    """The complete execution envelope for ``run_code`` (R24)."""

    mode: ExecutionMode
    sandbox_image: str | None = None
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    env: EnvPolicy
    resources: ResourcePolicy

    def summary(self) -> dict[str, str]:
        """One-line-per-question answers, for the console and reports."""
        return {
            "能访问哪些文件": (
                "仅任务目录（容器内 /work）+ 只读技能 /skills"
                if self.filesystem.isolated
                else "宿主机全部文件（无隔离）"
            ),
            "能访问哪些网络": {
                NetworkMode.HOST: "共享宿主网络，可访问任意地址（含内网/本机端口）",
                NetworkMode.PRIVATE: "容器私有网络，仅可主动出站",
                NetworkMode.NONE: "无网络",
            }[self.network.mode],
            "能继承哪些环境变量": (
                "宿主机全部环境变量（含密钥）"
                if self.env.host_secrets_visible
                else f"仅白名单：{', '.join(self.env.forwarded) or '（无）'}"
            ),
            "最长执行时间": f"{int(self.resources.timeout_seconds)}s（单次上限 "
            f"{int(self.resources.timeout_max_seconds)}s）",
            "资源上限": (
                f"内存 {self.resources.memory_mb}MB / CPU {self.resources.cpus} / "
                f"进程 {self.resources.pids_limit}"
                if self.filesystem.isolated
                else "无（沿用宿主机）"
            ),
        }


# Variables forwarded into the container by default (pip / proxies). Kept in one
# place so the argv builder and the policy description cannot disagree.
DEFAULT_FORWARDED_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
)

# run_code's own hard cap and default, mirrored here for the description.
RUN_CODE_MAX_TIMEOUT = 900.0
RUN_CODE_DEFAULT_TIMEOUT = 300.0


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def build_execution_policy(settings: Settings) -> ExecutionPolicy:
    """Derive the execution policy from settings (pure)."""
    if settings.sandbox == "podman":
        return _podman_policy(settings)
    return _host_policy(settings)


def _host_policy(settings: Settings) -> ExecutionPolicy:
    return ExecutionPolicy(
        mode=ExecutionMode.HOST,
        sandbox_image=None,
        filesystem=FilesystemPolicy(
            readable=["<host>:*"],
            writable=["<host>:*"],
            denied=[],
            isolated=False,
        ),
        network=NetworkPolicy(
            mode=NetworkMode.HOST,
            allow=[],
            enforced=False,
            note="host 模式：命令直接使用宿主网络栈，无法限制目标地址",
        ),
        env=EnvPolicy(forwarded=["<host> 全部"], host_secrets_visible=True),
        resources=ResourcePolicy(
            memory_mb=0,
            cpus=0.0,
            pids_limit=0,
            timeout_seconds=RUN_CODE_DEFAULT_TIMEOUT,
            timeout_max_seconds=RUN_CODE_MAX_TIMEOUT,
        ),
    )


def _podman_policy(settings: Settings) -> ExecutionPolicy:
    forwarded = list(DEFAULT_FORWARDED_ENV)
    for name in _split(settings.sandbox_env_allow):
        if name not in forwarded:
            forwarded.append(name)
    network_mode = NetworkMode(settings.sandbox_network)
    allow = _split(settings.sandbox_network_allow)
    enforced = network_mode is NetworkMode.NONE
    note = {
        NetworkMode.HOST: (
            "共享宿主网络：可访问内网/本机任意端口，无法按地址过滤。"
            "如需严格限制请设 sandbox_network=private 并配合外部防火墙。"
        ),
        NetworkMode.PRIVATE: (
            "容器私有网络：仅主动出站；目标地址过滤需在容器外实施，agent-core 不代管"
        ),
        NetworkMode.NONE: "无网络（目标地址过滤无意义）",
    }[network_mode]
    return ExecutionPolicy(
        mode=ExecutionMode.PODMAN,
        sandbox_image=settings.sandbox_image,
        filesystem=FilesystemPolicy(
            readable=["/work（任务目录）", "/skills/<id>（只读）", "/root/.cache/pip（共享缓存）"],
            writable=["/work"],
            denied=["/inputs 写入", "/skills 写入"],
            isolated=True,
        ),
        network=NetworkPolicy(
            mode=network_mode, allow=allow, enforced=enforced, note=note
        ),
        env=EnvPolicy(forwarded=forwarded, host_secrets_visible=False),
        resources=ResourcePolicy(
            memory_mb=settings.sandbox_memory_mb,
            cpus=settings.sandbox_cpus,
            pids_limit=settings.sandbox_pids_limit,
            timeout_seconds=RUN_CODE_DEFAULT_TIMEOUT,
            timeout_max_seconds=RUN_CODE_MAX_TIMEOUT,
        ),
    )
