# kaist-openconnect

[한국어](README.md) | **English**

A small, dependency-free command-line client for connecting to the **KAIST VPN**
(Ivanti Connect Secure + AirCUVE "2Auth" two-factor) entirely from the terminal —
no browser required.

It prompts for your ID, password, and one-time code (SMS or email), completes the
two-factor handshake, and then brings the tunnel up with
[OpenConnect](https://www.infradead.org/openconnect/).

## Install (Windows, Linux, macOS)

### Linux / macOS

Paste this one line into your terminal — it installs everything you need
(Homebrew on macOS if missing, plus OpenConnect) and links `kvpn` onto your
`PATH`:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/seo-rii/kaist-openconnect/main/install.sh)"
```

Then just run `kvpn`. It skips anything already installed, so it's safe to
re-run — re-running also updates kvpn to the latest version. On Linux it uses
your distribution's package manager (apt/dnf/pacman/zypper/apk) for the
dependencies.

### Windows

First install [Python 3](https://www.python.org/downloads/windows/). Download
the official [OpenConnect 9.21 Windows build ZIP](https://gitlab.com/openconnect/openconnect/-/jobs/artifacts/v9.21/download?job=MinGW64%2FGnuTLS),
extract it, and run `openconnect-installer-MinGW64-GnuTLS-v9.21.exe` to install
OpenConnect and its Wintun driver. Then run this in a normal PowerShell to
install `kvpn` on your user `PATH`:

```powershell
irm https://raw.githubusercontent.com/seo-rii/kaist-openconnect/main/install.ps1 | iex
```

Open an **Administrator PowerShell or Command Prompt** to run `kvpn`, because
creating the tunnel device requires elevated rights. If OpenConnect is in a
nonstandard location, set `KVPN_OPENCONNECT` to the full path of
`openconnect.exe` before running kvpn.

<details>
<summary>Manual install (if you'd rather not run the installer)</summary>

Install the [requirements](#requirements) yourself, then:

```sh
git clone https://github.com/seo-rii/kaist-openconnect.git
cd kaist-openconnect
chmod +x kvpn
./kvpn
```

On Windows, run `./install.ps1` from the checkout, then run `kvpn` in an
Administrator terminal.

Optionally put it on your `PATH`:

```sh
ln -s "$PWD/kvpn" /usr/local/bin/kvpn
```

</details>

Set a default ID so you can just press Enter at the prompt:

```sh
export KVPN_USER=your_id   # add to ~/.zshrc or ~/.bashrc
```

![A full kvpn session: ID/password/realm prompts, SMS one-time code, Keychain storage offer, and OpenConnect bringing up the tunnel](docs/screenshot.png)

With stored credentials, later runs skip straight to the code prompt:

```
$ ./kvpn
=== KAIST VPN (kvpn) ===
Using stored credentials for your_id (KAIST Members). Run `kvpn --forget` to remove.
Send code via:
  1) SMS (default)
  2) Email
