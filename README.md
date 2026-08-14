# KOHZU EPICS Control Test

KOHZU 모터 스테이지를 EPICS 7, synApps motor, Bluesky/Ophyd 및 EPICS
Archiver Appliance와 단계적으로 연동하기 위한 프로젝트다.

현재 목표 연결 구성은 다음과 같다.

```text
GUI / Bluesky(Ophyd)
        |
   EPICS motor record
        |
ARIES/LYNX용 Model 3 드라이버
        |
 asyn + Ethernet/TCP
        |
 ARIES -- Motionnet -- LYNX
        |                |
     TITAN-A2         TITAN-A2
        |                |
  KOHZU stage       KOHZU stage
```

## 확정된 조건

- EPICS Base: `/usr/local/epics/base-7.0.7`
- synApps support: `/usr/local/epics/synApps/support`
- motor module: `/usr/local/epics/synApps/support/motor-R7-3-1`
- PC와 ARIES는 Ethernet/TCP로 통신한다.
- 기본 TCP 서버 주소는 장비 설정을 확인하여 IOC 시작 파일에 지정한다.
- ARIES 매뉴얼의 기본 TCP 포트는 `12321`이다.
- 기본 운용 축은 5개이며 최대 32축까지 확장 가능한 구조로 설계한다.
- 기존 `motorKohzu`의 SC 시리즈 드라이버는 사용하지 않는다.
- `asynMotorController`와 `asynMotorAxis` 기반 Model 3 드라이버를 새로 구현한다.
- 이동 때마다 ARIES speed table `0`을 현재 motor record의 속도·가속도에 맞춰 갱신한다.
- 컨트롤러와 모든 TITAN-A2 드라이버 박스는 `M1` 선택 상태로 운용한다.
- TITAN-A2의 M1은 공장 기본 스위치 위치 `1`, 즉 2분할(half-step)을 유지한다.
- 정상 운전 범위는 motor record의 `HLM/LLM`으로 제한한다.
- ARIES controller soft limit은 IOC가 설정하거나 강제로 변경하지 않고 공장 기본값을 유지한다.
- 센서 구성과 원점 복귀 방법은 스테이지 모델에 고정하지 않고 축별로 사용자가 선택한다.
- GUI 패널은 동적으로 생성·삭제하되 IOC의 축 객체와 motor record는 유지한다.
- 스테이지 모델 변경은 축 정지, 설정 검증, 저속 시험 및 재원점 복귀 절차를 요구한다.

## 문서

- [`documents/ARIES_LYNX_manual_Rev1.43_en.pdf`](documents/ARIES_LYNX_manual_Rev1.43_en.pdf): ARIES/LYNX 제조사 매뉴얼
- [`documents/TITAN-A2_manual_rev1.11_en.pdf`](documents/TITAN-A2_manual_rev1.11_en.pdf): TITAN-A2 제조사 매뉴얼
- [`docs/01-aries-lynx-protocol-analysis.md`](docs/01-aries-lynx-protocol-analysis.md): 프로토콜 분석과 드라이버 설계 기준
- [`docs/02-implementation-progress.md`](docs/02-implementation-progress.md): 구현 범위와 검증 결과 기록
- [`docs/03-motor-unit-conversion.md`](docs/03-motor-unit-conversion.md): motor record에서 ARIES까지의 단위 변환
- [`docs/04-stage-model-configuration.md`](docs/04-stage-model-configuration.md): 모델 catalog와 32축 할당 형식
- [`docs/05-test-stage-specifications.md`](docs/05-test-stage-specifications.md): 시험용 5축 공식 사양과 초기 설정 근거
- [`docs/06-dynamic-gui-foundation.md`](docs/06-dynamic-gui-foundation.md): 동적 축 패널 GUI 구조와 안전 범위
- [`docs/07-real-controller-commissioning.md`](docs/07-real-controller-commissioning.md): 실제 controller 읽기 전용 확인과 시운전 기록
- [`docs/08-ophyd-bluesky-basics.md`](docs/08-ophyd-bluesky-basics.md): Ophyd 설치, EPICS motor 연결 및 Bluesky 기초 사용법
- [`docs/09-ophyd-bluesky-integration-log.md`](docs/09-ophyd-bluesky-integration-log.md): 실제 IOC와 Ophyd/Bluesky의 단계별 연동 시험 기록
- [`docs/10-fixed-point-kinematics.md`](docs/10-fixed-point-kinematics.md): 5축 고정점 운동의 이상적 기구 모델, 변환식 및 시험 계획
- [`docs/11-python-module-roles.md`](docs/11-python-module-roles.md): `kohzu_kinematics`, `kohzu_ophyd`, `tools`의 파일별 역할과 호출 관계
- [`documents/stage-specifications/`](documents/stage-specifications/): KOHZU 공식 모델 사양 PDF와 검토용 추출문

