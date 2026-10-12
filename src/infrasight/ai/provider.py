from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AIError(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status
        super().__init__(code)


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=128)
    arguments: str = Field(max_length=12000)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=256)
    type: str = "function"
    function: FunctionCall


class Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["assistant"] = "assistant"
    content: str | None = Field(default=None, max_length=12000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=3)


class LLMProvider(Protocol):
    async def complete(
        self, messages: list[dict], tools: list[dict], choice: str
    ) -> Completion: ...


class GroqProvider:
    """Groq chat completions; only local function tools are ever supplied."""

    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    async def complete(self, messages, tools, choice):
        if not self.settings.groq_api_key:
            raise AIError("AI_NOT_CONFIGURED", 503)
        payload = {
            "model": self.settings.groq_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 800,
        }
        if tools:
            payload.update(tools=tools, tool_choice=choice, parallel_tool_calls=False)
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.groq_timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": "Bearer " + self.settings.groq_api_key.get_secret_value()
                    },
                    json=payload,
                )
            if response.status_code == 429:
                raise AIError("AI_RATE_LIMITED", 429)
            if response.status_code in (401, 403):
                raise AIError("AI_PROVIDER_CONFIGURATION", 503)
            if response.status_code >= 500:
                raise AIError("AI_PROVIDER_UNAVAILABLE", 503)
            if response.status_code != 200:
                raise AIError("AI_PROVIDER_ERROR")
            if len(response.content) > 100000:
                raise AIError("AI_PROVIDER_INVALID_RESPONSE")
            data = response.json()
            return Completion.model_validate(data["choices"][0]["message"])
        except httpx.TimeoutException as exc:
            raise AIError("AI_PROVIDER_TIMEOUT", 504) from exc
        except httpx.TransportError as exc:
            raise AIError("AI_PROVIDER_UNAVAILABLE", 503) from exc
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise AIError("AI_PROVIDER_INVALID_RESPONSE") from exc
