import asyncio
import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message


# ----------------------------
# Weather Agent
# ----------------------------
class WeatherAgent:

    async def get_coordinates(self, city: str):
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"

        async with httpx.AsyncClient() as client:
            geo_response = await client.get(
                geo_url,
                params={"name": city, "count": 1},
            )

        geo_data = geo_response.json()

        if "results" not in geo_data:
            return None, None

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        return lat, lon

    async def get_weather(self, lat, lon):

        weather_url = "https://api.open-meteo.com/v1/forecast"

        async with httpx.AsyncClient() as client:
            weather_response = await client.get(
                weather_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": True,
                },
            )

        data = weather_response.json()

        temp = data["current_weather"]["temperature"]
        wind = data["current_weather"]["windspeed"]

        return temp, wind


# ----------------------------
# Agent Executor (Streaming)
# ----------------------------
class WeatherAgentExecutor(AgentExecutor):

    def __init__(self):
        self.agent = WeatherAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue):

        city = context.get_user_input()

        await event_queue.enqueue_event(
            new_agent_text_message("🔍 Fetching city coordinates...")
        )

        await asyncio.sleep(1)

        lat, lon = await self.agent.get_coordinates(city)

        if lat is None:
            await event_queue.enqueue_event(
                new_agent_text_message(f"❌ City '{city}' not found.")
            )
            return

        await event_queue.enqueue_event(
            new_agent_text_message(f"📍 Coordinates found: {lat}, {lon}")
        )

        await asyncio.sleep(1)

        await event_queue.enqueue_event(
            new_agent_text_message("🌦 Fetching weather data...")
        )

        temp, wind = await self.agent.get_weather(lat, lon)

        await asyncio.sleep(1)

        await event_queue.enqueue_event(
            new_agent_text_message(
                f"✅ Weather in {city}: Temperature {temp}°C, Wind {wind} km/h"
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise Exception("Cancel not supported")


# ----------------------------
# Agent Definition
# ----------------------------
skill = AgentSkill(
    id="weather",
    name="Weather Agent",
    description="Returns weather information for a city",
    tags=["weather"],
    examples=["Dallas", "New York", "London"],
)

agent_card = AgentCard(
    name="Weather Agent",
    description="Streaming weather agent using Open-Meteo",
    url="https://your-render-url.onrender.com/",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],
)

request_handler = DefaultRequestHandler(
    agent_executor=WeatherAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)

app = server.build()


# ----------------------------
# Agent Card Endpoint
# ----------------------------
async def get_agent_card(request):
    return JSONResponse(agent_card.dict())


app.routes.append(Route("/agent-card", get_agent_card))