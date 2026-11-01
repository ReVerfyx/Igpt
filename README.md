# iGPT — iPad 1 remote client

iGPT is a small UIKit/iOS 5 client that shows JPEG frames from a VPS. It does
not embed ChatGPT, YouTube or a modern browser in UIWebView. ChatGPT is opened
at `chatgpt.com` in Chromium on the VPS; the owner signs in there themselves.
No OpenAI API key is used or required for that mode.

## Fast test (HTTP only on a private LAN)

HTTP is intentionally a client-visible test mode. It is not safe on the public
Internet: its access token and frames are readable by the network. It must not
be used to submit passwords. For public use put the service behind nginx with a
valid HTTPS certificate; the client does not bypass certificate validation.

On the VPS, copy this repository to `/opt/igpt`, then run:

```sh
export IGPT_TOKEN="$(openssl rand -hex 32)"
cd /opt/igpt
sudo -E server/install-ubuntu24.sh
```

The systemd unit runs as the unprivileged `igpt` account and binds only to
localhost. Add a reverse proxy for HTTPS. Set `IGPT_PUBLIC_URL` to that HTTPS
origin before enabling video playback; signed video URLs cannot be generated
over HTTP.

In the app, open Settings and enter `https://your-domain` (or the explicit
`http://` test address) and the generated bridge token. This token is held only
in memory; it is not the root/SSH password.

## Operating notes

- Run `playwright install chromium` as `igpt`; do not run the service as root.
- `IGPT_HEADLESS=0` uses normal Chromium and requires a configured graphical
  display. This is the fallback if ChatGPT declines a headless browser. The
  project does not bypass CAPTCHA or login protection.
- Browser and ChatGPT have separate persisted cookie storage but share one
  Chromium process. The included browser route blocks URL navigation to private
  and loopback addresses; deploy an egress firewall as additional protection.
- YouTube search tries every configured Invidious source. Availability and
  compatible MP4 streams vary, so self-hosted sources are recommended. The
  proxy preserves `Range` responses for seeking.
- The `/term` endpoint executes only as `igpt`, never root. Codex is optional;
  if its CLI is absent the client receives a clear 503 response.

## Build and install

GitHub Actions produces `client/packages/*.deb`. To install on a jailbroken
iPad 1, transfer it through iFile and tap Install, or run `dpkg -i FILE.deb`
over SSH on the device. The package targets iOS 5.0+ and ARMv7.