## 새 환경에서 IOC 설정, 빌드 및 실행

### 간편 실행

빌드와 설정이 끝난 현재 장비에서는 저장소 최상위에서 다음 명령 하나로 IOC, persistent
axis assignment 적용과 GUI를 순서대로 시작할 수 있다.

```bash
./start_kohzu_control.sh
```

기본적으로 IOC와 GUI 모두 현재 사용자로 실행한다. EPICS CA port와 controller TCP
연결에는 root 권한이 필요하지 않다. 특별한 시스템 설정 때문에 IOC에 sudo가 필요한
경우에만 다음을 사용한다.

```bash
./start_kohzu_control.sh --sudo
```

controller 주소, EPICS prefix/bin/CA 주소, Python 실행 파일과 GUI listen/port의 기본값은
[`config/runtime.ini`](config/runtime.ini)에 모여 있다. 모든 값은 launcher 옵션으로도
일시적으로 덮어쓸 수 있으며 `./start_kohzu_control.sh --help`에서 목록을 볼 수 있다.

기본 브라우저 주소는 `http://127.0.0.1:8080`이다. 종료할 때 launcher 터미널에서 Ctrl-C를
한 번 누르면 GUI가 먼저 활성 패널 축을 Disable하고 assignment를 저장한 뒤 IOC를
종료한다. 모든 실행 로그는 `logs/kohzu-control/<실행시각>-<PID>/`에 보존되고
`logs/kohzu-control/latest`가 마지막 실행을 가리킨다.

저장소 디렉터리를 옮기거나 이름을 바꾸면 EPICS 실행 파일의 RUNPATH와 `envPaths`가 이전
절대 경로를 가리킬 수 있다. `TOP ... was built with TOP ...` 경고 또는 shared library
오류가 나오면 현재 저장소 최상위에서 다시 빌드한다.

```bash
make clean
make -j2
```

별도의 자동 치환 스크립트는 사용하지 않는다. 새 컴퓨터에서는 EPICS support 경로와
IOC 시작 파일만 확인한다.

### 1. EPICS build 경로 설정

[`configure/RELEASE`](configure/RELEASE)에서 다음 네 경로를 설치 환경에 맞게
수정한다.

```make
SUPPORT = /usr/local/epics/synApps/support
ASYN = $(SUPPORT)/asyn-R4-44-2
MOTOR = $(SUPPORT)/motor-R7-3-1
EPICS_BASE = /usr/local/epics/base-7.0.7
```

- `EPICS_BASE`: EPICS Base 최상위 경로
- `SUPPORT`: synApps support 최상위 경로
- `ASYN`: 빌드할 asyn module 최상위 경로
- `MOTOR`: motor module 최상위 경로

각 경로에는 해당 module의 `configure`와 `include`, `lib` 등이 있어야 한다.
asyn과 motor가 서로 다른 support 경로에 설치됐다면 `SUPPORT`를 사용하지 않고
`ASYN`, `MOTOR`에 각각 절대 경로를 적어도 된다. `EPICS_BASE`는 RELEASE 파일의 support
module 정의보다 뒤에 둔다.

### 2. Controller 주소와 PV prefix 설정

[`iocBoot/iockohzuAriesLynx/st.cmd`](iocBoot/iockohzuAriesLynx/st.cmd)는 검증된 실제
controller 주소와 32축 DB load를 포함한다. 다른 환경에서는 주소와 prefix를 먼저
검토해 수정한다.

