import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

# ----------------------------
# Define the Weather Agent
# ----------------------------
class WeatherAgent:
    """Weather Agent using Open-Meteo (free API)."""

    async def get_weather(self, city: str) -> str:
        # Step 1: Get latitude and longitude from city name
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        async with httpx.AsyncClient() as client:
            geo_response = await client.get(geo_url, params={"name": city, "count": 1})
        geo_data = geo_response.json()
        if "results" not in geo_data:
            return f"City '{city}' not found."

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        # Step 2: Fetch weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        async with httpx.AsyncClient() as client:
            weather_response = await client.get(
                weather_url,
                params={"latitude": lat, "longitude": lon, "current_weather": True},
            )
        weather_data = weather_response.json()
        temp = weather_data["current_weather"]["temperature"]
        wind = weather_data["current_weather"]["windspeed"]

        return f"Weather in {city}: Temperature {temp}°C, Wind speed {wind} km/h"

# ----------------------------
# Define the Agent Executor
# ----------------------------
class WeatherAgentExecutor(AgentExecutor):
    """Executor for Weather Agent."""

    def __init__(self):
        self.agent = WeatherAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        user_input = context.get_user_input()
        result = await self.agent.get_weather(user_input)
        await event_queue.enqueue_event(new_agent_text_message(result))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise Exception("cancel not supported")

# ----------------------------
# Agent Skill & Card
# ----------------------------
skill = AgentSkill(
    id="weather",
    name="Weather Agent",
    description="Returns weather information for a city",
    tags=["weather"],
    examples=["Dallas weather", "weather in New York"],
)

agent_card = AgentCard(
    name="Weather Agent",
    description="Free weather agent using Open-Meteo",
    url="http://localhost:9999/",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],
)

# ----------------------------
# Request Handler
# ----------------------------
request_handler = DefaultRequestHandler(
    agent_executor=WeatherAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

# ----------------------------
# Build A2AStarletteApplication
# ----------------------------
server = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)

# ----------------------------
# Top-level ASGI app (Render requires this)
# ----------------------------
app = server.build()

# ----------------------------
# /agent-card endpoint
# ----------------------------
async def get_agent_card(request: Request):
    return JSONResponse(agent_card.dict())

app.routes.append(Route("/agent-card", get_agent_card))

# ----------------------------
# /get-weather?city=CityName endpoint
# ----------------------------
async def get_weather(request: Request):
    city = request.query_params.get("city")
    if not city:
        return JSONResponse({"error": "Please provide a city"}, status_code=400)

    agent = WeatherAgent()
    weather_info = await agent.get_weather(city)
    return JSONResponse({"weather": weather_info})

app.routes.append(Route("/get-weather", get_weather))

# ----------------------------
# NOTE: Remove uvicorn.run() entirely
# Render will start Uvicorn with:
# uvicorn __main__:app --host 0.0.0.0 --port $PORT
# ----------------------------