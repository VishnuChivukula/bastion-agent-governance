"""HTTP client for the control-plane API, as used by the console."""

from typing import Any

import httpx

from bastion.api.auth import ACTOR_HEADER, PASSCODE_HEADER


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Api:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=30)
        self.passcode = ""
        self.actor = ""

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.passcode:
            headers[PASSCODE_HEADER] = self.passcode
        if self.actor:
            headers[ACTOR_HEADER] = self.actor
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(
                method, self.base_url + path, headers=self._headers(), **kwargs
            )
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Cannot reach the Bastion API at {self.base_url} ({exc})") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            if not isinstance(detail, str):  # FastAPI validation errors: a list of problems
                detail = "; ".join(
                    f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}"
                    for d in detail
                )
            raise ApiError(response.status_code, detail)
        return response.json()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", path, json=body)
