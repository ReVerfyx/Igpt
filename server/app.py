"""iGPT bridge: run behind HTTPS reverse proxy as an unprivileged user.
iOS 5 communicates with this service, never directly with OpenAI or YouTube.
"""
import asyncio
import errno
import hashlib
import hmac
import ipaddress
import os
import pty
import secrets
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

TOKEN = os.environ.get("IGPT_TOKEN", "")
WORKDIR = os.environ.get("IGPT_WORKDIR", "/var/lib/igpt/workspace")
VIDEO_CACHE = os.environ.get("IGPT_VIDEO_CACHE", "/var/lib/igpt/video-cache")
VIDEO_CACHE_LIMIT = int(os.environ.get("IGPT_VIDEO_CACHE_LIMIT", str(800 * 1024 * 1024)))
PUBLIC_URL = os.environ.get("IGPT_PUBLIC_URL", "").rstrip("/")
# Comma separated, self-hosted instances are preferred.  A single public
# instance is deliberately not a mandatory dependency.
INVIDIOUS_INSTANCES = [x.rstrip("/") for x in os.environ.get(
    "IGPT_INVIDIOUS_INSTANCES", "https://yewtu.be,https://inv.nadeko.net"
).split(",") if x.strip()]
if len(TOKEN) < 32:
    raise RuntimeError("Set IGPT_TOKEN to a random 32+ character secret.")
os.makedirs(WORKDIR, exist_ok=True)
os.makedirs(VIDEO_CACHE, exist_ok=True)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
terminal_sessions = {}
TERMINAL_LIMIT = 3


class Payload(BaseModel):
    text: str = Field(default="", max_length=4000)
    action: str = ""
    url: str = ""
    x: int = 0
    y: int = 0
    delta: int = 0
    id: str = ""
    quality: str = "360p"


def close_terminal(session_id):
    session = terminal_sessions.pop(session_id, None)
    if not session:
        return
    try:
        os.close(session["fd"])
    except OSError:
        pass
    try:
        os.kill(session["pid"], 15)
    except OSError:
        pass


@app.post("/terminal/open")
async def terminal_open():
    """Create an unprivileged interactive PTY; no SSH/root credential exists here."""
    if len(terminal_sessions) >= TERMINAL_LIMIT:
        raise HTTPException(429, "Terminal session limit reached")
    # forkpty makes the shell's slave its controlling terminal; merely wiring
    # pipes to a pseudo-terminal makes interactive programs exit on SIGHUP.
    pid, master = pty.fork()
    if pid == 0:  # pragma: no cover - replaced by exec in the child
        os.chdir(WORKDIR)
        os.execvpe("/bin/bash", ["/bin/bash", "--noprofile", "--norc"],
                   {**os.environ, "TERM": "xterm", "HISTFILE": "/dev/null"})
    os.set_blocking(master, False)
    session_id = secrets.token_urlsafe(24)
    terminal_sessions[session_id] = {"fd": master, "pid": pid, "last": time.monotonic()}
    return {"id": session_id}


@app.post("/terminal/write")
async def terminal_write(p: Payload):
    session = terminal_sessions.get(p.id)
    if not session:
        raise HTTPException(404, "Terminal session not found")
    raw = p.text.encode("utf-8", "replace")[:8192]
    try:
        os.write(session["fd"], raw)
    except OSError:
        close_terminal(p.id)
        raise HTTPException(410, "Terminal session closed")
    session["last"] = time.monotonic()
    return {"ok": True}