```text
drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

dbLoadTemplate("db/kohzuAriesLynxMotors.substitutions", "PREFIX=KOHZU:,MOTOR_PORT=KOHZU")
dbLoadRecords("db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU")
dbLoadTemplate("db/kohzuAriesLynxHomeDiagnostics.substitutions", "PREFIX=KOHZU:,MOTOR_PORT=KOHZU")

# DEVELOPMENT-ONLY: Bluesky와 GUI 개발 완료 전까지 사용
dbLoadTemplate("db/kohzuAriesLynxCommissioning.substitutions", "PREFIX=KOHZU:")
asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
```

- 첫 번째 port 이름 `KOHZU_TCP`는 TCP asyn port 이름이다.
- controller 이름 `KOHZU`는 motor record의 `MOTOR_PORT`와 같아야 한다.
- `10.1.101.51:12321`은 실제 controller의 `IP:port`다.
- `PREFIX=KOHZU:`를 바꾸면 `P=`, model 적용 명령의 `--prefix`도 같이 바꾼다.
- `32`는 생성할 최대 축 수다.
- `100`, `1000`은 각각 이동 중/정지 중 polling 주기(ms)다.

동일한 PV prefix를 제공하는 실제 IOC와 mock IOC를 동시에 실행하지 않는다.

### 3. 빌드

저장소 최상위에서 실행한다.

```bash
make
```

EPICS Base, asyn 또는 motor module 경로·버전을 변경했다면 기존 산출물을 지운 뒤 다시
빌드한다.

```bash
make clean
make
```

빌드가 성공하면 실행 파일은 일반적으로 다음 위치에 생성된다.

```text
bin/linux-x86_64/kohzuAriesLynx
```

다른 architecture에서는 `linux-x86_64` 부분이 해당 `EPICS_HOST_ARCH`로 바뀐다.

### 4. IOC 실행

```bash
cd iocBoot/iockohzuAriesLynx
../../bin/linux-x86_64/kohzuAriesLynx st.cmd
```

IOC shell의 `epics>` prompt에서 정상 종료하려면 다음을 입력한다.

```text
exit
```

실행 후 최소 확인:

```bash
caget KOHZU:m1.RBV
caget KOHZU:m1.DMOV
caget KOHZU:Diag:LastErrorCode
```

### 5. 선택 모델 검증 및 적용

32축 motor record는 substitutions로 항상 생성된다. 실제 모델 정보는
[`config/stage-models.ini`](config/stage-models.ini)와
[`config/axis-assignments.ini`](config/axis-assignments.ini)에서 관리한다.

먼저 controller에 쓰지 않는 검증과 dry-run을 실행한다.

```bash
python3 tools/validate_stage_config.py
python3 tools/stage_config_dry_run.py
```

실행 중인 IOC에 적용될 내용을 다시 확인한다.

```bash
python3 tools/stage_config_apply.py --prefix KOHZU:
```

IOC 시작 직후 선택 모델을 실제 적용한다.

```bash
python3 tools/stage_config_apply.py --prefix KOHZU: --apply
```

이 도구는 모델이 할당된 축의 `DESC`, `EGU`, `DIR`, `MRES`, `LLM/HLM`, `VMAX`,
`VELO`, `VBAS`, `ACCL`, `OriginMethod`를 `_able=Disable` 상태에서 적용한다. 최종
`_able` 상태는 assignment의 `enabled` 값을 따른다. `model` 항목이 존재하는 축은 설정
적용 대상이며 GUI 웹서버가 시작되면 저장된 모델 축을 Enable하고 패널을 복원한다.

commissioning PV, Ready flag와 access-security는 기본 학습용 end-to-end 프로파일에서
사용하지 않는다. 이전 안전 실험은 소스에 opt-in 형태로 남겨 두었다.

### 6. 고정점 궤적 검토 및 실행

`tools/fixed_point_run.py`는 Yaw 테이블 표면 중심 기준의 고정점 좌표(mm), 목표
Pitch/Yaw(deg), 실행 시간과 구간 수를 받는다. 기본은 snapshot을 읽고 연속 계산 목표와
`MRES/OFF/DIR`로 양자화한 실행 목표만 출력하는 read-only 모드다.

```bash
conda activate kohzu-bluesky
python tools/fixed_point_run.py \
  --prefix KOHZU: \
  --fixed-x 20 --fixed-y 0 --fixed-z 0 \
  --target-pitch 0.1 --target-yaw 0.1 \
  --duration 10 --intervals 100
```

