"""Wanderpin - set your iPhone's GPS location from your PC.

Runs a small local web app (http://127.0.0.1:8765) and talks to the iPhone through
pymobiledevice3's developer location-simulation service (the same one Xcode uses).

Needs: iOS 17.4+, Developer Mode on, and `pymobiledevice3 remote tunneld` running
as administrator (the app can start it for you on Windows).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.tunneld.api import get_tunneld_devices

import updater

VERSION = "1.0.0"
# Your public GitHub repo that holds releases, e.g. "janedoe/wanderpin".
UPDATE_REPO = "kermit13619/Wanderpin"

HOST, PORT = "127.0.0.1", 8765
HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "Wanderpin"
SPOTS_FILE = DATA_DIR / "spots.json"
TICK_S = 1.0  # how often a route pushes a new position

SPEEDS = {"walk": 1.4, "bike": 5.0, "drive": 13.0}  # metres per second


# --------------------------------------------------------------------------- geometry

def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def walk_path(points: list[tuple[float, float]], step_m: float):
    """Yield positions spaced step_m apart along a polyline."""
    yield points[0]
    carry = 0.0
    for a, b in zip(points, points[1:]):
        seg = distance_m(a, b)
        if seg == 0:
            continue
        d = step_m - carry
        while d <= seg:
            t = d / seg
            yield (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            d += step_m
        carry = seg - (d - step_m)
    yield points[-1]


# --------------------------------------------------------------------------- device

class Device:
    """Holds one location-simulation channel open. Closing the channel makes iOS
    drop the fake location, so we keep it open for as long as the app runs."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.stack: Optional[contextlib.AsyncExitStack] = None
        self.loc: Optional[LocationSimulation] = None
        self.info: dict = {}
        self.state = "idle"  # idle | connecting | ready | error
        self.message = "Not connected yet."
        self.position: Optional[tuple[float, float]] = None
        self.route_task: Optional[asyncio.Task] = None
        self.route_progress: Optional[dict] = None

    # -- connection ---------------------------------------------------------
    async def connect(self) -> None:
        async with self.lock:
            await self._close()
            self.state, self.message = "connecting", "Looking for your iPhone…"
            try:
                rsds = await get_tunneld_devices()
            except Exception:
                self._fail("Phone connection service isn't running. Click “Start phone connection”.")
                return
            if not rsds:
                self._fail("No iPhone found. Plug it in by USB, unlock it and tap Trust.")
                return
            rsd, extra = rsds[0], rsds[1:]
            for r in extra:
                with contextlib.suppress(Exception):
                    await r.close()

            self.info = {
                "name": _attr(rsd, "name", "device_name") or "iPhone",
                "model": _attr(rsd, "product_type"),
                "ios": _attr(rsd, "product_version"),
                "udid": _attr(rsd, "udid"),
            }
            self.message = "Preparing developer tools on the phone…"
            ok, err = await asyncio.to_thread(_mount_developer_image, self.info.get("udid"))
            if not ok:
                with contextlib.suppress(Exception):
                    await rsd.close()
                self._fail(_explain(err))
                return

            stack = contextlib.AsyncExitStack()
            try:
                stack.push_async_callback(rsd.close)
                dvt = await stack.enter_async_context(DvtProvider(rsd))
                self.loc = await stack.enter_async_context(LocationSimulation(dvt))
            except Exception as e:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    await stack.aclose()
                self.loc = None
                self._fail(_explain(repr(e)))
                return
            self.stack = stack
            self.state, self.message = "ready", "Connected."
            if self.position:  # re-apply after a reconnect
                with contextlib.suppress(Exception):
                    await self.loc.set(*self.position)

    async def _close(self) -> None:
        if self.stack:
            with contextlib.suppress(Exception):
                await self.stack.aclose()
        self.stack, self.loc = None, None

    def _fail(self, msg: str) -> None:
        self.state, self.message = "error", msg

    async def _push(self, lat: float, lon: float) -> None:
        """Send one position, reconnecting once if the channel dropped."""
        if self.loc is None:
            await self.connect()
        if self.loc is None:
            raise HTTPException(409, self.message)
        try:
            await self.loc.set(lat, lon)
        except Exception:  # noqa: BLE001
            self.position = (lat, lon)
            await self.connect()
            if self.loc is None:
                raise HTTPException(409, self.message)
        self.position = (lat, lon)

    # -- commands -----------------------------------------------------------
    async def set(self, lat: float, lon: float) -> None:
        await self.stop_route()
        await self._push(lat, lon)

    async def clear(self) -> None:
        await self.stop_route()
        self.position = None
        if self.loc:
            with contextlib.suppress(Exception):
                await self.loc.clear()

    async def start_route(self, points: list[tuple[float, float]], speed: float, loop: bool) -> None:
        await self.stop_route()
        await self._push(*points[0])
        self.route_task = asyncio.create_task(self._run_route(points, speed, loop))

    async def stop_route(self) -> None:
        t, self.route_task = self.route_task, None
        self.route_progress = None
        if t and not t.done():
            t.cancel()
            with contextlib.suppress(BaseException):
                await t

    async def _run_route(self, points, speed: float, loop: bool) -> None:
        total = sum(distance_m(a, b) for a, b in zip(points, points[1:]))
        try:
            while True:
                done = 0.0
                prev = points[0]
                for p in walk_path(points, speed * TICK_S):
                    done += distance_m(prev, p)
                    prev = p
                    self.route_progress = {"done_m": round(done), "total_m": round(total), "loop": loop}
                    await self._push(*p)
                    await asyncio.sleep(TICK_S)
                if not loop:
                    break
                points = list(reversed(points))  # walk back the way we came
        except HTTPException:
            pass
        finally:
            self.route_progress = None
            if self.route_task is asyncio.current_task():
                self.route_task = None

    def status(self) -> dict:
        return {
            "state": self.state,
            "message": self.message,
            "device": self.info if self.state == "ready" else None,
            "position": list(self.position) if self.position else None,
            "route": self.route_progress,
            "tunnel_running": _tunneld_running(),
            "version": VERSION,
            "update": update_state,
        }


