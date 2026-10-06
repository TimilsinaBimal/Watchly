from urllib.parse import urlparse

import httpx
from loguru import logger

from app.core.base_client import BaseClient

# AIOManager's Hydra protocol. Reinstall identifies the addon by its manifest URL,
# so one call both installs it and refreshes it in place, and the manager then
# propagates the result to every platform the account is connected to.
REINSTALL_PATH = "/hydra/reinstall"
STATUS_PATH = "/hydra/status"
ADDONS_PATH = "/hydra/addons"
REGISTER_PATH = "/hydra/register"

# Shown on the account's Connections card in AIOManager.
ADDON_NAME = "Watchly"

# The instance is too old to serve Hydra, or the URL points at something else that
# answers 200 with an HTML page. Both need the same answer: this is not a manager.
NO_HYDRA = "That instance does not serve AIOManager's Hydra API. Update AIOManager and try again."
NOT_A_MANAGER = "That URL is not an AIOManager instance. Check the address you open AIOManager at."
UNREACHABLE = "Could not reach that AIOManager instance. Check the URL and try again."


class AIOManagerError(Exception):
    """A Hydra call failed with something the configure page can explain to the user.

    Carries the HTTP status the page should see, so a rejected key is a 401 and a
    rate limit a 429 rather than everything collapsing into one gateway error.
    """

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def normalize_instance_url(url: str) -> str:
    """The instance URL without a trailing slash, which is how paths are built on it."""
    return (url or "").strip().rstrip("/")


def is_http_url(url: str) -> bool:
    try:
        return urlparse(url).scheme in ("http", "https") and bool(urlparse(url).netloc)
    except ValueError:
        return False


class AIOManagerService:
    """AIOManager's Hydra API, called on behalf of one user at a time.

    The instance URL is per user, so the client carries no base URL and every call
    takes a full one. Errors are translated here rather than in the endpoint: a
    rotated key, a rate limit and an instance that never had Hydra all reach the
    page as one sentence each.
    """

    def __init__(self) -> None:
        # One attempt, not the client's usual three: /hydra/reinstall is capped at
        # 10 requests a minute per account, so retrying inside the window would
        # spend the user's whole budget on a single save.
        self.client = BaseClient(timeout=15.0, max_retries=1)

    async def close(self) -> None:
        await self.client.close()

    @staticmethod
    def _url(instance_url: str, path: str) -> str:
        return f"{normalize_instance_url(instance_url)}{path}"

    @staticmethod
    def _auth(api_key: str) -> dict[str, str]:
        return {"X-API-Key": api_key}

    async def probe(self, instance_url: str) -> str:
        """The protocol version the instance reports, or raise when it serves no Hydra.

        `/hydra/status` is the only Hydra endpoint that needs no key, which makes it
        the way to tell a manager from any other web server before asking for one.
        """
        if not is_http_url(instance_url):
            raise AIOManagerError("Enter your AIOManager instance URL, including https://.", status=400)

        try:
            data = await self.client.get(self._url(instance_url, STATUS_PATH))
        except httpx.HTTPStatusError as error:
            # Every manager answers this path, so a 404 or a refusal means the URL
            # belongs to something else. Telling the user to update AIOManager here
            # would send them looking in the wrong place.
            if error.response.status_code in (400, 403, 404):
                raise AIOManagerError(NOT_A_MANAGER, status=400) from error
            raise self._explain(error) from error
        except Exception as error:
            raise self._explain(error) from error

        if not data.get("capabilities"):
            # An instance without a Hydra route answers its single-page app instead:
            # 200, HTML body, and BaseClient hands back {} for the unparseable body.
            raise AIOManagerError(NO_HYDRA)
        return str(data.get("platformVersion") or data.get("version") or "")

    async def check_key(self, instance_url: str, api_key: str) -> None:
        """Raise unless the account key is accepted, without changing anything.

        Reads the addon collection rather than registering: the page validates as
        the user types, and a rejected key must not leave a half-connected card.
        """
        try:
            await self.client.get(self._url(instance_url, ADDONS_PATH), headers=self._auth(api_key))
        except Exception as error:
            raise self._explain(error) from error

    async def reinstall(self, instance_url: str, api_key: str, addon_url: str) -> int:
        """Install this addon in the user's AIOManager account, or refresh it in place.

        Returns the size of the collection the manager reports back.
        """
        try:
            data = await self.client.post(
                self._url(instance_url, REINSTALL_PATH),
                json={"addonUrl": addon_url},
                headers=self._auth(api_key),
            )
        except Exception as error:
            raise self._explain(error) from error

        addons = data.get("addons")
        if not isinstance(addons, list):
            raise AIOManagerError(NO_HYDRA)

        # Best effort: appearing in the account's Connections list is a nicety, and
        # the addon is already installed by the call above.
        await self.register(instance_url, api_key)
        logger.info("Pushed this addon to AIOManager")
        return len(addons)

    async def register(self, instance_url: str, api_key: str) -> None:
        """Name this addon to the manager so it shows as a pull source. Never fatal."""
        try:
            await self.client.post(
                self._url(instance_url, REGISTER_PATH),
                json={"name": ADDON_NAME},
                headers=self._auth(api_key),
            )
        except Exception as error:
            logger.warning(f"AIOManager registration was not accepted: {type(error).__name__}")

    def _explain(self, error: Exception) -> AIOManagerError:
        """One sentence per failure the user can act on, under the status the page should see."""
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 401:
                return AIOManagerError(
                    "AIOManager rejected that API key. Copy it again from the API Key tab of your account.",
                    status=401,
                )
            if status == 429:
                return AIOManagerError(
                    "AIOManager is rate limiting this account. Wait a minute and try again.", status=429
                )
            if 400 <= status < 500:
                return AIOManagerError(
                    self._upstream_message(error.response) or "AIOManager refused the request.", status=400
                )
            return AIOManagerError("AIOManager could not complete the request. Try again shortly.")
        if isinstance(error, httpx.HTTPError):
            return AIOManagerError(UNREACHABLE)
        return AIOManagerError("AIOManager could not complete the request. Try again shortly.")

    @staticmethod
    def _upstream_message(response: httpx.Response) -> str | None:
        try:
            message = response.json().get("message")
        except ValueError:
            return None
        return message if isinstance(message, str) and message else None


aiomanager_service = AIOManagerService()
