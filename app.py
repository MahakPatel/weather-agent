"""A2A-only weather agent. Use method message/stream (not message/send) for streaming; POST / with JSON-RPC."""

import os

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication

# Optional: set AUTH_TOKEN (or WEATHER_AGENT_TOKEN) in env to require "Authorization: Bearer <token>" for POST /
REQUIRED_AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "").strip() or os.environ.get("WEATHER_AGENT_TOKEN", "").strip()
# Base URL for agent card (set on Render via RENDER_EXTERNAL_URL, or BASE_URL)
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip() or os.environ.get("BASE_URL", "http://localhost:8000").strip()


class AuthMiddleware:
    """Requires Authorization: Bearer <token> for POST / when REQUIRED_AUTH_TOKEN is set."""

    def __init__(self, app, required_token: str = ""):
        self.app = app
        self.required_token = required_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not self.required_token:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "")
        if method == "GET" and path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            await self.app(scope, receive, send)
            return
        if method != "POST" or path != "/":
            await self.app(scope, receive, send)
            return
        headers = dict((k.decode().lower(), v.decode()) for k, v in scope.get("headers", []))
        auth = headers.get("authorization")
        token = auth[7:].strip() if auth and auth.startswith("Bearer ") else ""
        if token != self.required_token:
            response = JSONResponse(
                {"error": "Unauthorized", "detail": "Missing or invalid Authorization header"},
                status_code=401,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from executor import WeatherExecutor

# Create executor and task store
executor = WeatherExecutor()
task_store = InMemoryTaskStore()
http_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
)

# Define agent card (SDK expects AgentCard model, not a dict)
agent_card = AgentCard(
    name="Weather Agent",
    description="Provides current weather updates with streaming. Ask me about the weather in any city.",
    version="1.0",
    url=BASE_URL.rstrip("/") or "http://localhost:8000",
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="weather",
            name="Weather",
            description="Ask me about the weather in any city.",
            tags=["weather", "forecast"],
        )
    ],
    supports_authenticated_extended_card=False,
)

# Create server – pass http_handler (wraps executor + task_store)
server = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=http_handler,
)

# Build the Starlette ASGI app, then auth (if token set), then CORS
app = server.build()
app = AuthMiddleware(app, REQUIRED_AUTH_TOKEN)
app = CORSMiddleware(
    app=app,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)