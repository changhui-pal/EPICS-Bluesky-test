# 최소 동적 축 패널 GUI

## 현재 범위

2026-08-13에 기존 commissioning, HOME, 진단과 recovery GUI를 비우고 다음 기능만 남긴
최소 구조로 다시 구현했다.

- 축 `1~32` 중 하나 선택
- `config/stage-models.ini`의 모델 중 하나 선택
- 생성 버튼으로 선택 축에 모델 설정 적용
- 적용 성공 후 해당 축 패널 생성
- 패널의 삭제 버튼으로 축 Disable 및 모델 할당 제거
- 패널별 motor 상태를 1초 간격으로 read-only 표시

GUI는 Python 표준 HTTP server와 브라우저의 HTML/CSS/JavaScript로 구성하며
`127.0.0.1`에만 bind한다. 추가 GUI framework는 필요하지 않다.

## 패널 생성과 실제 적용

생성은 단순한 화면 표시가 아니다. `POST /api/panels`가 공용
`tools/stage_config_apply.py` 구현을 재사용하여 선택한 한 축에 다음 모델 고유 field를
쓰고 즉시 readback을 검증한다.

```text
DESC, EGU, MRES, LLM, HLM, VMAX, VELO, VBAS, ACCL
```

GUI는 먼저 정지 상태를 확인하고 축을 Disable한 뒤 모델을 적용한다. 모든 readback이
일치하면 `axis-assignments.ini`에 모델과 `enabled=true`를 원자적으로 저장하고 패널을
생성한다. 설정 파일 저장이 실패하면 축을 다시 Disable한다.

`DIR`과 OriginMethod는 설치 방향과 센서 구성에 따른 축 고유 설정이지 모델 자체의
속성이 아니므로 이번 GUI 단계에서는 변경하지 않는다. HOME, ORG, 이동, STOP,
controller speed table 및 recovery 명령도 제공하지 않는다.

각 패널은 한 번의 allowlist CA read로 다음 상태를 1초마다 갱신한다.

```text
RBV, EGU, _able, MOVN, DMOV, HLS, LLS, LVIO,
LLM, HLM, VELO, VMAX, DIR, MRES, OriginMethodSelectedRBV
```

화면에는 현재 위치, Enabled/Disabled와 Moving/Stopped 요약, 양쪽 하드 리미트,
software 범위, 현재/최대 속도, DIR/MRES와 Origin method가 표시된다. CA 연결 오류는
패널별로 표시하며 다른 패널 갱신에는 영향을 주지 않는다.

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

웹서버가 SIGINT 또는 SIGTERM으로 정상 종료되면 모든 활성 패널 축을 Disable하고
`enabled=false`로 바꾸되 `model`은 보존한다. 다음 GUI 시작 때 해당 패널들이 다시
적용·Enable된다. 브라우저 탭 닫기나 새로고침은 웹서버 종료가 아니므로 Disable하지
않는다.

## 실행

IOC가 별도 터미널에서 실행 중이고 32축이 생성된 상태에서 다음을 실행한다.

```bash
conda activate kohzu-bluesky
cd /home/changhui1788/Documents/EPICS-Bluesky-test
python gui/kohzu_gui_server.py --prefix KOHZU:
```

브라우저에서 `http://127.0.0.1:8080`을 연다.

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

## 다음 GUI 후보

기능은 한 번에 하나씩 추가하고 각 단계마다 mock IOC 시험을 먼저 만든다. 현재 확정한
구현 순서는 다음과 같다.

### A. 실제 위치 단위 확인

GUI는 pulse field인 RRBV/RVAL이 아니라 사용자 좌표인 RBV를 표시한다. 실제 IOC에서
다음을 함께 읽어 motor record 변환 관계를 확인한다.

```text
RBV, RRBV, MRES, OFF, DIR, EGU
```

정상 USE 모드의 일반 이동에서는 목표가 pulse 격자와 정확히 일치하지 않아도 OFF가
변하지 않는다. motor record가 정수 pulse에 해당하는 실제 RBV를 계산한다.

### B. 3단계 반응형 패널

전체 화면의 `간편/기본/상세` 선택을 모든 축 패널에 공통 적용하고 선택값은 브라우저
localStorage에 저장한다.

- 간편: 모바일 한 화면에 5~6축이 보이도록 축, 위치, 상태, CCW/STOP/CW만 한 줄 표시
- 기본: 상태, hard limit, 상대·절대 이동, STOP, 현재 속도와 축별 저장 위치
- 상세: 기본 항목과 raw/dial/user 좌표, 변환값, 속도·limit·status 및 HOME 정보

### C. STOP과 일반 이동

STOP을 가장 먼저 구현하고 검증한 뒤 상대 이동과 절대 이동을 추가한다. 모든 위치
요청은 현재 `OFF/MRES/DIR`로 표현 가능한 최근접 user 좌표로 양자화하고 LLM/HLM을
검사한 다음 Ophyd/Bluesky로 실행한다. 입력 목표와 실제 실행 목표가 다르면 둘 다
표시한다.

### D. 모바일 CW/CCW JOG

JOG는 위치 목표가 아니라 방향·속도 동작이다. pointerdown에서 시작하고 pointerup,
pointercancel, pointerleave, window blur와 visibility 변경에서 STOP한다. 정지 후 DMOV와
최종 RBV를 다시 읽는다. STOP 경로 검증 전에는 JOG 버튼을 활성화하지 않는다.

### E. 축별 저장 위치

정렬 작업에서 자주 쓰는 단일 축 위치를 이름과 함께 여러 개 저장한다. 저장 파일은
assignment와 분리된 `config/saved-positions.json`을 사용하고 원자적으로 갱신한다.

저장 항목은 축, 모델, 실제 RBV, EGU, MRES, OFF, DIR과 저장 시각이다. 복귀 전에는
패널 존재, Enable/정지, limit 해제, 모델·EGU·MRES·OFF·DIR 일치와 현재 software
limit 범위를 검사한다. 현재 GUI server 세션 이전의 저장값은 좌표계가 유지됐는지
사용자 확인을 받는다. 좌표계 generation counter는 도입하지 않는다.

### F. 전체 포즈와 후속 기능

축별 저장 위치가 검증된 뒤 활성 축 전체 포즈 저장과 다축 Bluesky 복귀를 추가한다.
포함된 축 중 하나라도 호환성 검사를 통과하지 못하면 전체 이동을 거부한다. 이후 순서는
운전 속도 변경, OriginMethod/HOME, 별도 5축 고정점 운동 패널, controller 진단 표시다.

실제 오차 보정 UI는 측정 도구 또는 카메라 기반 측정 방법이 마련될 때까지 추가하지
않는다.
