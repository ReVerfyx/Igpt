"""Persistent remote Chromium sessions for iGPT iOS 5 client.
No ChatGPT API key required; user logs in to chatgpt.com through rendered screen.
"""
import asyncio
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/remote", tags=["remote"])
PROFILE_ROOT = Path(os.environ.get("IGPT_PROFILE_DIR", "/var/lib/igpt/profiles"))
PROFILE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(PROFILE_ROOT, 0o700)
WIDTH, HEIGHT = 1024, 700
contexts = {}
pages = {}
locks = {"chatgpt": asyncio.Lock(), "browser": asyncio.Lock()}
_playwright = None
_browser = None
_cache = {}

async def close():
    """Release Chromium cleanly so profile state and RAM are not leaked."""
    global _browser, _playwright
    for context in list(contexts.values()):
        try:
            await context.close()
        except Exception:
            pass
    contexts.clear()
    pages.clear()
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None

class Command(BaseModel):
    mode: str = "chatgpt"
    action: str = ""
    url: str = ""
    text: str = Field(default="", max_length=8000)
    key: str = ""
    x: int = 0
    y: int = 0
    delta: int = 0
    width: int = 1024
    height: int = 700

def check_mode(mode):
    if mode not in locks:
        raise HTTPException(400, "mode must be chatgpt or browser")

def checked_url(address):
    address = address.strip()
    if "://" not in address:
        address = "https://" + address
    u = urlsplit(address)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("HTTP(S) public URL required")
    if u.port and u.port not in (80, 443):
        raise ValueError("Only 80/443 permitted")
    return address

def resolve_public_host(host):
    # This is defense in depth; the process should also have an egress firewall
    # preventing access to local/private/metadata network ranges.
    import time
    hit = _cache.get(host)
    if hit is not None and time.monotonic() < hit:
        return
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not records:
            raise ValueError("Cannot resolve host")
        if any(not ipaddress.ip_address(row[4][0]).is_global for row in records):
            raise ValueError("Local/private network blocked")
    except (OSError, ValueError) as exc:
        raise ValueError(str(exc))
    _cache[host] = time.monotonic() + 30

async def network_guard(route):
    try:
        url = route.request.url
        if url.startswith(("data:", "blob:")):
            await route.continue_()
            return
        checked_url(url)
        host = urlsplit(url).hostname
        await asyncio.to_thread(resolve_public_host, host)
        await route.continue_()
    except Exception:
        await route.abort()

async def ensure(mode):
    global _playwright, _browser
    check_mode(mode)
    if mode in pages and not pages[mode].is_closed():
        return pages[mode]
    try:
        from playwright.async_api import async_playwright
        if _playwright is None:
            _playwright = await async_playwright().start()
        # One Chromium process hosts both isolated contexts.  Cookies are saved
        # to separate state files after every operation, avoiding one Chromium
        # per panel while preserving the ChatGPT/browser login separation.
        if _browser is None or not _browser.is_connected():
            headless = os.environ.get("IGPT_HEADLESS", "1") != "0"
            _browser = await _playwright.chromium.launch(headless=headless)
        user_dir = PROFILE_ROOT / mode
        user_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(user_dir, 0o700)
        state = user_dir / "storage-state.json"
        context = await _browser.new_context(
            storage_state=str(state) if state.exists() else None,
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
            locale="ru-RU",
            accept_downloads=False,
            ignore_https_errors=False,
            java_script_enabled=True,
            # Chromium sandbox may need host user namespaces configured.
            # The server must be unprivileged and isolated from internal networks.
        )
        await context.route("**/*", network_guard)
        page = context.pages[0] if context.pages else await context.new_page()
        contexts[mode], pages[mode] = context, page
        if not page.url.startswith(("https://", "http://")):
            await page.goto("https://chatgpt.com/" if mode == "chatgpt" else "https://example.org",
                            wait_until="domcontentloaded", timeout=35000)
        return page
    except Exception as exc:
        raise HTTPException(503, "Remote Chromium unavailable: " + str(exc)[:240])

@router.post("/open")
async def open_mode(p: Command):
    check_mode(p.mode)
    async with locks[p.mode]:
        page = await ensure(p.mode)
        try:
            if p.mode == "chatgpt":
                if not page.url.startswith(("https://chatgpt.com", "https://auth.openai.com",
                                           "https://accounts.google.com", "https://appleid.apple.com")):
                    await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=35000)
            elif p.url:
                url = checked_url(p.url)
                await asyncio.to_thread(resolve_public_host, urlsplit(url).hostname)
                await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            await contexts[p.mode].storage_state(path=str(PROFILE_ROOT / p.mode / "storage-state.json"))
            return {"mode": p.mode, "url": page.url, "viewport": [WIDTH, HEIGHT]}
        except Exception as exc:
            raise HTTPException(502, "Navigation error: " + str(exc)[:240])

@router.post("/action")
async def interact(p: Command):
    check_mode(p.mode)
    if p.action not in ("click", "scroll", "type", "key", "back", "forward", "reload", "navigate"):
        raise HTTPException(400, "Unknown action")
    async with locks[p.mode]:
        page = await ensure(p.mode)
        try:
            if p.action == "click":
                await page.mouse.click(max(0, min(WIDTH - 1, p.x)), max(0, min(HEIGHT - 1, p.y)))
            elif p.action == "scroll":
                await page.mouse.wheel(0, max(-1400, min(1400, p.delta)))
            elif p.action == "type":
                await page.keyboard.insert_text(p.text)
            elif p.action == "key":
                if p.key not in ("Enter", "Tab", "Backspace", "Escape", "ArrowDown",
                                 "ArrowUp", "ArrowLeft", "ArrowRight", "ControlOrMeta+A"):
                    raise HTTPException(400, "Key not allowed")
                await page.keyboard.press(p.key)
            elif p.action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=20000)
            elif p.action == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=20000)
            elif p.action == "reload":
                await page.reload(wait_until="domcontentloaded", timeout=30000)
            elif p.action == "navigate":
                if p.mode == "chatgpt":
                    raise HTTPException(403, "Use Browser mode for arbitrary URLs")
                url = checked_url(p.url)
                await asyncio.to_thread(resolve_public_host, urlsplit(url).hostname)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await contexts[p.mode].storage_state(path=str(PROFILE_ROOT / p.mode / "storage-state.json"))
            return {"mode": p.mode, "url": page.url}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, "Browser action failed: " + str(exc)[:240])

@router.get("/frame")
async def frame(mode: str = Query("chatgpt"), quality: int = Query(45, ge=20, le=70)):
    check_mode(mode)
    async with locks[mode]:
        page = await ensure(mode)
        try:
            result = await page.screenshot(type="jpeg", quality=quality, animations="disabled")
            return Response(result, media_type="image/jpeg",
                            headers={"Cache-Control": "no-store, max-age=0"})
        except Exception as exc:
            raise HTTPException(502, "Frame failed: " + str(exc)[:240])

@router.get("/status")
async def status():
    return {"chatgpt": "running" if "chatgpt" in pages and not pages["chatgpt"].is_closed() else "idle",
            "browser": "running" if "browser" in pages and not pages["browser"].is_closed() else "idle",
            "viewport": {"width": WIDTH, "height": HEIGHT}}
