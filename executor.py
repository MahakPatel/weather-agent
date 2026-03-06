"""A2A AgentExecutor for weather. Uses Open-Meteo as data source; protocol is A2A only."""

import asyncio
import re
import uuid
from datetime import datetime, timezone

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils.message import new_agent_text_message

OPEN_METEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_WEATHER = "https://api.open-meteo.com/v1/forecast"


def _extract_city(query: str) -> str:
    """Extract city name from phrases like 'weather in Dallas' or 'Dallas weather'."""
    query = query.strip()
    if not query:
        return ""
    # "weather in X", "forecast for X", "X weather"
    for pattern in [r"(?:weather|forecast)\s+in\s+(.+)", r"(?:weather|forecast)\s+for\s+(.+)", r"(.+?)\s+weather"]:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return query


class WeatherExecutor(AgentExecutor):
    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        user_query = context.get_user_input().strip()
        task_id = context.task_id or ""
        context_id = context.context_id or ""
        city = _extract_city(user_query) or user_query or "your area"
        artifact_id = str(uuid.uuid4())

        def artifact_chunk(text: str) -> TaskArtifactUpdateEvent:
            return TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=artifact_id,
                    parts=[Part(root=TextPart(text=text))],
                ),
            )

        async def send_intermediate(text: str) -> None:
            """Send a chunk that does not close the stream (SDK treats Message as final)."""
            await event_queue.enqueue_event(artifact_chunk(text))

        async def send_final(text: str) -> None:
            """Send final chunk as Message so the SDK closes the stream."""
            msg = new_agent_text_message(
                text=text,
                task_id=task_id,
                context_id=context_id,
            )
            await event_queue.enqueue_event(msg)

        try:
            # Step 1: Searching location (intermediate – do not use Message or queue closes)
            await send_intermediate(f"🔎 Searching location for {city}...")
            await asyncio.sleep(0.3)

            async with httpx.AsyncClient(timeout=15.0) as client:
                geo_resp = await client.get(
                    OPEN_METEO_GEOCODING, params={"name": city}
                )
                geo = geo_resp.json() if geo_resp.content else {}
                if "results" not in geo or not geo["results"]:
                    await send_final(f"❌ City '{city}' not found")
                    return

                lat = geo["results"][0]["latitude"]
                lon = geo["results"][0]["longitude"]
                resolved_name = geo["results"][0].get("name", city)

                # Step 2: Fetching weather (intermediate)
                await send_intermediate("🌦 Fetching weather data...")
                await asyncio.sleep(0.3)

                weather_resp = await client.get(
                    OPEN_METEO_WEATHER,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": "true",
                    },
                )
                weather = weather_resp.json() if weather_resp.content else {}
                if "current_weather" not in weather:
                    await send_final("❌ Weather data unavailable")
                    return

                temp = weather["current_weather"]["temperature"]
                wind = weather["current_weather"]["windspeed"]

                # Step 3: Final result (Message so stream ends)
                await send_final(
                    f"✅ Weather in {resolved_name}: {temp}°C, Wind {wind} km/h"
                )
        except Exception as e:
            await send_final(f"❌ Error: {e!s}")

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id = context.task_id or ""
        context_id = context.context_id or ""
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.canceled,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
            )
        )
