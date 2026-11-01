"""iGPT bridge: run behind HTTPS reverse proxy as an unprivileged user.
iOS 5 communicates with this service, never directly with OpenAI or YouTube.
"""
import asyncio
import hashlib
import hmac
import ipaddress
import os
import secrets
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

TOKEN = os.environ.get("IGPT_TOKEN", "")
API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("IGPT_MODEL", "gpt-5-mini")
WORKDIR = os.environ.get("IGPT_WORKDIR", "/var/lib/igpt/workspace")
PUBLIC_URL = os.environ.get("IGPT_PUBLIC_URL", "").rstrip("/")
INVIDIOUS = os.environ.get("IGPT_INVIDIOUS", "https://inv.nadeko.net").rstrip("/")
if len(TOKEN) < 32:
    raise RuntimeError("Set IGPT_TOKEN to a random 32+ character secret.")
os.makedirs(WORKDIR, exist_ok=True)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
history = []
browser_lock = asyncio.Lock()
pw = browser = page = None


class Payload(BaseModel):
    text: str = Field(default="", max_length=4000)
    action: str = ""
    url: str = ""
    x: int = 0
    y: int = 0
    delta: int = 0
    id: str = ""


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


@app.post("/chat/reset")
async def reset():
    history.clear()
    return {"ok": True}


@app.post("/chat")
async def chat(p: Payload):
    if not API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY is not configured on the VPS")
    if not p.text.strip():
        raise HTTPException(400, "Empty message")
    user_text = p.text[:4000]
    messages = (history[-14:] + [{"role": "user", "content": user_text}])
    async with httpx.AsyncClient(timeout=100) as client:
        try:
            r = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": "Bearer " + API_KEY},
                json={"model": MODEL, "input": messages, "max_output_tokens": 900},
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, "OpenAI API: HTTP " + str(e.response.status_code))
        except httpx.HTTPError as e:
            raise HTTPException(502, "OpenAI connection error: " + str(e))
    answer = "\n".join(
        c.get("text", "") for item in data.get("output", [])
        if item.get("type") == "message"
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    ).strip()
    if not answer:
        raise HTTPException(502, "No text in model response")
    history.extend(({"role": "user", "content": user_text},
                    {"role": "assistant", "content": answer}))
    del history[:-20]
    return {"text": answer}


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


async def ensure_browser():
    global pw, browser, page
    if page is None:
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True,
                                                args=[])
            page = await browser.new_page(viewport={"width": 1024, "height": 640},
                                          device_scale_factor=1)
        except Exception as e:
            page = None
            raise HTTPException(503, "Chromium not ready: " + str(e))


@app.post("/browser/action")
async def browser_action(p: Payload):
    async with browser_lock:
        await ensure_browser()
        try:
            if p.action == "open":
                url = p.url.strip()
                if "://" not in url:
                    url = "https://" + url
                await asyncio.to_thread(validate_url, url)
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            elif p.action == "click":
                await page.mouse.click(max(0, min(1023, p.x)), max(0, min(639, p.y)))
            elif p.action == "type":
                await page.keyboard.insert_text(p.text[:2000])
            elif p.action == "enter":
                await page.keyboard.press("Enter")
            elif p.action == "scroll":
                await page.mouse.wheel(0, max(-1200, min(1200, p.delta)))
            elif p.action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=20000)
            else:
                raise HTTPException(400, "Unknown action")
            return {"url": page.url}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, str(e)[:300])


@app.get("/browser/screen")
async def browser_screen():
    async with browser_lock:
        await ensure_browser()
        data = await page.screenshot(type="jpeg", quality=55)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/video/search")
async def video_search(p: Payload):
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(INVIDIOUS + "/api/v1/search",
                                 params={"q": p.text[:120], "type": "video"})
            r.raise_for_status()
            items = r.json()
            return {"items": [{"title": x.get("title", "")[:150],
                                "id": x.get("videoId", "")} for x in items[:15]
                               if x.get("videoId")]}
        except Exception:
            raise HTTPException(502, "Video search backend unavailable")


async def stream_info(video_id):
    if len(video_id) != 11 or not all(c.isalnum() or c in "-_" for c in video_id):
        raise HTTPException(400, "Bad video id")
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(INVIDIOUS + "/api/v1/videos/" + video_id)
            r.raise_for_status()
            streams = r.json().get("formatStreams", [])
        except Exception:
            raise HTTPException(502, "Invidious video metadata failed")
    candidates = [s for s in streams if "video/mp4" in s.get("type", "")]
    if not candidates:
        raise HTTPException(404, "No compatible MP4 format")
    return next((s.get("url") for s in candidates if "360" in s.get("qualityLabel", "")),
                candidates[0].get("url"))


def video_signature(video_id, exp):
    return hmac.new(TOKEN.encode(), (video_id + ":" + str(exp)).encode(),
                    hashlib.sha256).hexdigest()


@app.post("/video/url")
async def video_url(p: Payload):
    if not PUBLIC_URL.startswith("https://"):
        raise HTTPException(503, "Set IGPT_PUBLIC_URL to your HTTPS domain")
    await stream_info(p.id)
    exp = int(time.time()) + 900
    return {"url": PUBLIC_URL + "/video/stream/" + p.id + "?exp=" +
                   str(exp) + "&sig=" + video_signature(p.id, exp)}


@app.get("/video/stream/{video_id}")
async def video_stream(video_id: str, request: Request, exp: int = 0, sig: str = ""):
    # The player cannot set custom headers, so require a short-lived signed URL.
    if exp < time.time() or exp > time.time() + 1000 or not hmac.compare_digest(
        sig, video_signature(video_id, exp)
    ):
        raise HTTPException(401, "Expired stream link")
    url = await stream_info(video_id)
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
from remote import router as remote_router
app.include_router(remote_router)