출력된 궤적과 software limit를 확인한 뒤 같은 명령에 `--execute`를 추가하면 양자화된
표본을 Ophyd/Bluesky로 실행한다. 기본 프로파일은 모델이 할당된 1~5축의 `_able=Enable`
만 운전 gate로 사용하며 HOME이나 Enable을 자동 수행하지 않는다.

```bash
python tools/fixed_point_run.py \
  --prefix KOHZU: \
  --fixed-x 20 --fixed-y 0 --fixed-z 0 \
  --target-pitch 0.1 --target-yaw 0.1 \
  --duration 10 --intervals 100 --execute
```

이전 안전 실험의 Emergency/상태 검사, plan hash 승인과 실패 시 추가 STOP을 함께
시험하려는 경우에만 `--safety-checks`와 해당 승인 option을 사용한다. 기본 실행은
`EmergencyActive` PV를 연결하거나 요구하지 않는다.

Python 전체 회귀시험은 같은 환경에서 다음과 같이 실행한다.

```bash
EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1 \
python -m pytest -q
```

## 스테이지 모델 추가, 수정 및 삭제

### 모델 추가

[`config/stage-models.ini`](config/stage-models.ini)에 고유한 section을 추가한다.

```ini
[model:NEW_MODEL]
description = Manufacturer and model description
egu = mm
mres = 0.0005
low_limit = -10
high_limit = 10
vmax = 5
default_velocity = 0.5
base_velocity = 0.05
acceleration_time = 0.5
```

필수 조건:

- `mres > 0`
- `low_limit < high_limit`
- `0 < base_velocity <= default_velocity <= vmax`
- 거리, 속도, 리미트는 모두 `egu` 기준
- `mres`는 현재 controller micro-step 설정에서 pulse 1개당 이동량
- 제조사 최고속도를 그대로 기본속도로 사용하지 않음

필요하면 `motor`, `motor_current_a_per_phase`, `basic_step_angle_deg`, `sensor`,
`source_pdf`를 검토용 metadata로 추가한다.

추가한 모델을 축에 할당하려면 `axis-assignments.ini`에서 축 slot을 수정한다.

```ini
[axis:6]
enabled = false
model = NEW_MODEL
direction = Pos
sensors = S2,L+,L-
home_method = 4
```

모델 할당만으로 실제 이동 방향이나 HOME 센서가 검증되는 것은 아니다. 새 모델은
Disable 상태에서 설정을 적용하고 저속 방향, 센서, 리미트, HOME을 다시 시험한다.

### 모델 수정

`stage-models.ini`의 해당 section 값을 수정한 뒤 반드시 다음을 수행한다.

1. 해당 모델을 사용하는 모든 축 확인
2. 설정 validator 실행
3. dry-run 결과 확인
4. 대상 축 Disable 및 정지 확인
5. `stage_config_apply.py --apply` 실행
6. 좌표와 소프트 리미트 확인
7. 저속 이동 및 필요 시 재원점 수행

특히 `mres`, `direction`, `low_limit/high_limit` 변경은 좌표와 이동 방향을 바꾸므로
일반 속도 변경보다 위험도가 높다.

### 모델 삭제

먼저 `axis-assignments.ini`에서 해당 모델을 참조하는 모든 축을 찾는다.

```bash
rg -n "model = MODEL_TO_DELETE" config/axis-assignments.ini
```

각 축에서 `model`, `direction`, `sensors`, `faulty_sensors`, `home_method`를 제거하고
미사용 slot 형태로 되돌린다.

```ini
[axis:6]
enabled = false
```

그다음 `stage-models.ini`에서 `[model:MODEL_TO_DELETE]` section 전체를 삭제한다.
참조가 남은 상태에서 모델만 삭제하면 validator가 오류로 거부한다.

추가·수정·삭제 후 공통 검증:

```bash
python3 tools/validate_stage_config.py
python3 -m unittest tests/test_stage_config_validator.py
python3 -m unittest tests/test_stage_config_apply.py
```

## 단계별 진행 원칙

각 단계는 작업 내용과 생성·변경 파일을 먼저 제시하고 사용자의 허가를 받은 후 진행한다.

