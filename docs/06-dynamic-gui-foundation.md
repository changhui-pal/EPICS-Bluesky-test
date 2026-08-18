# 최소 동적 축 패널 GUI

## 현재 범위

2026-08-13에 기존 commissioning, HOME, 진단과 recovery GUI를 비우고 다음 기능만 남긴
최소 구조로 다시 구현했다.

- 축 `1~32` 중 하나 선택
- `config/stage-models.ini`의 모델 중 하나 선택
- 생성 버튼으로 선택 축에 모델 설정 적용
- 적용 성공 후 해당 축 패널 생성
- 패널의 삭제 버튼으로 축 Disable 및 모델 할당 제거
- EPICS monitor → WebSocket event로 위치와 motor 상태 표시
- 기본·상세 패널의 allowlist motor field 편집과 readback 검증

GUI는 FastAPI/Uvicorn backend와 브라우저의 HTML/CSS/JavaScript로 구성한다. 기본 bind는
`127.0.0.1`이며 `config/runtime.ini` 또는 `--listen`으로 변경할 수 있다. 추가 GUI
framework는 필요하지 않다.

## 패널 생성과 실제 적용

생성은 단순한 화면 표시가 아니다. `POST /api/panels`가 공용
`tools/stage_config_apply.py` 구현을 재사용하여 선택한 한 축에 다음 모델 고유 field를
쓰고 즉시 readback을 검증한다.

```text
DESC, EGU, MRES, LLM, HLM, VMAX, VELO, JVEL, JAR, HVEL, VBAS, ACCL
```

GUI는 먼저 정지 상태를 확인하고 축을 Disable한다. 단, `_able`은 motor record의
`SDIS`이므로 Disable 중에 쓴 MRES의 special 처리는 사라지지 않고 다음 process까지
보류된다. 이를 첫 이동 때 처리하면 motor record가 `LOAD_POS`를 실행하고
`FOFF=Variable`에서 OFF와 사용자 LLM/HLM을 번역할 수 있다. 따라서 모델 적용기는 축별로
`SET=Set`을 먼저 선택하고 record 처리를 잠시 허용한 상태에서 MRES와 나머지 필드를
적용한다. 이때 MRES 변경은 controller 좌표 쓰기 대신 GET_INFO로 소비된다. 적용 후
기존 SET 상태와 Disable을 복원하며, 최종 assignment가 활성인 경우에만 Enable한다.

모든 readback이 일치하면 `axis-assignments.ini`에 모델과 `enabled=true`를 원자적으로
저장하고 패널을 생성한다. 설정 파일 저장 또는 중간 적용이 실패하면 SET 상태 복원을
시도하고 축을 반드시 Disable한다. SPMG는 변경하지 않으므로 적용 자체가 불필요한
STP 명령을 만들지 않는다.

`DIR`과 OriginMethod는 설치 방향과 센서 구성에 따른 축 고유 설정이지 모델 자체의
속성이 아니므로 이번 GUI 단계에서는 변경하지 않는다. GUI는 Ophyd/Bluesky를 통한
절대·상대 위치 이동, 누르는 동안의 CW/CCW JOG와 motor record `.STOP`을 통한 정상 감속
정지를 제공한다. HOME, ORG, controller speed table 직접 변경 및 recovery 명령은
제공하지 않는다.

## 영구 Ophyd session, EPICS monitor와 WebSocket

패널마다 `AxisSession`과 `SafeStopEpicsMotor`를 하나씩 만들고 모든 표시·편집 PV에 한 번만
연결한다. CA callback은 cache를 갱신하고 backend가 WebSocket으로 browser에 push한다.
polling, 반복 상태 `caget`, 운전 `caput`, `/status`, `/move`, `/jog`, `/stop`, `/field`
HTTP endpoint는 없다.

숫자 PV는 `PREC` 문자열 변환 없이 numeric value로 읽는다. 그래야 초기 `PREC=0`인
slot에서 `MRES=0.0005`가 문자열 `0`으로 잘리지 않는다. 유효 snapshot과 subscription이
준비된 뒤 `_able=Enable`로 바꾸고 Ready panel을 공개한다. JOG 시작과 해제는 같은
WebSocket에 연속 전송하므로 짧은 tap의 STOP이 시작 응답을 기다리지 않는다. 연결이
끊기면 그 연결이 소유한 동작 축을 정지한다.

launcher의 IOC와 GUI 자식은 터미널 SIGINT를 직접 처리하지 않는다. Ctrl-C는 launcher가
받아 GUI에 SIGTERM을 보내고, GUI가 request 종료·축 Disable·assignment 저장을 마친 뒤
IOC shell에 `exit`를 전달한다. 따라서 GUI와 IOC가 동시에 종료되어 cleanup CA 조회가
실패하는 경쟁을 피한다.