Choice [1]:
```

## Why

KAIST's VPN uses Ivanti Connect Secure with an AirCUVE second factor whose OTP
step runs inside a JavaScript portal on a separate host. OpenConnect on its own
can't drive that portal, so the usual advice is "log in with a browser, copy the
`DSID` cookie, then run openconnect." This tool automates that whole dance: it
performs the portal's OTP flow over plain HTTP and hands the resulting session
cookie to OpenConnect for you.

**It does not bypass anything.** You still authenticate with your own password and
a fresh one-time code on every connection — exactly like the official client.

## Requirements

- **Python 3** (standard library only — no `pip install`)
- **[OpenConnect](https://www.infradead.org/openconnect/)** on your `PATH`
  (`brew install openconnect` on macOS)
- administrator rights (`sudo` or an Administrator terminal on Windows;
  OpenConnect needs them to create the tunnel interface)

Linux uses the `vpnc-script` supplied by its OpenConnect package. Windows uses
Wintun and `vpnc-script-win.js` from the official OpenConnect installer.

## Usage

Run `./kvpn` and follow the prompts. To disconnect, press **Ctrl-C** in the
terminal running it — OpenConnect tears down the tunnel and restores your routes.

### Stored credentials

After a successful login, kvpn offers to store your credentials so future runs
jump straight to the "Send code via" prompt. The password goes into the
**macOS Keychain** on macOS and **Windows Credential Manager** on Windows. Your
ID and realm go into `~/.config/kvpn/config.json` on macOS/Linux and
`%APPDATA%\kvpn\config.json` on Windows. On Linux, where no native credential
store is assumed, the password is kept in the user-only (`0600`) config file
instead (kvpn warns you first). A fresh one-time code is still required on every
connection.

To remove everything that was stored:

```sh
./kvpn --forget
```

Set `KVPN_DEBUG=1` to print HTTP diagnostics to stderr for initialization, code
requests, and verification. These include status codes, response type and length,
JSON structure, and known error-page signals:

```sh
KVPN_DEBUG=1 ./kvpn
```

In Windows PowerShell, set `KVPN_DEBUG_LOG` to save diagnostics separately while
keeping interactive prompts usable. Setting the file path alone enables logging:

```powershell
$env:KVPN_DEBUG_LOG = Join-Path $env:TEMP ("kvpn-debug-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
kvpn
Get-Content -LiteralPath $env:KVPN_DEBUG_LOG
```

Share the resulting `[kvpn-debug]` lines after reproducing the error. Request
bodies, cookie values, response string/number values, URL queries, and authentication
tokens are omitted. Raw HTTP bodies and full terminal transcripts are not needed.
Run `Remove-Item Env:\KVPN_DEBUG_LOG` to disable file logging. Logs append as UTF-8
and use user-only (`0600`) permissions on Linux/macOS.

Diagnostic version 3 adds a `primary-auth` event with `phase: "submitted"` containing
actual login-form presence, known field names, error-region classifications such as
`invalid-credentials`, `invalid-request`, or `unknown-error`, and presence-only
checks for `DSSIGNIN`/`DSID` cookies. Field values and original error text are never
recorded. `submitted` means the request completed, not that authentication succeeded;
an empty `errors` list does not establish success either.

## How it works

The login is a chain across two hosts — the Ivanti gateway (`kvpn.kaist.ac.kr`)
and the AirCUVE portal (`kvpnportal.kaist.ac.kr:8443`):

1. `GET kvpn.kaist.ac.kr/` — obtain the Ivanti sign-in session.
2. `GET portal /view/redirectVPN` — mint a portal session and correlation code.
3. `POST login.cgi` with username, password, realm, and the full handshake as
   `password#2` — perform primary authentication without requiring a DSID yet.
4. `GET portal /view/onepassCheck` → `/vpnInit` — pass only the correlation suffix
   (not the handshake prefix), check primary authentication, and set the OTP context.
5. `GET portal /oauth/authorize` — register the OAuth request as Spring Security's
   "saved request" so the post-OTP redirect returns to the OAuth flow.
   Reproduce `/request`'s JavaScript-created `POST /view/redirect` and verify that
   the OTP menu is reached. Invalid-access and expired-session pages stop the flow.
6. `POST portal /api/portal` (`cmd=AuthPortal.twoAuthSend`) — send the SMS/email code.
7. `POST portal /j_spring_security_check.do` — verify the code; Spring redirects
   through `/oauth/authorize` → `/vpn/<client_id>?code=…`.
8. That page exposes a `message` token, which becomes Ivanti's `password#2`.
9. `POST login.cgi` with username, password, realm, and `password#2` → a `DSID`
   session cookie.
10. `sudo openconnect --protocol=nc --cookie-on-stdin kvpn.kaist.ac.kr` — the DSID
    is passed on stdin so it never appears in the process list.

## Notes & troubleshooting

- **Email/SMS code did not arrive?** kvpn asks for a code only after the portal
  accepts the request with `success: "true"`. `emailNull` or `phoneNumberNull`
  means the portal has no registered contact of that type. Check the same account
  in the [official VPN portal](https://kvpn.kaist.ac.kr/). `Portal accepted` confirms
  request acceptance, not delivery to your inbox. Check the `Error:` message if
  the request fails.
- **`invalid-access` at `onepassCheck` in the log?** Initialization failed before
  code delivery. Run the installer again to update. Updated logs show
  `diagnostics_version: 3`, a `POST login.cgi` before `onepassCheck`, and a
  `portal-init` event with `phase: "otp-ready"` after the OTP menu is confirmed.
  If it still fails, collect the new log and the `Error:` message, and check whether
  the official browser portal reaches OTP on the same PC, account, and realm.
  This response alone does not prove an incorrect password. The reported rejection
  with a real account remains unresolved.
- **Test coverage:** CI uses simulated portal responses to check initialization
  ordering and failure handling, accepted and rejected send requests, and
  Email (`otp_flag=2`)/SMS (`otp_flag=1`) verification.
  It does not test mail delivery or VPN connections with a real KAIST account.
- **Credential storage is opt-in.** Nothing is saved unless you answer "y" at
  the store prompt; `kvpn --forget` removes it all. The `DSID` is ephemeral
  either way (it dies when you disconnect), and a fresh one-time code is
  required on every connection.
- **Stored password went stale?** If your KAIST password changes, initial or final
  authentication will fail — run `kvpn --forget` and log in again.
- **Linux/macOS `sudo` prompt collision:** if `sudo` misbehaves because stdin is piped, run
  `sudo -v` first, then `./kvpn`.
- **OpenConnect not found on Windows:** set `KVPN_OPENCONNECT` to the full path
  of `openconnect.exe`. The standard official install location under
  `C:\Program Files\OpenConnect` is detected automatically.
- **Harmless route warnings:** on connect you may see two lines like
  `Can't assign requested address` / `File exists` for a route to your own VPN IP
  or an already-present route. Every other route still installs; this doesn't
  affect connectivity.
- **If login suddenly breaks**, KAIST likely changed the portal flow. Run with
  `KVPN_DEBUG=1` and open an issue with the (redacted) hop list.

## Disclaimer

This is an unofficial, personal interoperability tool. It is **not affiliated with
or endorsed by KAIST, Ivanti, or AirCUVE**. Use it with your own account and in
accordance with your institution's acceptable-use policy. Provided "as is" without
warranty of any kind (see [LICENSE](LICENSE)).

## Acknowledgements

Built on top of the excellent [OpenConnect](https://www.infradead.org/openconnect/)
project, which does the actual VPN tunneling.
