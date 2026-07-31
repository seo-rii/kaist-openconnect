# kaist-openconnect

A small, dependency-free command-line client for connecting to the **KAIST VPN**
(Ivanti Connect Secure + AirCUVE "2Auth" two-factor) entirely from the terminal —
no browser required.

It prompts for your ID, password, and one-time code (SMS or email), completes the
two-factor handshake, and then brings the tunnel up with
[OpenConnect](https://www.infradead.org/openconnect/).

```
$ ./kvpn
=== KAIST VPN (kvpn) ===
KAIST ID: your_id
Password:
Realm:
  1) KAIST Members (default)
  2) Visitors
  3) Graduates
Choice [1]:
Send code via:
  1) SMS (default)
  2) Email
Choice [1]:
Code sent via SMS. It may take up to a minute to arrive.
Enter the code: 123456
Authenticated. DSID acquired.
Store these credentials in the macOS Keychain for future logins? [y/N]: y
Stored in the macOS Keychain (id/realm in ~/.config/kvpn/config.json). Run `kvpn --forget` to remove.

Bringing up the tunnel (sudo will prompt for your Mac password)...
...
ESP session established with server
```

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
- `sudo` rights (OpenConnect needs root to create the tunnel interface)

Developed and tested on macOS. It should work on Linux with OpenConnect's default
`vpnc-script`; reports welcome.

## Install

```sh
git clone https://github.com/predict-woo/kaist-openconnect.git
cd kaist-openconnect
chmod +x kvpn
./kvpn
```

Optionally put it on your `PATH`:

```sh
ln -s "$PWD/kvpn" /usr/local/bin/kvpn
```

Set a default ID so you can just press Enter at the prompt:

```sh
export KVPN_USER=your_id   # add to ~/.zshrc or ~/.bashrc
```

## Usage

Run `./kvpn` and follow the prompts. To disconnect, press **Ctrl-C** in the
terminal running it — OpenConnect tears down the tunnel and restores your routes.

### Stored credentials

After a successful login, kvpn offers to store your credentials so future runs
jump straight to the "Send code via" prompt. The password goes into the
**macOS Keychain** (service `kvpn`); your ID and realm go into
`~/.config/kvpn/config.json` (user-only, `0600`). On systems without a
Keychain, the password is kept in that same `0600` file instead (kvpn warns
you first). A fresh one-time code is still required on every connection.

To remove everything that was stored:

```sh
./kvpn --forget
```

Set `KVPN_DEBUG=1` to print the internal HTTP redirect chain (useful if the login
flow changes and something breaks):

```sh
KVPN_DEBUG=1 ./kvpn
```

## How it works

The login is a chain across two hosts — the Ivanti gateway (`kvpn.kaist.ac.kr`)
and the AirCUVE portal (`kvpnportal.kaist.ac.kr:8443`):

1. `GET kvpn.kaist.ac.kr/` — obtain the Ivanti sign-in session.
2. `GET portal /view/redirectVPN` — mint a portal session and correlation code.
3. `GET portal /view/onepassCheck` → `/vpnInit` — set the OTP context.
4. `GET portal /oauth/authorize` — register the OAuth request as Spring Security's
   "saved request" so the post-OTP redirect returns to the OAuth flow.
5. `POST portal /api/portal` (`cmd=AuthPortal.twoAuthSend`) — send the SMS/email code.
6. `POST portal /j_spring_security_check.do` — verify the code; Spring redirects
   through `/oauth/authorize` → `/vpn/<client_id>?code=…`.
7. That page exposes a `message` token, which becomes Ivanti's `password#2`.
8. `POST login.cgi` with username, password, realm, and `password#2` → a `DSID`
   session cookie.
9. `sudo openconnect --protocol=nc --cookie-on-stdin kvpn.kaist.ac.kr` — the DSID
   is passed on stdin so it never appears in the process list.

## Notes & troubleshooting

- **Credential storage is opt-in.** Nothing is saved unless you answer "y" at
  the store prompt; `kvpn --forget` removes it all. The `DSID` is ephemeral
  either way (it dies when you disconnect), and a fresh one-time code is
  required on every connection.
- **Stored password went stale?** If your KAIST password changes, the final
  login step will fail — run `kvpn --forget` and log in again.
- **`sudo` prompt collision:** if `sudo` misbehaves because stdin is piped, run
  `sudo -v` first, then `./kvpn`.
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
