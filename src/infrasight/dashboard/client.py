import httpx


class APIError(Exception):
    def __init__(self, status, code, request_id=None):
        self.status, self.code, self.request_id = status, code, request_id
        super().__init__(code)

    @property
    def message(self):
        return {
            401: (
                "Your dashboard access could not be verified. Check server-side API configuration."
            ),
            403: "This operation needs administrative access.",
            409: "An ingestion cycle is already running for this source.",
            422: "Check the selected time window and query parameters.",
            429: (
                "The AI analyst has reached its usage limit. Wait a moment before submitting again."
            ),
            502: "The AI provider could not complete this analysis. No answer was generated.",
            503: "The analytics service is temporarily unavailable.",
            504: "The analysis took too long. Try a shorter question or window.",
        }.get(self.status, "The request could not complete. Please try again.")


class APIClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.api_base_url,
            timeout=settings.request_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self):
        self.http.close()

    def request(self, method, endpoint, params=None, body=None, admin=False):
        if not endpoint.startswith("/api/v1/") or "://" in endpoint or ".." in endpoint:
            raise APIError(422, "INVALID_ENDPOINT")
        if not self.settings.api_key:
            raise APIError(401, "READ_KEY_NOT_CONFIGURED")
        headers = {"X-API-Key": self.settings.api_key.get_secret_value()}
        if admin:
            if not self.settings.admin_key:
                raise APIError(403, "ADMIN_KEY_NOT_CONFIGURED")
            headers["X-Admin-Key"] = self.settings.admin_key.get_secret_value()
        timeout = 70 if method == "POST" else self.settings.request_timeout_seconds
        try:
            response = self.http.request(
                method,
                endpoint,
                headers=headers,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=body,
                timeout=timeout,
            )
            try:
                result = response.json()
            except ValueError as exc:
                raise APIError(502, "INVALID_API_RESPONSE") from exc
            if response.status_code >= 400:
                # Never relay arbitrary backend/provider messages to the interface.
                raise APIError(
                    response.status_code, "REQUEST_FAILED", response.headers.get("X-Request-ID")
                )
            if not isinstance(result, dict):
                raise APIError(502, "INVALID_API_RESPONSE")
            expected = (
                {"answer", "evidence", "request_id"}
                if endpoint == "/api/v1/ai/query"
                else {"data", "meta"}
            )
            if (
                not expected <= result.keys()
                or (
                    endpoint != "/api/v1/ai/query"
                    and (
                        not isinstance(result.get("data"), (dict, list))
                        or not isinstance(result.get("meta"), dict)
                    )
                )
                or (
                    endpoint == "/api/v1/ai/query"
                    and (
                        not isinstance(result.get("answer"), str)
                        or not isinstance(result.get("evidence"), dict)
                    )
                )
            ):
                raise APIError(502, "INVALID_API_RESPONSE")
            return result
        except httpx.TimeoutException as exc:
            raise APIError(504, "REQUEST_TIMEOUT") from exc
        except httpx.TransportError as exc:
            raise APIError(503, "API_UNAVAILABLE") from exc

    def get(self, endpoint, params=None):
        return self.request("GET", endpoint, params=params)

    def ask(self, body):
        return self.request("POST", "/api/v1/ai/query", body=body)

    def trigger(self, body):
        return self.request("POST", "/api/v1/etl/run", body=body, admin=True)
