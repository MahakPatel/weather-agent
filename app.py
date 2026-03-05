# app.py
import asyncio
import uuid
import requests
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS so the browser client can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


OPEN_METEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_WEATHER = "https://api.open-meteo.com/v1/forecast"

def stream_message(text):
    """Format message in JSON for SSE streaming."""
    return {
        "id": str(uuid.uuid4()),
        "jsonrpc": "2.0",
        "result": {
            "kind": "message",
            "messageId": str(uuid.uuid4()),
            "role": "agent",
            "parts": [{"kind": "text", "text": text}]
        }
    }

async def get_weather_stream(city: str):
    # Step 1: Searching location
    yield f"data: {stream_message(f'🔎 Searching location for {city}...')}\n\n"
    await asyncio.sleep(1)

    geo = requests.get(OPEN_METEO_GEOCODING, params={"name": city}).json()
    if "results" not in geo:
        yield f"data: {stream_message(f'❌ City {city} not found')}\n\n"
        return

    lat = geo["results"][0]["latitude"]
    lon = geo["results"][0]["longitude"]

    # Step 2: Fetching weather
    yield f"data: {stream_message('🌦 Fetching weather data...')}\n\n"
    await asyncio.sleep(1)

    weather = requests.get(
        OPEN_METEO_WEATHER,
        params={"latitude": lat, "longitude": lon, "current_weather": True}
    ).json()
    if "current_weather" not in weather:
        yield f"data: {stream_message('❌ Weather data unavailable')}\n\n"
        return

    temp = weather["current_weather"]["temperature"]
    wind = weather["current_weather"]["windspeed"]

    # Step 3: Final result
    yield f"data: {stream_message(f'✅ Weather in {city}: {temp}°C, Wind {wind} km/h')}\n\n"

@app.get("/get-weather")
async def get_weather(city: str):
    """SSE endpoint for streaming weather updates."""
    return StreamingResponse(get_weather_stream(city), media_type="text/event-stream")