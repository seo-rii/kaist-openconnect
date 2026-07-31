# kaist-openconnect

**한국어** | [English](README.en.md)

브라우저 없이 터미널에서 바로 **KAIST VPN**(Ivanti Connect Secure + AirCUVE
"2Auth" 2단계 인증)에 접속하는, 의존성 없는 작은 명령줄 클라이언트입니다.

ID, 비밀번호, 일회용 코드(SMS 또는 이메일)를 입력받아 2단계 인증을 완료한 뒤
[OpenConnect](https://www.infradead.org/openconnect/)로 터널을 엽니다.

![kvpn 전체 세션: ID/비밀번호/realm 입력, SMS 일회용 코드, 키체인 저장 여부 확인, OpenConnect 터널 연결](docs/screenshot.png)

자격 증명을 저장해 두면 이후 실행에서는 곧바로 코드 입력 단계로 넘어갑니다:

```
$ ./kvpn
=== KAIST VPN (kvpn) ===
Using stored credentials for your_id (KAIST Members). Run `kvpn --forget` to remove.
Send code via:
  1) SMS (default)
  2) Email
Choice [1]:
```

## 왜 만들었나

KAIST VPN은 Ivanti Connect Secure에 AirCUVE 2차 인증을 얹은 구조인데, OTP 단계가
별도 호스트의 JavaScript 포털 안에서 동작합니다. OpenConnect 단독으로는 이 포털을
처리할 수 없어서, 흔한 해법은 "브라우저로 로그인해서 `DSID` 쿠키를 복사한 다음
openconnect를 실행하라"는 것이었습니다. 이 도구는 그 과정 전체를 자동화합니다:
포털의 OTP 흐름을 순수 HTTP로 수행하고, 얻은 세션 쿠키를 OpenConnect에
넘겨줍니다.

**아무것도 우회하지 않습니다.** 공식 클라이언트와 똑같이, 매 접속마다 본인의
비밀번호와 새 일회용 코드로 인증합니다.

## 요구 사항

- **Python 3** (표준 라이브러리만 사용 — `pip install` 불필요)
- **[OpenConnect](https://www.infradead.org/openconnect/)** — `PATH`에 있어야
  합니다 (macOS에서는 `brew install openconnect`)
- `sudo` 권한 (OpenConnect가 터널 인터페이스를 만들려면 root가 필요합니다)

macOS에서 개발·테스트했습니다. Linux에서도 OpenConnect 기본 `vpnc-script`로
동작할 것으로 예상합니다; 제보 환영합니다.

## 설치

터미널에 아래 한 줄을 붙여넣으면 끝입니다 — Homebrew(macOS, 없을 때만)와
OpenConnect까지 필요한 것을 전부 설치하고, `kvpn`을 `PATH`에 연결합니다:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/predict-woo/kaist-openconnect/main/install.sh)"
```

이미 설치된 것은 건너뛰므로 다시 실행해도 안전하며, 다시 실행하면 kvpn이 최신
버전으로 갱신됩니다. Linux에서는 배포판 패키지 관리자(apt/dnf/pacman/zypper)로
의존성을 설치합니다.

<details>
<summary>수동 설치 (설치 스크립트를 쓰고 싶지 않다면)</summary>

[요구 사항](#요구-사항)을 직접 설치한 뒤:

```sh
git clone https://github.com/predict-woo/kaist-openconnect.git
cd kaist-openconnect
chmod +x kvpn
./kvpn
```

원한다면 `PATH`에 추가하세요:

```sh
ln -s "$PWD/kvpn" /usr/local/bin/kvpn
```

</details>

기본 ID를 설정해 두면 프롬프트에서 Enter만 누르면 됩니다:

```sh
export KVPN_USER=your_id   # ~/.zshrc 또는 ~/.bashrc 에 추가
```

## 사용법

`./kvpn`을 실행하고 프롬프트를 따라가면 됩니다. 연결을 끊으려면 실행 중인
터미널에서 **Ctrl-C** 를 누르세요 — OpenConnect가 터널을 정리하고 라우팅을
복원합니다.

### 자격 증명 저장

로그인에 성공하면 kvpn이 자격 증명 저장을 제안하며, 저장해 두면 이후 실행은
곧바로 "Send code via" 단계로 넘어갑니다. 비밀번호는 **macOS 키체인**(서비스명
`kvpn`)에, ID와 realm은 `~/.config/kvpn/config.json`(사용자 전용, `0600`)에
저장됩니다. 키체인이 없는 시스템에서는 비밀번호도 같은 `0600` 파일에 저장됩니다
(저장 전에 경고를 띄웁니다). 어느 경우든 일회용 코드는 매 접속마다 새로
필요합니다.

저장된 내용을 모두 삭제하려면:

```sh
./kvpn --forget
```

`KVPN_DEBUG=1`을 설정하면 내부 HTTP 리다이렉트 체인을 출력합니다(로그인 흐름이
바뀌어 뭔가 깨졌을 때 유용합니다):

```sh
KVPN_DEBUG=1 ./kvpn
```

## 동작 원리

로그인은 두 호스트 — Ivanti 게이트웨이(`kvpn.kaist.ac.kr`)와 AirCUVE
포털(`kvpnportal.kaist.ac.kr:8443`) — 를 오가는 체인입니다:

1. `GET kvpn.kaist.ac.kr/` — Ivanti 로그인 세션을 얻습니다.
2. `GET portal /view/redirectVPN` — 포털 세션과 correlation code를 발급받습니다.
3. `GET portal /view/onepassCheck` → `/vpnInit` — OTP 컨텍스트를 설정합니다.
4. `GET portal /oauth/authorize` — OAuth 요청을 Spring Security의 "saved
   request"로 등록해, OTP 이후 리다이렉트가 OAuth 흐름으로 돌아오게 합니다.
5. `POST portal /api/portal` (`cmd=AuthPortal.twoAuthSend`) — SMS/이메일 코드를
   발송합니다.
6. `POST portal /j_spring_security_check.do` — 코드를 검증하면 Spring이
   `/oauth/authorize` → `/vpn/<client_id>?code=…` 로 리다이렉트합니다.
7. 그 페이지가 노출하는 `message` 토큰이 Ivanti의 `password#2`가 됩니다.
8. `POST login.cgi` — username, password, realm, `password#2`를 보내면 `DSID`
   세션 쿠키를 받습니다.
9. `sudo openconnect --protocol=nc --cookie-on-stdin kvpn.kaist.ac.kr` — DSID를
   stdin으로 전달해 프로세스 목록에 노출되지 않게 합니다.

## 참고 및 문제 해결

- **자격 증명 저장은 선택(opt-in)입니다.** 저장 프롬프트에서 "y"라고 답하지 않는
  한 아무것도 저장되지 않으며, `kvpn --forget`으로 전부 삭제할 수 있습니다.
  `DSID`는 어차피 일시적이고(연결이 끊기면 소멸), 일회용 코드는 매 접속마다 새로
  필요합니다.
- **저장된 비밀번호가 낡았다면?** KAIST 비밀번호를 바꾸면 마지막 로그인 단계가
  실패합니다 — `kvpn --forget` 후 다시 로그인하세요.
- **`sudo` 프롬프트 충돌:** stdin이 파이프로 연결된 탓에 `sudo`가 오작동하면
  `sudo -v`를 먼저 실행한 뒤 `./kvpn`을 실행하세요.
- **무해한 라우트 경고:** 접속 시 자기 VPN IP로의 라우트나 이미 존재하는 라우트에
  대해 `Can't assign requested address` / `File exists` 같은 줄이 보일 수
  있습니다. 나머지 라우트는 모두 정상적으로 설치되며 연결에는 영향이 없습니다.
- **로그인이 갑자기 깨졌다면** KAIST가 포털 흐름을 바꿨을 가능성이 큽니다.
  `KVPN_DEBUG=1`로 실행해 (민감한 정보를 가린) hop 목록과 함께 이슈를 올려주세요.

## 면책 조항

이 도구는 비공식 개인 상호운용성(interoperability) 도구이며, **KAIST, Ivanti,
AirCUVE와 무관하고 이들의 승인을 받지 않았습니다**. 본인 계정으로, 소속 기관의
이용 정책에 맞게 사용하세요. 어떤 종류의 보증도 없이 "있는 그대로" 제공됩니다
([LICENSE](LICENSE) 참조).

## 감사의 말

실제 VPN 터널링을 담당하는 훌륭한
[OpenConnect](https://www.infradead.org/openconnect/) 프로젝트 위에
만들어졌습니다.
