# IOC 빌드와 통합 운용

## 범위

이 문서는 EPICS IOC를 빌드하고 실제 장비 설정을 검토한 뒤 IOC, 축 설정 적용기와 GUI를
통합 launcher로 운용하는 절차를 설명한다. Python/EPICS 의존성 설치는
[`12-environment-setup.md`](12-environment-setup.md), 축과 모델 설정은
[`04-stage-model-configuration.md`](04-stage-model-configuration.md)를 먼저 따른다.

## EPICS 빌드 경로

검증한 조합은 EPICS Base 7.0.7, asyn R4-44-2, motor R7-3-1이다. 다른 컴퓨터에서는
Git 추적 파일을 바꾸지 않고 `configure/RELEASE.local`에 설치 경로를 둔다.

```make
SUPPORT = /usr/local/epics/synApps/support
ASYN = $(SUPPORT)/asyn-R4-44-2
MOTOR = $(SUPPORT)/motor-R7-3-1
EPICS_BASE = /usr/local/epics/base-7.0.7
```

저장소 최상위에서 빌드한다.

```bash
make -j2
```

EPICS 경로나 저장소 절대 경로가 달라졌다면 기존 산출물의 RUNPATH와 `envPaths`가 남을
수 있으므로 다시 빌드한다.

```bash
make clean
make -j2
```

기본 architecture에서 IOC 실행 파일은 `bin/linux-x86_64/kohzuAriesLynx`에 생성된다.

## 로컬 운용 설정

다음 파일은 Git에서 제외되며 장비별 실제 값을 보존한다.

```text
config/runtime.ini
config/axis-assignments.ini
configure/RELEASE.local
```

로컬 INI가 없으면 launcher가 추적되는 `.example.ini`를 한 번 복사하며 기존 설정은
덮어쓰지 않는다. 수동으로 생성하려면 다음을 실행한다.

```bash
python3 tools/initialize_local_config.py
```

운전 전에 최소한 다음 값을 확인한다.

- `controller.host`, `controller.port`: 실제 ARIES TCP endpoint
- `epics.prefix`, `epics.bin`, `epics.ca_addr_list`: IOC와 CA 도구 설정
- `python.executable`: runtime 또는 development 환경의 절대 Python 경로
- `gui.listen`, `gui.port`: GUI bind 주소와 포트
- 각 축의 모델, 방향, HOME method와 초기 `enabled` 상태

`127.0.0.1` bind는 서버 컴퓨터에서만 접속할 수 있다. LAN 접속은 서버 LAN IP 또는
`0.0.0.0`으로 bind하고 브라우저에서는 서버의 실제 LAN IP로 접속한다. GUI에는 사용자
인증과 TLS가 없으므로 non-loopback bind는 격리된 신뢰 네트워크에서만 사용한다.

## 통합 launcher

빌드와 설정 검토 후 저장소 최상위에서 실행한다.

```bash
./start_kohzu_control.sh
```

launcher는 다음 순서를 책임진다.

1. 기존 IOC·GUI 중복 프로세스 검사
2. IOC 시작과 PV 준비 대기
3. `axis-assignments.ini`의 모델 설정 적용
4. GUI 시작과 HTTP 준비 확인
5. IOC, 적용기, GUI 로그의 실시간 통합 출력

기본 GUI 주소는 `http://127.0.0.1:8080`이다. 실행 옵션은 다음으로 확인한다.

```bash
./start_kohzu_control.sh --help
```

일반적인 CA/TCP 연결에는 root 권한이 필요 없다. 환경상 IOC에만 sudo가 필요한 경우에만
`--sudo`를 사용한다. Ctrl-C를 한 번 누르면 GUI가 진행 중 요청을 정리하고 활성 패널
축을 Disable한 뒤 IOC를 종료한다.

## 로그 확인

실행별 로그는 다음 위치에 보존된다.

```text
logs/kohzu-control/<YYYYMMDD-HHMMSS-PID>/
```

`latest` symlink가 마지막 실행을 가리킨다.

```bash
less logs/kohzu-control/latest/session.log
tail -F logs/kohzu-control/latest/session.log
```

`ioc.log`, `apply.log`, `gui.log`, `launcher.log`에는 원본 출력이, `session.log`에는 시간과
source가 붙은 통합 이력이 기록된다. FIFO만 `/tmp/kohzu-control-runtime.*`에 생성되며
종료 시 제거된다.

## 수동 실행과 확인

통합 launcher 문제를 분리해서 확인해야 할 때만 IOC를 직접 실행한다.

```bash
cd iocBoot/iockohzuAriesLynx
../../bin/linux-x86_64/kohzuAriesLynx st.cmd
```

IOC shell은 `exit`로 정상 종료한다. 다른 터미널에서 최소 PV를 확인할 수 있다.

```bash
caget KOHZU:m1.RBV
caget KOHZU:m1.DMOV
caget KOHZU:Diag:LastErrorCode
```

GUI만 별도로 실행하는 방법과 LAN bind 주의점은
[`06-dynamic-gui-foundation.md`](06-dynamic-gui-foundation.md)에 기록되어 있다.

## Mock 회귀시험

실제 controller를 사용하지 않는 기본 회귀시험은 다음과 같다.

```bash
python -m pytest -q
./tests/run_mock_integration.sh
./tests/run_stage_apply_integration.sh
./tests/run_gui_integration.sh
```

통합시험은 loopback simulator와 `MOCK:`/`FIXED:` prefix를 사용한다. 동일한 PV prefix의
실제 IOC와 mock IOC를 동시에 실행하지 않는다.