1. 요구사항과 제조사 프로토콜 정리
2. EPICS IOC 및 드라이버 프로젝트 골격 생성
3. TCP 명령·응답 계층과 테스트 구현
4. Model 3 축 동작 구현
5. motor record와 다축 IOC 구성
6. 실제 장비에 대한 저속·단축 시험
7. 스테이지 모델 설정 체계 구현
8. GUI 구현
9. Ophyd/Bluesky 연동
10. Archiver Appliance 연동

현재는 4단계의 읽기 전용 축 polling과 5단계의 generic motor record 연결까지
수행했다. EPICS Base, asyn 및 motor에
링크되는 IOC와 `KohzuAriesLynxController`/`KohzuAriesLynxAxis` 클래스가 빌드된다.
CRLF 기반 TCP 프레이밍, 응답 파서, 비동기 `SYS` 분리, `IDN` 및 `RAX` 조회가
구현되었다. `RDP`, `STR`, `ROG`로 실제 검출 축의 위치와 상태를 읽어 Model 3
parameter와 최대 32개의 motor record에 반영한다. 시험 모델 5종의 M1 half-step
사양은 catalog에 등록했지만 실제 축 배선·방향·원점 방법을 확인하지 않았으므로
assignment와 mock IOC는 기본적으로 모두 `Disable` 상태다. production `st.cmd`도
32축을 모두 Disable로 시작하고, 지정된 1~5축 모델은 별도 적용 도구로 반영한다.
HOME은 guarded SYS.2/ORG,
절대 위치 이동은 speed table 0 검증 후 APS에 연결했으며 STOP은 `STP<axis>/0` 정상
감속 정지에 연결했다. JOG는 방향·리미트 검사 후 `FRP`에 연결했고 버튼 해제는
`STP/0`을 사용한다. SET 모드의 좌표 보정은 정지·EMG 검사 후 `WRP`를 보내고
`RDP`로 확인한다. 긴급정지
lock을 해제하는 `REM`이나 `RAX`는 자동 실행하지 않는다.
ARIES 오류와 경고는 마지막 코드, 설명, 발생 명령 및 원문 응답을 별도 진단 PV에
보존한다.

골격 빌드와 IOC 등록 확인:

```bash
cd ~/Documents/codex-EPICS-control-test
make -j2
cd iocBoot/iockohzuAriesLynx
../../bin/linux-x86_64/kohzuAriesLynx st.cmd
```

하드웨어가 필요 없는 프로토콜 파서 테스트:

```bash
./kohzuAriesLynxApp/src/O.linux-x86_64/testKohzuAriesLynxProtocol
```

로컬 가상 ARIES를 이용한 TCP 통합 테스트:

```bash
./tests/run_mock_integration.sh
./tests/run_stage_apply_integration.sh
./tests/run_gui_integration.sh
```

두 번째 시험은 별도 loopback ARIES와 모든 축이 Disable로 시작하는 모의 IOC에서
적용 도구를 실제 Channel Access로 호출한다. 5축 설정 readback, 최종 Enable과 DISP
복원을 확인하고
WRP/APS/RPS/FRP/ORG/WTB/WSY/STP/REM이 전송되면 실패한다.

동적 GUI만 실행:

```bash
python3 gui/kohzu_gui_server.py
```

기본 `127.0.0.1` bind는 서버가 실행되는 컴퓨터에서만 접속할 수 있다. 같은 LAN의 다른
컴퓨터에서 접속하려면 `runtime.ini`의 `gui.listen`을 서버의 LAN IP 또는 `0.0.0.0`으로
바꾸고 브라우저에서는 `http://서버의-LAN-IP:8080`을 연다. `0.0.0.0`은 모든 로컬
인터페이스에서 요청을 받으라는 bind 값이지 접속 주소가 아니다. 현재 GUI에는 사용자
인증과 TLS가 없으므로 외부 bind는 격리된 신뢰 네트워크와 방화벽 안에서만 사용한다.