launcher는 실행별 `logs/kohzu-control/<시각>-<PID>/`에 `ioc.log`, `apply.log`,
`gui.log`, `launcher.log`와 이들을 시간·출처와 함께 합친 `session.log`를 보존한다.
터미널에도 합친 내용을 실시간 표시하며 `latest` symlink는 마지막 실행을 가리킨다.
정상과 실패 실행을 모두 보존하고 자동 rotation은 아직 적용하지 않는다. IOC stdin FIFO
같은 runtime 자원만 `/tmp/kohzu-control-runtime.*`에 만들고 종료 시 제거한다.

각 패널의 allowlist 상태는 EPICS monitor callback이 발생할 때만 갱신한다.

```text
RBV, VAL, EGU, _able, MOVN, DMOV, HLS, LLS, LVIO,
LLM, HLM, VELO, JVEL, JAR, HVEL, VMAX, VBAS, ACCL, DIR, MRES, OFF, FOFF,
DVAL, DRBV, RVAL, RRBV, MSTA, SET, SPMG, TWV, backlash/retry fields,
PREC, UREV/SREV, ERES/RRES, OriginMethodSelectedRBV
```

화면에는 현재 위치, Enabled/Disabled와 Moving/Stopped 요약, 양쪽 하드 리미트,
software 범위와 현재/최대 속도가 표시된다. 상세 보기에는 목표·dial·raw 좌표,
DIR/MRES, OFF/FOFF, VBAS/ACCL, MSTA와 Origin method도 표시한다. CA 연결 오류는 패널별로
표시하며 다른 패널 갱신에는 영향을 주지 않는다.

간편 보기에는 JOG/STOP과 함께 절대 목표 입력 한 개를 둔다. 기본 보기는 VELO, ACCL,
JVEL, JAR, TWV와 LLM/HLM을 편집한다. 상세 보기는 VBAS/VMAX/HVEL, backlash, retry,
settling 설정과 motorx_all 계열 좌표·분해능 필드를 추가한다. 모든 write는 서버의 명시적
allowlist를 통과하고 실제 readback이 요청값과 일치해야 성공한다. 이동 중 field edit은
거부하며 OFF/MRES/DIR/FOFF는 사용자가 먼저 SET=Set을 선택한 경우에만 허용한다.
숫자 입력은 Enter로 해당 필드 하나를 즉시 적용하고 select는 선택 변경 즉시 적용한다.
노란색은 미적용 수정, 파란색은 적용 중, 녹색은 readback 일치, 빨간색은 실패를 뜻한다.
구역별 적용 버튼은 여러 변경값을 순서대로 적용할 때 유지한다.

encoder 선택은 UEIP(장치 encoder가 있을 때 사용)와 URIP(RDBL link가 있을 때 사용)를
제공한다. 실제 encoder 또는 RDBL link가 없는 record에서 Yes를 선택해도 새 센서나
readback source가 생기지는 않는다. Backlash에는 별도 Enable field가 없으며 BDST=0이
사실상 비활성이고, 0이 아닌 BDST에서 BVEL/BACC가 복귀 동작을 정한다.

## assignment와 패널 수명주기

`axis-assignments.ini`가 패널과 IOC 적용 상태의 영속 기준이다.

```text
model 있음 + 웹서버 실행 중 패널 존재 = enabled=true, IOC Enable
model 있음 + 웹서버 종료             = enabled=false, 다음 시작 때 복원
model 없음                           = 패널 미할당, IOC Disable
```

GUI 시작 시 `model`이 있는 모든 축을 다시 적용하고 Enable한 뒤 패널을 자동 생성한다.
브라우저 새로고침은 `/api/config`의 현재 서버 패널 목록으로 화면만 복원한다.

삭제 버튼은 먼저 IOC 축을 Disable하고 readback을 확인한 뒤 assignment에서 `model`을
제거하고 `enabled=false`로 저장한다. 실제 motor record slot과 현재 좌표는 삭제하지
않는다. 따라서 같은 축과 모델을 즉시 다시 생성할 수 있다.

`direction`, `sensors`, `home_method`는 모델 할당이 아니라 물리적인 축 설치 설정이므로
삭제 후에도 보존한다. 다른 모델을 할당하면 새 모델의 단위·분해능·범위·속도 필드는
교체되지만 이 세 값은 기존 축 값을 그대로 사용한다. 서로 다른 종류의 모델로 바꿀
때에는 방향과 Origin Method가 적합한지 사용자가 다시 확인해야 한다.

웹서버가 SIGINT 또는 SIGTERM으로 정상 종료되면 모든 활성 패널 축을 Disable하고
`enabled=false`로 바꾸되 `model`은 보존한다. 다음 GUI 시작 때 해당 패널들이 다시
적용·Enable된다. 브라우저 탭 닫기나 새로고침은 웹서버 종료가 아니므로 Disable하지
않는다.

