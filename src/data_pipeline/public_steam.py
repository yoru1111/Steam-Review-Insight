"""Bounded requests to fixed public Steam sources without credentials."""
import http.client
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .collector import CollectionError, RETRYABLE, retry_delay

HOSTS = {"store.steampowered.com", "api.steampowered.com"}

def allowed(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and (host in HOSTS or host.endswith(".steamstatic.com")
                                                    or host == "steamcdn-a.akamaihd.net"))
    except ValueError:
        return False


class SteamRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not allowed(newurl):
            raise CollectionError("Steam redirect target is not allowed")
        return super().redirect_request(request, fp, code, message, headers, newurl)


class PublicSteamClient:
    def __init__(self, *, opener=None, sleep=time.sleep, delay=1, timeout=15, retries=2):
        self.opener = opener or build_opener(SteamRedirects()).open
        self.sleep, self.delay, self.timeout, self.retries = sleep, delay, timeout, retries
        self.calls = 0

    def get(self, url, *, as_json=True, method="GET"):
        if not allowed(url):
            raise ValueError("Only fixed public Steam sources are allowed")
        for attempt in range(self.retries + 1):
            if self.calls:
                self.sleep(self.delay)
            self.calls += 1
            wait = None
            try:
                request = Request(url, headers={"User-Agent": "Steam-Review-Insight/2.0"}, method=method)
                with self.opener(request, timeout=self.timeout) as response:
                    if method == "HEAD":
                        return True
                    payload = response.read(8 * 1024 * 1024 + 1)
                    if len(payload) > 8 * 1024 * 1024:
                        raise CollectionError("Steam response exceeds size limit")
                    return json.loads(payload) if as_json else payload.decode("utf-8")
            except HTTPError as exc:
                code = exc.code
                wait = retry_delay(exc.headers.get("Retry-After") if exc.headers else None, attempt)
                exc.close()
                if code not in RETRYABLE:
                    raise CollectionError(f"Public Steam HTTP {code}") from None
                error = f"Public Steam HTTP {code}"
            except (URLError, TimeoutError, OSError, http.client.HTTPException):
                error = "Public Steam network error"
            except (ValueError, UnicodeError):
                raise CollectionError("Public Steam returned invalid content") from None
            if attempt == self.retries:
                raise CollectionError(error)
            wait = wait if wait is not None else retry_delay(None, attempt)
            if wait > 120:
                raise CollectionError(error + "; Retry-After exceeds 120 seconds")
            self.sleep(wait)