축 1~32와 catalog 모델을 선택해 패널을
생성·삭제할 수 있다. 생성은 선택 축이 Disable일 때 선택 모델의 `DESC`, `EGU`,
`MRES`, software limit와 속도 field를 실제 IOC에 적용하고 readback을 검증한 뒤 축을
Enable하고 assignment에 저장한다. `DIR`과 OriginMethod는 축 고유 설정이므로 변경하지
않는다. 삭제는 축을 Disable하고 assignment의 모델을 제거한다. 정상적인 웹서버 종료는
모든 패널 축을 Disable하되 모델을 보존하며, 다음 시작 때 패널을 자동 복원한다. 현재
GUI는 사용자·dial·raw 위치와 기본 motor 상태를 표시하고 활성 패널마다 절대·상대
위치 이동, press-and-hold CW/CCW JOG와 정상 감속 STOP을 제공한다. 위치 이동은 서버의
전용 worker에서 Ophyd motor와 Bluesky RunEngine을 거쳐 실행하며 브라우저가 PV에 직접
쓰지 않는다. JOG는 Ophyd JOGF/JOGR signal을 사용하고 실제 MOVN 전환을 확인한 뒤,
해제할 때 같은 Ophyd STOP 경로를 사용한다. HOME, commissioning, 진단 또는 recovery
명령은 아직 제공하지 않는다.

이동 전에는 Enable·정지·limit 상태와 유한한 입력을 확인한다. 절대 입력은 목표 사용자
좌표, 상대 입력은 현재 RBV에 더한 목표로 바꾼 뒤 현재 MRES 간격의 최근접 사용자
좌표로 반올림하고 LLM/HLM을 검사한다. 입력 목표와 실행 목표가 다르면 완료 메시지에
두 값과 최종 RBV를 함께 표시한다.

브라우저와 backend는 영구 WebSocket을 유지하고, panel별 영구 Ophyd motor가 EPICS
monitor callback으로 상태를 push한다. 반복 polling과 운전용 `caget/caput` HTTP 경로는
없다. 이동이나 JOG 중 위치와 motion/limit 상태도 monitor 변경 시 즉시 전달된다.
간편 패널에도 절대 목표 입력을 제공한다. 기본·상세 패널은 motorx_all을
참고한 속도, JOG, limit, backlash, retry와 좌표 설정 field를 편집할 수 있으며, 서버의
allowlist와 readback 검증을 거친다. 좌표 변환 field는 SET=Set에서만 변경할 수 있다.
숫자 field는 Enter, enum field는 선택 변경으로 즉시 적용되며 배경색으로 수정·적용 중·
성공·실패 상태를 구분한다. UEIP/URIP encoder 선택도 제공하고, backlash는 별도 스위치
대신 BDST=0일 때 비활성으로 취급한다.

브라우저 WebSocket이 끊기면 backend가 그 연결이 소유한 동작 축에 STOP을 보낸다. launcher에서
Ctrl-C를 누르면 자식 프로세스가 신호를 동시에 받지 않으며 GUI의 진행 중 요청과 축
Disable·assignment 저장을 마친 뒤 IOC를 종료한다.

launcher 터미널에는 IOC, stage apply, GUI와 launcher 출력을 각각 `[IOC]`, `[APPLY]`,
`[GUI]`, `[LAUNCHER]`로 표시해 실시간 출력한다. 실행별 디렉터리에는 각 원본 로그와
시간순으로 합친 `session.log`를 정상·실패 종료 모두 보존한다. 마지막 실행은 다음처럼
확인할 수 있다.

```bash
less logs/kohzu-control/latest/session.log
tail -F logs/kohzu-control/latest/session.log
```

FIFO는 `/tmp/kohzu-control-runtime.*`에서만 생성하며 종료 시 항상 삭제한다. 운영 로그
디렉터리는 `.gitignore` 대상이고 현재는 자동 보존 기간이나 개수 제한을 두지 않는다.

패널 삭제나 다른 모델 할당에서도 `direction`, `sensors`, `home_method`는 모델이 아닌
축 설치 고유 설정이므로 보존된다. 다른 종류의 모델로 교체할 때 이 값들이 새 모델에
자동으로 맞춰지는 것은 아니므로 사용자가 방향과 Origin Method의 적합성을 다시
확인해야 한다.

진단 database를 로드하면 다음 읽기 전용 PV가 생성된다. 아래 이름에서 prefix는
mock IOC의 `MOCK:` 예시이며 실제 IOC에서는 설정한 prefix로 바뀐다.