def _attr(obj, *names):
    for n in names:
        v = getattr(obj, n, None)
        if v:
            return str(v)
    return None


def _mount_developer_image(udid: Optional[str]) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pymobiledevice3", "mounter", "auto-mount", "--tunnel", udid or ""]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, "mount timed out"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 or "already mounted" in out.lower():
        return True, ""
    return False, out[-400:]


def _explain(err: str) -> str:
    e = err.lower()
    if "developermode" in e or "developer mode" in e or "dtservicehub" in e:
        return "Turn on Developer Mode: Settings → Privacy & Security → Developer Mode, then restart the phone."
    if "passcode" in e or "password" in e or "locked" in e:
        return "Unlock your iPhone and try again."
    if "timed out" in e or "timeout" in e:
        return "The phone took too long to answer. Unplug it, plug it back in and try again."
    return "Couldn't talk to the phone: " + err.strip().splitlines()[-1][:200] if err.strip() else "Couldn't talk to the phone."


def _tunneld_running() -> bool:
    import socket
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", 49151), timeout=0.3):
        return True
    return False


def start_tunneld_elevated() -> str:
    args = "-m pymobiledevice3 remote tunneld"
    if sys.platform == "win32":
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
        if rc <= 32:
            raise HTTPException(500, "Windows didn't start the phone connection (admin prompt declined?).")
        return "started"
    raise HTTPException(400, f"Run this in a terminal, then click Connect:  sudo {sys.executable} {args}")


# --------------------------------------------------------------------------- spots