@app.post("/terminal/read")
async def terminal_read(p: Payload):
    session = terminal_sessions.get(p.id)
    if not session:
        raise HTTPException(404, "Terminal session not found")
    chunks = []
    remaining = 16384
    while remaining:
        try:
            chunk = os.read(session["fd"], min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                break
            close_terminal(p.id)
            raise HTTPException(410, "Terminal session closed")
    session["last"] = time.monotonic()
    return {"text": b"".join(chunks).decode("utf-8", "replace")}


@app.post("/terminal/close")
async def terminal_close(p: Payload):
    close_terminal(p.id)
    return {"ok": True}


@app.middleware("http")
async def check_auth(req: Request, next_call):
    if req.url.path == "/health" or req.url.path.startswith("/video/stream/"):
        # /video/stream has its own short-lived HMAC signature validation.
        return await next_call(req)
    got = req.headers.get("x-igpt-token", "")
    if not hmac.compare_digest(got, TOKEN):
        return Response("unauthorized", status_code=401)
    return await next_call(req)


@app.get("/health")
async def health():
    return {"ok": True, "name": "iGPT bridge"}


def execute(argv, seconds):
    try:
        result = subprocess.run(argv, cwd=WORKDIR, capture_output=True,
                                text=True, errors="replace", timeout=seconds,
                                env={**os.environ, "HOME": os.path.expanduser("~")})
        return {"text": (result.stdout + "\n" + result.stderr)[-12000:] or "(no output)",
                "status": result.returncode}
    except subprocess.TimeoutExpired:
        return {"text": "Timeout; process stopped", "status": 124}
    except OSError as err:
        return {"text": str(err), "status": 127}


@app.post("/term")
async def terminal(p: Payload):
    # Explicit commands from authenticated owner only. Never run this service as root.
    if not p.text.strip():
        raise HTTPException(400, "Empty command")
    return await asyncio.to_thread(execute, ["/bin/sh", "-lc", p.text], 30)


@app.post("/codex")
async def codex(p: Payload):
    if not shutil.which("codex"):
        raise HTTPException(503, "Install and authenticate Codex CLI on VPS first")
    return await asyncio.to_thread(execute,
        ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
         "--cd", WORKDIR, p.text], 180)


def validate_url(url):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Only http(s) allowed")
    parts = urlsplit(url)
    host = parts.hostname
    if not host or parts.username or parts.password:
        raise HTTPException(400, "Invalid URL")
    try:
        ips = socket.getaddrinfo(host, parts.port or 443)
    except socket.gaierror:
        raise HTTPException(400, "Host not found")
    for hit in ips:
        ip = ipaddress.ip_address(hit[4][0])
        if not ip.is_global:
            raise HTTPException(403, "Private or local addresses blocked")


@app.post("/video/search")
async def video_search(p: Payload):
    if not p.text.strip():
        raise HTTPException(400, "Empty search")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for instance in INVIDIOUS_INSTANCES:
            try:
                r = await client.get(instance + "/api/v1/search",
                                     params={"q": p.text[:120], "type": "video"})
                r.raise_for_status()
                items = r.json()
                return {"items": [{"title": x.get("title", "")[:150],
                                   "id": x.get("videoId", ""),
                                   "thumb": x.get("videoThumbnails", [{}])[0].get("url", "")}
                                  for x in items[:15] if x.get("videoId")]}
            except (httpx.HTTPError, ValueError, KeyError):
                continue
    raise HTTPException(502, "No configured video backend is available")


async def stream_info(video_id, quality="360p"):
    if len(video_id) != 11 or not all(c.isalnum() or c in "-_" for c in video_id):
        raise HTTPException(400, "Bad video id")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for instance in INVIDIOUS_INSTANCES:
            try:
                r = await client.get(instance + "/api/v1/videos/" + video_id)
                r.raise_for_status()
                streams = r.json().get("formatStreams", [])
                candidates = [s for s in streams if "video/mp4" in s.get("type", "") and s.get("url")]
                # iPad 1 decodes baseline/main H.264 best at 360p.  The source
                # is still proxied through this service; conversion is handled
                # by a local source deployment when no compatible stream exists.
                if candidates:
                    requested = quality if quality in ("144p", "240p", "360p", "480p") else "360p"
                    return next((s["url"] for s in candidates
                                 if requested in s.get("qualityLabel", "")),
                                next((s["url"] for s in candidates
                                      if "360" in s.get("qualityLabel", "")), candidates[0]["url"]))
            except (httpx.HTTPError, ValueError, KeyError):
                continue
    raise HTTPException(404, "No compatible MP4 stream from configured backends")