## 실행

IOC가 별도 터미널에서 실행 중이고 32축이 생성된 상태에서 다음을 실행한다.

```bash
conda activate kohzu-bluesky
cd /home/changhui1788/Documents/EPICS-Bluesky-test
python gui/kohzu_gui_server.py
```

브라우저에서 `http://127.0.0.1:8080`을 연다.

다른 컴퓨터에서 접속할 때는 `config/runtime.ini`의 `gui.listen`을 서버 LAN IP 또는
`0.0.0.0`으로 설정하고, 클라이언트에서는 서버의 실제 LAN IP로 접속한다. `127.0.0.1`은
각 컴퓨터 자신을 뜻하므로 원격 접속에 사용할 수 없다. 현재 same-origin write token은
임의 외부 사용자를 인증하는 장치가 아니며 TLS도 없으므로 외부 bind는 격리된 신뢰
네트워크에서만 사용한다. non-loopback bind 시 서버도 이 제한을 경고한다.

controller endpoint, EPICS prefix/bin/CA 주소, Python 실행 파일과 GUI bind/port는
`config/runtime.ini`에서 함께 관리된다. launcher 옵션 및 각 Python 도구의 명시적 CLI
인자는 해당 실행에 한해 중앙 기본값을 덮어쓴다. mock 시험의 loopback 주소와 포트는
운영 설정과 무관한 격리 fixture이므로 중앙 설정을 사용하지 않는다.

IOC부터 함께 시작하려면 저장소 최상위의 launcher를 사용한다.

```bash
./start_kohzu_control.sh
```

launcher는 IOC PV 준비를 기다리고 assignment를 적용한 뒤 GUI를 시작한다. Ctrl-C 시
GUI를 먼저 종료하여 활성 패널 축을 Disable·저장하고 그 다음 IOC를 종료한다.

## 검증

```bash
python -m pytest -q tests/test_gui_server.py
./tests/run_gui_integration.sh
```

통합시험은 loopback simulator와 `MOCK:` IOC를 사용한다. 축 6에 RA04A-W01을 적용해
모델 field와 최종 Enable을 확인한다. 이어서 삭제 시 Disable/할당 제거, 같은 축의 다른
모델 재생성, 서버 종료 시 Disable/모델 보존을 확인한다. 인증 token이 잘못된 요청과
중복 패널도 거부되며 WRP, APS, RPS, FRP, ORG, WTB, WSY, STP와 REM 명령이 controller에
전송되지 않은 것도 검사한다.

## 완료된 표시 단계와 다음 GUI 후보

기능은 한 번에 하나씩 추가하고 각 단계마다 mock IOC 시험을 먼저 만든다. 현재 확정한
구현 순서는 다음과 같다.

### A. 실제 위치 단위 확인 — 구현 완료

GUI는 pulse field인 RRBV/RVAL이 아니라 사용자 좌표인 RBV를 표시한다. 실제 IOC에서
다음을 함께 읽어 motor record 변환 관계를 확인한다.

```text
RBV, RRBV, MRES, OFF, DIR, EGU
```

정상 USE 모드의 일반 이동에서는 목표가 pulse 격자와 정확히 일치하지 않아도 OFF가
변하지 않는다. motor record가 정수 pulse에 해당하는 실제 RBV를 계산한다.

### B. 3단계 반응형 패널 — 표시 구조 구현 완료

전체 화면의 `간편/기본/상세` 선택을 모든 축 패널에 공통 적용하고 선택값은 브라우저
localStorage에 저장한다.

- 간편: 모바일 한 화면에 5~6축이 보이도록 축, 위치, 상태, 활성 STOP과
  press-and-hold CCW/CW를 한 줄로 표시
- 기본: 현재 위치, 상태, hard/software limit와 현재 속도 표시
- 상세: 기본 항목과 target/raw/dial/user 좌표, 변환값, 속도·limit·MSTA 및 Origin method

기본·상세 보기의 일반 위치 이동은 C 단계, 간편 보기의 CCW/CW JOG는 D 단계에서
구현했다.

### C. STOP과 일반 이동 — 구현 완료

활성 패널의 STOP API와 기본·간편 보기 버튼은 motor record `.STOP=1`을 요청하며
assignment나 Enable 상태를 변경하지 않는다. 드라이버는 이를 정상 감속
`STP<axis>/0`으로 변환한다.

