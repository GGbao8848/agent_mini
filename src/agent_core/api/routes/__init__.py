"""HTTP transport for Agent Core: FastAPI routers."""

from fastapi import APIRouter

from agent_core.api.routes import (
    agents,
    approvals,
    artifacts,
    attachments,
    events,
    mcp,
    runs,
    schedules,
    skills,
    tasks,
    tools,
)

api_router = APIRouter()
api_router.include_router(agents.router)
api_router.include_router(skills.router)
api_router.include_router(tools.router)
api_router.include_router(mcp.router)
api_router.include_router(attachments.router)
api_router.include_router(tasks.router)
api_router.include_router(schedules.router)
api_router.include_router(runs.router)
api_router.include_router(approvals.router)
api_router.include_router(artifacts.router)
api_router.include_router(events.router)

__all__ = ["api_router"]
