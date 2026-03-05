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
# Weather Agent Logic
# ----------------------------
class WeatherAgent:

    async def get_weather(self, city: str):

        try:
            geo_url = "https://geocoding-api.open-meteo.com/v1/search"

            async with httpx.AsyncClient(timeout=10) as client:
                geo = await client.get(
                    geo_url,
                    params={"name": city, "count": 1}
                )

            geo_data = geo.json()

            if "results" not in geo_data or len(geo_data["results"]) == 0:
                return f"City '{city}' not found."

            lat = geo_data["results"][0]["latitude"]
            lon = geo_data["results"][0]["longitude"]

            weather_url = "https://api.open-meteo.com/v1/forecast"

            async with httpx.AsyncClient(timeout=10) as client:
                weather = await client.get(
                    weather_url,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": True
                    }
                )

            weather_data = weather.json()

            if "current_weather" not in weather_data:
                return f"Weather data unavailable for '{city}'."

            temp = weather_data["current_weather"]["temperature"]
            wind = weather_data["current_weather"]["windspeed"]

            return f"Weather in {city}: {temp}°C, Wind {wind} km/h"

        except Exception as e:
            print("Weather API error:", str(e))
            return f"Weather service temporarily unavailable for '{city}'."


# ----------------------------
# Agent Executor
# ----------------------------
class WeatherAgentExecutor(AgentExecutor):

    def __init__(self):
        self.agent = WeatherAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue):

        user_input = context.get_user_input()

        result = await self.agent.get_weather(user_input)

        await event_queue.enqueue_event(
            new_agent_text_message(result)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise Exception("Cancel not supported")


# ----------------------------
# Define Agent Skill
# ----------------------------
skill = AgentSkill(
    id="weather",
    name="Weather Agent",
    description="Returns weather for a city",
    tags=["weather"],
    examples=["Dallas", "Pomona", "New York"]
)


# ----------------------------
# Agent Card
# ----------------------------
agent_card = AgentCard(
    name="Weather Agent",
    description="Free weather agent using Open-Meteo",
    url="https://weather-agent-k31a.onrender.com",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill]
)


# ----------------------------
# Request Handler
# ----------------------------
request_handler = DefaultRequestHandler(
    agent_executor=WeatherAgentExecutor(),
    task_store=InMemoryTaskStore(),
)


# ----------------------------
# Build A2A Server
# ----------------------------
server = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler
)

app = server.build()


# ----------------------------
# Weather Endpoint
# ----------------------------
async def get_weather(request):

    city = request.query_params.get("city")

    if not city:
        return JSONResponse({"error": "city query param required"})

    agent = WeatherAgent()

    result = await agent.get_weather(city)

    return JSONResponse({"result": result})


# ----------------------------
# Agent Card Endpoint
# ----------------------------
async def get_agent_card(request):
    return JSONResponse(agent_card.dict())


# ----------------------------
# Register Routes
# ----------------------------
app.routes.append(Route("/get-weather", get_weather))
app.routes.append(Route("/agent-card", get_agent_card))