기본·상세 보기에는 절대 목표와 상대 이동량 입력을 제공한다. 서버는 활성 패널,
Enable, DMOV/MOVN과 hardware/software limit를 확인하고 현재 RBV에서 MRES 간격의 최근접
user 좌표로 목표를 양자화한 뒤 LLM/HLM을 검사한다. 통과한 요청만 단일 worker가 소유한
Ophyd `SafeStopEpicsMotor`와 Bluesky `RunEngine`으로 직렬 실행한다. 입력 목표, 양자화된
실행 목표와 최종 RBV를 응답하고 값이 달라졌으면 GUI에 모두 표시한다. 이동 중 STOP은
같은 Ophyd motor의 pending status를 실패 완료시키므로 RunEngine 요청도 종료된다.
RunEngine plan의 완료 제한시간은 `config/runtime.ini`의 `gui.move_timeout`으로 관리하며
기본값은 180초다. mock 통합시험은 실패를 빨리 검출하기 위해 CLI에서 8초로 덮어쓴다.

mock end-to-end 시험은 GUI 요청이 motor record를 거쳐 `APS1/0/200/1` wire 명령을 만들고,
시간 기반 mock 이동 중 `MOVN=1/DMOV=0`을 관찰한 뒤 최종 `0.1 mm`에서 완료되는 것을
검증한다. 수정된 모델 적용 transaction에서는 MRES 처리를 첫 이동까지 미루지 않으므로
WRP 좌표 설정 명령도 발생하지 않는다.

### D. 모바일 CW/CCW JOG — 구현 완료

JOG는 위치 목표가 아니라 방향·속도 동작이다. pointerdown에서 시작하고 pointerup,
pointercancel, pointer capture 상실, window blur와 visibility 변경에서 STOP한다. 빠른
탭은 같은 WebSocket의 순서를 이용해 시작 응답을 기다리지 않고 STOP을 바로 전송한다.

서버는 Enable, SET=Use, SPMG=Go, 정지와 limit 상태를 확인하고 물리 CW/CCW를 DIR에 따라
JOGF/JOGR로 변환한다. 시작 API는 Ophyd signal write가 처리되면 즉시 반환하여 짧은 탭의
pointerup STOP이 다음 IOC 상태 poll까지 기다리지 않게 한다. 해제는
`SafeStopEpicsMotor.stop()`을 통해 정상 감속 `STP<axis>/0`으로 이어진다.

모델 적용 시 `JVEL`과 `HVEL`은 모델 기본 속도로 설정한다. `JAR`은 일반 이동과 같은
램프 시간을 만들도록 `(default_velocity-base_velocity)/acceleration_time`으로 계산한다.
mock end-to-end 시험에서 `JOGF -> WTB -> FRP(CW) -> MOVN -> STP/0` 경로를 확인했다.

### E. Origin Method와 HOME — 구현 완료

기본·상세 panel에서 Method 1~15를 사용자가 직접 선택한다. 선택값은 IOC의
`:OriginMethod`에 쓰고 readback을 확인한 뒤 `axis-assignments.ini`의 `home_method`에
저장한다. 센서 종류로 Method를 자동 제한하지 않으며 선택 책임은 사용자에게 있다.
panel 생성과 GUI 재시작 시 저장된 Method를 Enable 전에 다시 적용한다.

HOME은 같은 `AxisSession`의 Ophyd `motor.home("forward")`, 즉 `.HOMF`를 실행한다.
driver의 기존 `STR → RSY(SYS.2) → 필요 시 WSY → RSY 재확인 → ORG` 경로를 재사용한다.
진행 상태는 EPICS monitor로 표시하고 STOP으로 중단할 수 있다. timeout은
`runtime.ini`의 `gui.home_timeout`에서 관리한다. commissioning flag와 개발용
HomeStatus는 운전 gate로 사용하지 않는다.

### F. 축별 저장 위치

정렬 작업에서 자주 쓰는 단일 축 위치를 이름과 함께 여러 개 저장한다. 저장 파일은
assignment와 분리된 `config/saved-positions.json`을 사용하고 원자적으로 갱신한다.

저장 항목은 축, 모델, 실제 RBV, EGU, MRES, OFF, DIR과 저장 시각이다. 복귀 전에는
패널 존재, Enable/정지, limit 해제, 모델·EGU·MRES·OFF·DIR 일치와 현재 software
limit 범위를 검사한다. 현재 GUI server 세션 이전의 저장값은 좌표계가 유지됐는지
사용자 확인을 받는다. 좌표계 generation counter는 도입하지 않는다.

### G. 전체 포즈와 후속 기능

축별 저장 위치가 검증된 뒤 활성 축 전체 포즈 저장과 다축 Bluesky 복귀를 추가한다.
포함된 축 중 하나라도 호환성 검사를 통과하지 못하면 전체 이동을 거부한다. 이후 순서는
운전 속도 변경, 별도 5축 고정점 운동 패널, controller 진단 표시다.

실제 오차 보정 UI는 측정 도구 또는 카메라 기반 측정 방법이 마련될 때까지 추가하지
않는다.