def load_spots() -> list[dict]:
    try:
        return json.loads(SPOTS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return []


def save_spots(spots: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SPOTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(spots, indent=2), "utf-8")
    tmp.replace(SPOTS_FILE)


# --------------------------------------------------------------------------- web app

class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteIn(BaseModel):
    points: list[Point] = Field(min_length=2, max_length=20_000)
    speed: str = "walk"
    loop: bool = False


class SpotIn(Point):
    name: str = Field(min_length=1, max_length=80)


# --------------------------------------------------------------------------- updates

update_state: dict = {"available": False}
_update_info: Optional[dict] = None


async def check_for_update() -> None:
    global _update_info
    try:
        _update_info = await asyncio.to_thread(updater.check, UPDATE_REPO, VERSION)
    except Exception:  # offline, rate-limited, repo not set up yet...
        _update_info = None
    if _update_info:
        update_state.update(available=True, version=_update_info["version"], notes=_update_info["notes"])


device = Device()


@contextlib.asynccontextmanager
async def lifespan(_app):
    asyncio.get_running_loop().create_task(check_for_update())
    if _tunneld_running():  # reconnect by itself, e.g. right after an update
        asyncio.get_running_loop().create_task(device.connect())
    yield
    await device.clear()  # hand the phone back its real GPS
    await device._close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    # Only this app's own page may change things: other websites can't add this
    # header to a cross-site request without a CORS preflight, which we never allow.
    if request.method != "GET" and request.headers.get("x-wanderpin") != "1":
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return await call_next(request)


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/status")
async def api_status():
    return device.status()


@app.post("/api/tunnel")
async def api_tunnel():
    return {"result": start_tunneld_elevated()}


@app.post("/api/connect")
async def api_connect():
    await device.connect()
    return device.status()


@app.post("/api/set")
async def api_set(p: Point):
    await device.set(p.lat, p.lon)
    return device.status()


@app.post("/api/clear")
async def api_clear():
    await device.clear()
    return device.status()


@app.post("/api/route")
async def api_route(r: RouteIn):
    if r.speed not in SPEEDS:
        raise HTTPException(400, "speed must be walk, bike or drive")
    await device.start_route([(p.lat, p.lon) for p in r.points], SPEEDS[r.speed], r.loop)
    return device.status()


@app.post("/api/route/stop")
async def api_route_stop():
    await device.stop_route()
    return device.status()


@app.post("/api/update")
async def api_update():
    if not _update_info:
        raise HTTPException(400, "No update available.")
    if update_state.get("installing"):
        raise HTTPException(409, "Already updating.")
    update_state["installing"] = True
    try:
        await asyncio.to_thread(updater.install, _update_info, HERE, sys.executable)
    except Exception as e:  # noqa: BLE001
        update_state["installing"] = False
        raise HTTPException(500, f"Update failed: {e}")
    await device.clear()
    await device._close()
    updater.restart(HERE, sys.executable)
    # Exit after this response is sent; the new version takes over the port.
    asyncio.get_running_loop().call_later(0.5, os._exit, 0)
    return {"result": "restarting", "version": _update_info["version"]}


@app.get("/api/spots")
async def api_spots():
    return load_spots()


@app.post("/api/spots")
async def api_add_spot(s: SpotIn):
    spots = [x for x in load_spots() if x.get("name") != s.name]
    spots.append({"name": s.name, "lat": s.lat, "lon": s.lon})
    save_spots(spots)
    return spots


@app.delete("/api/spots/{name}")
async def api_del_spot(name: str):
    spots = [x for x in load_spots() if x.get("name") != name]
    save_spots(spots)
    return spots


def main() -> None:
    url = f"http://{HOST}:{PORT}/"
    after_update = "--after-update" in sys.argv
    if after_update:  # wait for the old version to let go of the port
        import socket
        for _ in range(40):
            with socket.socket() as s:
                if s.connect_ex((HOST, PORT)) != 0:
                    break
            time.sleep(0.25)
    if "--no-browser" not in sys.argv and not after_update:  # the open page reloads itself
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"Wanderpin is running at {url}  (close this window to stop; your real GPS comes back)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
