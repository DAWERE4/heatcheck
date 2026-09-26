"""Talking to the outside world: Twilio (phone calls) and ntfy (push alerts).

Only the Python standard library is used, so there is nothing to install.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class ServiceError(RuntimeError):
    pass


def _read_error(err: urllib.error.HTTPError) -> str:
    try:
        body = err.read().decode("utf-8", "replace")
        data = json.loads(body)
        return data.get("message") or body
    except Exception:
        return str(err)


def twilio_create_call(settings, to: str, url: str, status_callback: str = None,
                       machine_detection: bool = True, ring_seconds: int = 25) -> str:
    """Start an outbound call. Twilio fetches `url` for instructions when it connects.

    Returns the call SID.
    """
    endpoint = (
        f"{settings.twilio_api_base}/2010-04-01/Accounts/"
        f"{urllib.parse.quote(settings.twilio_sid)}/Calls.json"
    )
    params = [
        ("To", to),
        ("From", settings.twilio_from),
        ("Url", url),
        ("Method", "POST"),
        ("Timeout", str(ring_seconds)),
    ]
    if status_callback:
        params += [("StatusCallback", status_callback), ("StatusCallbackMethod", "POST")]
    if machine_detection:
        params.append(("MachineDetection", "Enable"))

    request = urllib.request.Request(
        endpoint, data=urllib.parse.urlencode(params).encode("utf-8"), method="POST"
    )
    creds = base64.b64encode(f"{settings.twilio_sid}:{settings.twilio_token}".encode()).decode()
    request.add_header("Authorization", "Basic " + creds)
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8")).get("sid", "")
    except urllib.error.HTTPError as err:
        raise ServiceError(f"Twilio said: {_read_error(err)}") from err
    except urllib.error.URLError as err:
        raise ServiceError(f"Couldn't reach Twilio: {err.reason}") from err


def ntfy_publish(settings, topic: str, title: str, message: str, priority: int = 5,
                 tags=None, click: str = None, actions=None) -> None:
    """Send a push notification to everyone subscribed to `topic` in the ntfy app."""
    payload = {"topic": topic, "title": title, "message": message, "priority": priority}
    if tags:
        payload["tags"] = list(tags)
    if click:
        payload["click"] = click
    if actions:
        payload["actions"] = actions
    request = urllib.request.Request(
        settings.ntfy_server + "/",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as err:
        raise ServiceError(f"ntfy said: {_read_error(err)}") from err
    except urllib.error.URLError as err:
        raise ServiceError(f"Couldn't reach ntfy: {err.reason}") from err
