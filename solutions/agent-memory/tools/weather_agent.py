"""
# Weather Forecaster Strands Agent

A demonstration of using Strands Agents' http_request tool to get weather information from the National Weather Service API.

## What This Example Shows

This example demonstrates:
- Creating an agent with HTTP capabilities
- Making requests to the National Weather Service API
- Processing weather data from a public API
- Handling multi-step API flows (get coordinates, then forecast)
- Error handling in HTTP requests

## Usage Examples

Basic usage:
```
python weather_forecaster.py
```

Import in your code:
```python
from examples.basic.weather_forecaster import weather_agent

# Make a direct weather request for a location
response = weather_agent("What's the weather like in Seattle?")
print(response["message"]["content"][0]["text"])

# Or use the tool directly with coordinates
forecast = weather_agent.tool.http_request(
    method="GET",
    url="https://api.weather.gov/points/47.6062,-122.3321"
)
```

## National Weather Service API

This example uses the free National Weather Service API:
- No API key required
- Production-ready and reliable
- Provides forecasts for the United States
- Documentation: https://www.weather.gov/documentation/services-web-api

## Core HTTP Request Concepts

Strands Agents' http_request tool provides:

1. **Multiple HTTP Methods**:
   - GET: Retrieve data from APIs
   - POST: Send data to APIs
   - PUT, DELETE: Modify resources

2. **Response Handling**:
   - JSON parsing
   - Status code checking
   - Error management

3. **Natural Language API Access**:
   - "What's the weather like in Chicago?"
   - "Will it rain tomorrow in Miami?"
   - "Get the forecast for San Francisco"
"""

from strands import Agent, tool
from strands_tools import http_request

# Define a weather-focused system prompt
WEATHER_SYSTEM_PROMPT = """You are a weather assistant with HTTP capabilities. You can:

1. Make HTTP requests to the National Weather Service API
2. Process and display weather forecast data
3. Provide weather information for locations in the United States

When retrieving weather information:
1. First get the coordinates or grid information using https://api.weather.gov/points/{latitude},{longitude} or https://api.weather.gov/points/{zipcode}
2. Then use the returned forecast URL to get the actual forecast

When displaying responses:
- Format weather data in a human-readable way
- Highlight important information like temperature, precipitation, and alerts
- Handle errors appropriately
- Convert technical terms to user-friendly language

Always explain the weather conditions clearly and provide context for the forecast.
"""

@tool()
def weather_agent(prompt: str):
    weather_agent =  Agent(
        system_prompt=WEATHER_SYSTEM_PROMPT,
        tools=[http_request],  # Explicitly enable http_request tool
    )
    resp = weather_agent(prompt)
    return str(resp)