```text
MOCK:Diag:LastErrorCode
MOCK:Diag:LastErrorText
MOCK:Diag:LastErrorCommand
MOCK:Diag:LastErrorRaw
MOCK:Diag:LastWarningCode
MOCK:Diag:LastWarningText
MOCK:Diag:LastWarningCommand
MOCK:Diag:LastWarningRaw
MOCK:Recovery:EmergencyActive
MOCK:Recovery:ReleaseEMG
MOCK:Recovery:RefreshAxes
MOCK:Recovery:Status
```

`Recovery:ReleaseEMG`는 모든 검출 축의 `STR`에서 물리 EMG 입력이 해제된 것을 새로
확인한 경우에만 `REM`을 전송한다. 확인 실패나 활성 입력이 있으면 안전하지 않은
상태로 보고 전송을 거부한다. `Recovery:RefreshAxes`는 Motionnet 복구 후 사용자가
명시적으로 `RAX` 재구성을 요청하는 PV이며 자동 실행되지 않는다.

이동 명령과 분리된 speed table 0 설정 시험은 다음 IOC shell 명령으로 수행할 수 있다.

```text
KohzuAriesLynxConfigureSpeedTable0("KOHZU", 1, 100, 1000, 4500)
```

인수는 motor port, controller 축 번호, 시작 속도[pulse/s], 최고 속도[pulse/s],
가속도[pulse/s²] 순서다. 드라이버는 `RSY<axis>/16`으로 축의 최고 속도 제한을 먼저
확인하고 매뉴얼 규정에 맞는 경우에만 table 0에 `WTB`를 쓴다. 이 명령은 속도 표만
변경하며 모터 이동을 시작하지 않는다.

검증된 모델·축 설정이 motor record에 어떻게 대응하는지 변경 없이 확인:

```bash
python3 tools/validate_stage_config.py
python3 tools/stage_config_dry_run.py --prefix KOHZU:
python3 tools/stage_config_apply.py --prefix KOHZU:
```

모델의 VMAX가 현재 SYS.16을 초과하면 validator와 dry-run은 필요한 최소 SYS.16 값을
경고하지만 모델을 거부하지 않는다. dry-run은 실행 가능한 `dbpf` 명령을 만들지 않고
IOC와 controller 값을 전혀 변경하지 않는다.

`stage_config_apply.py`도 기본 실행은 쓰기 없는 적용 계획만 출력한다. catalog에서
모델이 할당된 축을 대상으로 하며 실제 Channel Access write에는 별도 `--apply`가
필요하다. 적용 중에는 `_able=Disable`과 SDIS를 유지하고 각 field를 write/readback
검증한다. 최종 `_able`은 assignment의 `enabled` 상태를 따른다. GUI 생성·삭제·종료가
이 값을 현재 패널 수명주기에 맞춰 갱신한다. 과거 commissioning EnableRequest와 Ready
구조는 기본 운전에서 사용하지 않는다.
프로젝트 motor template은 `_able`을
`KOHZU_INTERNAL_ENABLE` access group에 정적으로 배치한다. IOC에서
`kohzuAriesLynxAccessSecurity.acf`를 iocInit 전에 로드하면 외부 Channel Access는
`_able`을 읽을 수만 있고 쓸 수 없으며, IOC 내부 commissioning DB link만 값을
변경한다.

축별 HOME 방식은 PV에서 사용자가 선택한다. PV write는 드라이버의 선택값만 바꾸고
controller SYS.2를 즉시 쓰지 않는다. 1~15는 모두 선택 가능하고 센서 적합성 판단은
사용자 책임이다.

```text
KOHZU:m1:OriginMethod       # 선택값 1..15
KOHZU:m1:OriginMethodSelectedRBV # driver가 수락한 선택값
KOHZU:m1:OriginMethodRBV    # HOME preflight에서 읽은 실제 SYS.2
KOHZU:m1:HomeStatus         # 설정 및 ORG 처리 결과
```