def cache_path(video_id, quality):
    # video_id and quality are validated before this point; retain a fixed name.
    return os.path.join(VIDEO_CACHE, video_id + "-" + quality + ".mp4")


async def cache_video(video_id, quality):
    """Download once to the VPS. iPad then seeks a local H.264/AAC MP4."""
    path = cache_path(video_id, quality)
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return path
    source = await stream_info(video_id, quality)
    await asyncio.to_thread(validate_url, source)
    temporary = path + ".part"
    total = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=180), follow_redirects=True) as client:
            async with client.stream("GET", source) as response:
                response.raise_for_status()
                length = int(response.headers.get("content-length", "0") or 0)
                if length and length > VIDEO_CACHE_LIMIT:
                    raise HTTPException(413, "Video exceeds VPS cache limit")
                with open(temporary, "wb") as output:
                    async for chunk in response.aiter_bytes(65536):
                        total += len(chunk)
                        if total > VIDEO_CACHE_LIMIT:
                            raise HTTPException(413, "Video exceeds VPS cache limit")
                        output.write(chunk)
        os.replace(temporary, path)
        return path
    except HTTPException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    except (OSError, httpx.HTTPError) as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise HTTPException(502, "Video download failed: " + str(exc)[:160])


def video_signature(video_id, quality, exp):
    return hmac.new(TOKEN.encode(), (video_id + ":" + quality + ":" + str(exp)).encode(),
                    hashlib.sha256).hexdigest()


@app.post("/video/url")
async def video_url(p: Payload):
    if not PUBLIC_URL.startswith("https://"):
        raise HTTPException(503, "Set IGPT_PUBLIC_URL to your HTTPS domain")
    quality = p.quality if p.quality in ("144p", "240p", "360p", "480p") else "360p"
    await cache_video(p.id, quality)
    exp = int(time.time()) + 900
    return {"url": PUBLIC_URL + "/video/stream/" + p.id + "?exp=" +
                   str(exp) + "&quality=" + quality + "&sig=" + video_signature(p.id, quality, exp)}


@app.get("/video/stream/{video_id}")
async def video_stream(video_id: str, request: Request, exp: int = 0, quality: str = "360p", sig: str = ""):
    # The player cannot set custom headers, so require a short-lived signed URL.
    if exp < time.time() or exp > time.time() + 1000 or not hmac.compare_digest(
        sig, video_signature(video_id, quality, exp)
    ):
        raise HTTPException(401, "Expired stream link")
    cached = cache_path(video_id, quality)
    if os.path.isfile(cached) and os.path.getsize(cached) > 1024:
        # Starlette FileResponse handles RFC 7233 Range requests for seeking.
        return FileResponse(cached, media_type="video/mp4", filename=video_id + ".mp4")
    url = await stream_info(video_id, quality)
    client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=90), follow_redirects=True)
    range_value = request.headers.get("range", "")
    upstream = await client.send(
        client.build_request("GET", url,
                             headers={"Range": range_value} if range_value else {}),
        stream=True)
    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, "Video upstream unavailable")
    headers = {k: v for k, v in upstream.headers.items()
               if k.lower() in ("content-range", "accept-ranges", "content-length")}
    async def body():
        try:
            async for chunk in upstream.aiter_bytes(65536):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(body(), status_code=upstream.status_code,
                             headers=headers, media_type="video/mp4")


# iOS 5 remote display sessions (separate persistent ChatGPT and browser profiles).
from remote import router as remote_router, close as close_remote
app.include_router(remote_router)

@app.on_event("shutdown")
async def shutdown_remote():
    for session_id in list(terminal_sessions):
        close_terminal(session_id)
    await close_remote()