`OriginMethodMaskConfig`와 `AllowedHomeMethods`는 사용되지 않는 초기 센서-mask
인터페이스였으므로 제거했다. Method 1~15의 적합성은 축 센서 구성에 맞춰 사용자가
선택한다. `HomeStatus`, `MoveStatus`, `PositionStatus`는 개발 중 Codex 진단용이며
개발 완료 후 DB에서 주석 처리하여 로드하지 않는다. commissioning과 `_able/SDIS`
잠금도 개발용이며 최종 운전 인터페이스에는 포함하지 않는다.

motor record HOME 요청 시 드라이버는 축 정지와 물리 EMG 입력을 확인하고
`RSY<axis>/2`로 실제 SYS.2를 읽는다. 선택값과 다르면 `WSY<axis>/2/<method>`로
변경한 뒤 RSY로 다시 확인하고, 확인된 경우에만 ORG를 보낸다. Method 10은 speed
table 변경 없이 `ORG<axis>/0/1`을 보내며, 이동하는 다른 방법은 speed table 0을
먼저 검증·갱신한다.

1~15 밖의 `OriginMethod` write만 controller 통신 전에 거부된다. EPICS output
record에는 마지막 시도값이 남을 수 있으므로 GUI와 Ophyd는 write 성공 여부와
`OriginMethodSelectedRBV`를 확인해야 한다. `applyConfiguredHomeMethods.cmd`는 검토된
초기 Method만 적용한다.

Model 3 이동은 명령 직전에 현재 위치·이동·EMG 상태를 새로 읽고 raw pulse 목표를
motor record soft limit과 비교한다. 통과하면 table 0과 SYS.16을 검증한 뒤
`APS<axis>/0/<target>/1`을 보낸다. motor record의 `RLV`는 record 내부에서 새 절대
목표로 변환되므로 일반 motor PV 경로에서는 두 번째 APS로 나타난다. driver의 직접
relative API에는 RPS 명령 생성 경로가 유지된다. 결과는 `m<axis>:MoveStatus`에서
확인한다.

JOG 요청은 Model 3 `maxVelocity`의 부호로 방향을 정한다. 현재 배선 확인 전 정책은
양수=CW(`FRP<axis>/0/0`), 음수=CCW(`FRP<axis>/0/1`)이며 실제 장비의 저속 단축
시험 뒤 DIR/CW/CCW 관계를 확정해야 한다. 드라이버는 FRP 직전에 fresh snapshot으로
EMG, 이동 중 여부, 진행 방향의 하드 리미트와 현재 위치의 motor-record raw soft
limit을 검사한다. 통과한 경우 속도의 절댓값으로 table 0과 SYS.16을 검증한다.
motor record는 JOG 중 dial 위치가 limit의 약 1초 이동거리 안에 들어오면 LVIO와 함께
정지를 요청한다. 따라서 polling 지연과 감속 거리만큼의 여유가 필요하며, 이 기능이
기계적 충돌 방지 장치를 대신하지는 않는다.

motor record에서 `SET=Set`인 상태로 `DVAL` 또는 `RVAL`을 변경하면 Model 3
`setPosition()`이 호출되어 `WRP<axis>/<raw pulse>`로 controller 좌표만 바뀐다.
드라이버는 축 정지와 EMG 해제를 새로 확인하고, WRP 뒤 RDP가 같은 값을 반환해야
성공으로 처리한다. 결과는 `m<axis>:PositionStatus`에 기록된다. WRP는 임의 좌표
교정이며 원점 탐색이나 homed 상태 설정을 의미하지 않는다. 반면 Origin Method 10의
ORG는 controller의 원점 복귀 절차로 현재 위치를 원점으로 확정하는 용도다.

SET 모드에서 어떤 drive field를 쓰는지와 `FOFF` 값에 따라 motor record가 `OFF`,
사용자 좌표 및 `HLM/LLM`을 함께 조정할 수 있으므로 GUI는 raw WRP를 직접 노출하지
않고 motor record의 SET/DVAL/RVAL 절차를 사용해야 한다. 좌표 보정 뒤에는 RBV,
VAL/DVAL/RVAL, OFF, LLM/HLM을 재확인한 후 다시 이동한다.

가상 서버는 `IDN`, `RAX`, `RDP`, `STR`, `ROG` 및 비동기 `W SYS 52`를 재현하며
실제 장비에 접속하거나 모터 명령을 실행하지 않는다.
