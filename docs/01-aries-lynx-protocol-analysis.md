# ARIES/LYNX 프로토콜 분석 및 EPICS 드라이버 설계 기준

## 1. 문서 목적

이 문서는 KOHZU ARIES/LYNX 시스템을 synApps motor의 Model 3 인터페이스로
제어하기 위한 기준을 정리한다. 제조사 매뉴얼의 명령을 EPICS motor 동작에
대응시키고, 다축 구성, 오류 진단, 스테이지 모델 변경 및 GUI 동작 원칙을 정의한다.

참조 문서는 다음과 같다.

- `documents/ARIES_LYNX_manual_Rev1.43_en.pdf`
- `documents/TITAN-A2_manual_rev1.11_en.pdf`

## 2. 시스템 구성과 장치 역할

```text
EPICS IOC
  `- asynMotorController / asynMotorAxis
       `- asynOctet
            `- drvAsynIPPort
                 `- Ethernet/TCP
                      `- ARIES
                           |- ARIES 내장 축
                           `- Motionnet 연결 LYNX 확장 축
                                `- TITAN-A2
                                     `- 5상 스테핑 모터 스테이지
```

- ARIES는 PC의 TCP 명령을 받는 주 컨트롤러다.
- LYNX는 Motionnet으로 연결되는 확장 컨트롤러다.
- ARIES와 LYNX는 각각 2축 단위로 모터 제어 신호를 제공한다.
- TITAN-A2는 2축 5상 스테핑 모터 드라이버이며 TCP 통신의 직접 상대가 아니다.
- ARIES는 연결된 LYNX 축을 포함해 최대 32축을 통합 관리한다.

## 3. TCP 통신

### 3.1 기본 설정

매뉴얼에 기재된 ARIES 기본값은 다음과 같다.

| 항목 | 기본값 |
|---|---|
| 동작 모드 | Host(TCP server) |
| IP 주소 | `192.168.1.120` |
| TCP 포트 | `12321` |
| subnet mask | `255.0.0.0` |

실제 장비의 IP, 포트 및 Host 모드는 운용 전에 확인한다. IOC에서는
`drvAsynIPPortConfigure()`로 TCP asyn port를 생성한다.

### 3.2 프레이밍

- Ethernet/TCP 명령에는 STX(`0x02`)를 붙이지 않는다.
- 명령과 응답은 CRLF(`\r\n`)로 끝난다.
- 명령에는 공백을 사용할 수 없다.
- 응답 필드는 TAB(`0x09`)으로 구분된다.
- 컨트롤러는 원칙적으로 명령 하나에 응답 하나를 반환한다.

예시:

```text
송신: APS1/0/1000/1\r\n
정상: C<TAB>APS1\r\n
오류: E<TAB>APS1<TAB>304\r\n
경고: W<TAB>APS1<TAB>350\r\n
```

ARIES는 비상정지나 LYNX 연결 상태 변화가 발생하면 요청과 무관한 `SYS`
오류·경고를 자발적으로 전송할 수 있다. 통신 계층은 수신 행을 예상 명령 응답과
비동기 시스템 이벤트로 구분해야 한다. 비동기 행을 명령 응답으로 잘못 소비하면
후속 응답 전체가 어긋날 수 있다.

### 3.3 응답 방식

이동 명령의 response method는 다음과 같다.

- `0`: 이동 완료 후 응답
- `1`: 명령을 접수하면 즉시 응답(Quick)

IOC는 Quick 방식 `1`을 사용한다. 이동 완료 여부는 poller가 `STR`로 확인한다.
완료 응답 방식은 한 축이 이동하는 동안 통신을 장시간 점유할 수 있으므로 다축 IOC에
적합하지 않다.

## 4. Model 3 메서드와 명령 매핑

| Model 3 동작 | ARIES 명령 | 사용 방안 |
|---|---|---|
| 절대 이동 | `APS` | `APS axis/0/position/1` |
| 상대 이동 | `RPS` | `RPS axis/0/distance/1` |
| 연속 이동 | `FRP` | 방향과 speed table 0 사용 |
| 원점 복귀 | `ORG` | `ORG axis/0/1` |

Model 3 HOME 구현은 `STR<axis>`로 정지와 EMG 입력을 새로 확인하고
`RSY<axis>/2`로 실제 Origin return method를 읽는다. 축별 `OriginMethod` PV의
사용자 선택값과 다르면 `WSY<axis>/2/<method>`로 변경하고 RSY로 재확인한다. 확인된
경우에만 `ORG<axis>/0/1`을 quick response 방식으로 보낸다. Method 10은 speed
table을 사용하지 않으며 나머지 방법은 HOME 요청 속도·가속도를 table 0에 반영한 뒤
ORG를 보낸다. PV 선택만으로 WSY를 전송하지 않는다.
| 정지 | `STP` | 정상 정지는 감속 정지 사용 |
| 위치 좌표 설정 | `WRP` | motor의 set-position 동작에 사용 |
| 현재 위치 조회 | `RDP` | raw pulse 위치를 읽음 |
| 축 상태 조회 | `STR` | 이동, 센서, limit, EMG 상태 |
| 원점 완료 조회 | `ROG` | Homed 상태 갱신 |
| servo 상태 조회 | `RSV` | servo 축에서 ready/on/alarm 확인 |
| 장치 구성 조회 | `RAX` | 실제 연결 축과 장치 구성 확인 |
| 속도표 쓰기 | `WTB` | speed table 0 갱신 |
| 속도표 읽기 | `RTB` | 설정 검증과 진단에 사용 |

초기 구현 대상 `asynMotorAxis` 메서드는 다음과 같다.

```cpp
move()
moveVelocity()
home()
stop()
poll()
setPosition()
```

profile move와 controller-level 동시 이동은 기본 단축 동작이 안정화된 뒤 별도
단계에서 검토한다.

## 5. Speed table 0 운용

모든 일반 motor 동작은 speed table `0`을 사용한다. 드라이버는 이동 직전에
motor record가 전달한 속도와 가속도를 ARIES 단위로 변환하여 `WTB`로 table 0을
갱신한 다음 이동 명령을 보낸다.

`WTB`의 주요 값은 다음과 같다.

- start speed: pulse/s
- top speed: pulse/s
- acceleration time: 설정값 x 10 ms
- deceleration time: 설정값 x 10 ms
- acceleration pattern: rectangular, trapezoidal 또는 S-curve

Model 3이 전달하는 가속도는 pulse/s² 단위로 취급하고, ARIES가 요구하는 가속
시간으로 변환한다. 반올림, 최소값, 최대값 및 ARIES의 속도표 제한을 검사한다.

축별 poll과 명령은 하나의 TCP 연결을 공유하므로 `WTB`와 이어지는 이동 명령은
다른 축의 명령이 중간에 끼지 않도록 동일한 controller lock 안에서 수행해야 한다.

Model 3 `move()`는 fresh `RDP/STR/ROG` snapshot으로 현재 pulse 위치, 이동 상태와
EMG를 확인한다. 절대 명령은 rounded target, 상대 명령은 `current+rounded delta`를
계산하여 raw motor soft-limit 범위 안일 때만 table 0을 설정하고 APS/RPS quick
명령을 보낸다. motor record의 RLV는 record 내부에서 절대 목표로 해석되므로 표준
motor PV 사용 시 APS가 전송된다.

## 6. 상태 매핑

`STR`의 축별 응답에는 다음 정보가 있다.

- driving state: stopped, operating, feedback operating
- emergency-stop 입력
- ORG/NORG 센서 조합
- CW/CCW limit 조합
- positive/negative soft-limit 상태
- encoder correction allowable range

초기 매핑 방안은 다음과 같다.

| 컨트롤러 상태 | EPICS 상태 |
|---|---|
| driving state 0 | `motorStatusDone_=1`, `motorStatusMoving_=0` |
| driving state 1 또는 2 | `motorStatusDone_=0`, `motorStatusMoving_=1` |
| CW limit | high 또는 low limit 후보 |
| CCW limit | low 또는 high limit 후보 |
| EMG 감지 | `motorStatusProblem_=1` |
| `ROG=1` | `motorStatusHomed_=1` |
| ORG 센서 감지 | `motorStatusAtHome_=1` 후보 |
| TCP/응답 실패 | `motorStatusCommsError_=1` |
| servo alarm | `motorStatusProblem_=1` |

CW/CCW를 high/low에 최종 대응시키는 방식은 스테이지별 이동 방향과 motor record의
`DIR`을 함께 고려해야 한다. 실제 스테이지 사양과 저속 시험 전에는 확정하지 않는다.

### 6.1 Software limit 운용 정책

정상 운전 범위는 EPICS motor record의 `HLM`과 `LLM`으로 제한한다. ARIES의
controller soft limit(`SYS 13~15`)은 IOC에서 운용하지 않는다.

ARIES controller soft limit을 IOC가 명시적으로 끄거나 값을 덮어쓰지는 않는다.
장비의 공장 기본 설정을 그대로 유지한다. 매뉴얼상 `SYS 13`의 공장 기본값은 `0`,
즉 controller soft limit 비활성이다. `SYS 14`와 `SYS 15`도 IOC가 변경하지 않는다.

motor record의 `HLM/LLM`은 일반 이동과 jog의 사용자 좌표 범위를 제한하지만,
synApps motor record는 원점 복귀 중 soft-limit 검사를 비활성화한다. ARIES 역시
원점 복귀 중 controller soft limit을 비활성화한다. 따라서 원점 복귀 시에는 선택한
원점 방법과 실제 센서 구성이 일치하는지 사용자가 확인해야 한다.

Hardware CW/CCW limit은 soft limit과 별개의 입력이다. `STR` 응답에서도 hardware
limit 상태와 controller soft-limit 상태는 서로 다른 필드로 제공된다.

### 6.2 Emergency-stop latch

Emergency-stop 입력으로 `E SYS 5`가 발생하면 물리적 원인을 해결한 뒤 `REM`으로
software lock을 해제한다. 이동 중 Motionnet 연결 이상으로 `E SYS 6`이 발생하면
연결 문제를 해결한 뒤 `RAX`로 축 구성을 다시 확인해야 한다. 두 원인이 함께
발생하면 `REM`과 `RAX`가 모두 필요하다.

IOC가 오류 수신 즉시 해제 명령을 자동 실행하지 않는다. GUI에서 원인 해결을 확인한
사용자가 reset을 요청했을 때만 해제 절차를 수행한다. Emergency stop 이후에는 위치
불일치 가능성이 있으며 `ROG`도 incomplete가 되므로 재원점 복귀가 필요할 수 있다.

## 7. 오류와 경고 진단

드라이버는 응답 문자열뿐 아니라 매뉴얼의 코드 의미를 해석해 제공한다. 축 오류와
시스템 오류는 별도로 유지한다.

권장 진단 항목은 다음과 같다.

```text
LAST_ERROR_CODE
LAST_ERROR_TEXT
LAST_ERROR_COMMAND
LAST_WARNING_CODE
LAST_WARNING_TEXT
LAST_RAW_RESPONSE
COMMUNICATION_STATE
```

GUI에는 다음과 같은 형태로 표시한다.

```text
축 1: CW limit가 감지되어 이동이 중지되었습니다.
명령: APS
코드: 304
```

처리 원칙:

- 원본 응답은 진단을 위해 보존한다.
- 코드 설명은 운전자가 이해할 수 있는 문장으로 제공한다.
- 알 수 없는 코드는 숫자와 원본 응답을 반드시 표시한다.
- 오류가 사라진 현재 상태와 마지막 오류 이력은 구분한다.
- 비동기 `SYS` 오류·경고는 controller-level 상태로 기록한다.
- motor 동작에 영향을 주는 오류는 `motorStatusProblem_`에도 반영한다.
- 통신 장애는 동작 오류와 구별하여 `motorStatusCommsError_`에 반영한다.

전체 오류·경고 대응표는 C++ 구현 전에 매뉴얼 목록을 바탕으로 별도 검토한다.

## 8. 축 구성

IOC와 database는 최대 32축까지 대응하도록 설계한다. 현재 실제 운용 대상은 5축이다.

- controller 생성 시 최대 축 수를 32로 구성할 수 있다.
- 시작할 때 `RAX`를 읽어 실제 연결된 축과 사용 가능 축을 확인한다.
- 연결되지 않은 축은 disabled/unavailable 상태로 표시한다.
- GUI는 실제 사용 가능한 축만 생성 후보로 제시한다.
- LYNX 추가 후에는 IOC를 재시작하여 새 구성을 다시 확인한다.

GUI에서 패널을 삭제해도 `asynMotorAxis`와 motor record는 삭제하지 않는다. 패널은
단지 해당 PV를 표시하는 client-side 객체다.

## 9. TITAN-A2 M1 및 motor resolution

### 9.1 확정된 운용 설정

- 컨트롤러와 TITAN-A2는 모두 M1 선택 상태다.
- M1 physical switch는 공장 기본 위치 `1`을 유지한다.
- TITAN-A2 표에서 스위치 위치 1은 2분할, 즉 half-step이다.
- 현재 프로젝트에서는 M2와 운전 중 micro-step 전환을 사용하지 않는다.

따라서 스테이지 모델의 motor resolution은 제조사 사양의 `Half Step` 값을
우선 사용한다.

예시 사양:

```text
Lead: 1.0 mm
Full/Half step resolution: 1.0 / 0.5 um
Micro-step 1/20 resolution: 0.05 um
```

이 사양에서 full-step당 이동은 1 um이고, lead 1 mm이므로 회전당 1,000 full
step이다. 기본 step angle은 다음과 같이 역산된다.

```text
360 deg / 1000 = 0.36 deg/full-step
```

M1 half-step 운용 시 실제 명령 resolution은 다음과 같다.

```text
0.5 um/pulse = 0.0005 mm/pulse
MRES = 0.0005 mm
```

제조사 표의 `1/20 = 0.05 um` 값은 M2 또는 분할 수 20을 선택할 때의 값이며,
현재 M1 기본 운용에는 사용하지 않는다.

### 9.2 RUN과 STOP

TITAN-A2 공장 기본 RUN switch 위치는 5이며 `0.75 A/phase`다. 실제 모터의 정격
phase current가 이 값에 적합한지 스테이지별로 확인한다.

공장 기본 STOP switch 위치는 6이며 RUN 전류의 48%다. RUN이 0.75 A/phase이면
정지 전류는 약 0.36 A/phase다. 정지 전류를 낮추면 발열은 줄지만 holding torque도
낮아진다. 수직축과 외력이 작용하는 축은 별도 검토한다.

## 10. 스테이지 모델 설정과 교체

스테이지 모델 설정에는 최소한 다음 정보가 필요하다.

- model name
- engineering unit
- lead 또는 회전당 이동량
- full/half-step resolution
- motor 기본 step angle
- M1 분할 수
- travel range
- 권장 최고 속도와 가속도
- CW/CCW와 사용자 좌표 방향의 관계
- motor 정격 phase current

축 번호는 controller의 전기적 채널이고, 스테이지 모델은 그 채널에 연결된 기계의
설정 묶음이다. 같은 축에 다른 스테이지를 연결할 수 있지만 모델 설정만 즉시 바꾸는
방식은 허용하지 않는다.

스테이지 제품 사양만으로는 실제 설치된 센서 구성을 결정할 수 없다. 같은 모델에도
설치 조건에 따라 CW/CCW limit, ORG, NORG 또는 encoder Z 센서가 추가되거나 빠질 수
있다. 따라서 센서 구성과 원점 복귀 방법은 스테이지 모델 정보와 분리하여 축별 설치
설정으로 관리한다.

### 10.1 축별 센서와 원점 설정

사용자는 GUI에서 축마다 실제 설치된 센서와 원점 복귀 방법을 선택한다.

```text
axis number
stage model
CW limit installed
CCW limit installed
ORG installed
NORG installed
encoder Z installed
limit/ORG/NORG logic
origin method (SYS 2)
origin offset (SYS 1)
origin scan speed (SYS 3)
```

GUI는 사용자가 입력한 센서 조합에 맞는 방법을 우선 제안한다.

| 설치 센서 예 | 원점 방법 후보 |
|---|---|
| ORG + NORG + CCW limit | Method 3 |
| NORG + CCW limit | Method 4 |
| ORG + CW limit | Method 5 |
| ORG + CCW limit | Method 6 |
| CW limit | Method 7 |
| CCW limit | Method 8 |
| ORG | Method 9 |
| 센서 없음 | Method 10 |
| encoder Z 포함 | Method 11~15 중 해당 방법 |

센서가 없는 Method 10은 움직이지 않고 현재 controller 위치를 원점으로 간주한다.
따라서 손으로 축을 움직였거나 step loss가 발생한 경우 실제 절대 위치를 복구하지
못한다. 센서가 원래 없는 경우와 설치된 센서가 고장 난 경우도 구분해야 한다.

초기 구현에서는 복잡한 homing watchdog을 필수 범위로 정하지 않는다. 선택한 센서
구성과 원점 방법이 일치하지 않으면 경고하고, `ROG`로 완료 여부를 확인하며, 실패한
경우 homed 상태를 완료로 만들지 않는 수준부터 구현한다.

모델 교체 절차:

1. 축 정지 확인
2. motor record와 GUI 이동 명령 비활성화
3. 필요하면 motor excitation 해제
4. 스테이지 교체
5. TITAN RUN, STOP, M1 physical switch 확인
6. 모델별 MRES, EGU, 방향, motor record `HLM/LLM`, 속도 및 가속도 적용
7. 실제 센서 구성과 원점 방법 설정 확인
8. 이전 위치와 homed 상태 무효화
9. 짧은 거리 저속 이동으로 방향, scale 및 limit 확인
10. 원점 복귀
11. 정상 조작 활성화

MRES가 바뀌면 같은 raw pulse 위치도 다른 사용자 위치로 환산된다. 물리 스테이지를
교체한 뒤 이전 좌표를 그대로 신뢰해서는 안 된다.

## 11. GUI 설계 원칙

GUI 사용 흐름은 다음을 목표로 한다.

1. `RAX` 결과에 따라 사용 가능한 축 번호 1~32 중 하나 선택
2. 등록된 스테이지 모델 선택
3. 실제 설치된 센서 구성과 원점 방법 선택
4. 생성 버튼으로 조작 패널 표시
5. 삭제 버튼으로 패널만 제거
6. 같은 축의 모델 변경 시 안전 재설정 절차 실행

패널 중복, 하나의 물리 축에 대한 상충 명령 및 미연결 축 선택을 막아야 한다.
동적 widget 생성과 향후 Ophyd 연계를 고려하면 PyDM/PyQt가 우선 후보지만 GUI
도구는 아직 확정하지 않는다.

> 2026-08-04 갱신: 현재 설치 환경에 PyDM/PyQt/tkinter가 없어, 추가 package 없이
> 실행 가능한 localhost 웹 GUI를 첫 구현으로 선택했다. 상세 안전 범위와 실행법은
> `docs/06-dynamic-gui-foundation.md`를 따른다.

## 12. 미확정 항목

다음 정보는 스테이지 모델 자료 또는 실제 장비 시험 후 확정한다.

- 실제 ARIES IP 주소와 포트
- 실제 연결된 ARIES/LYNX 구성 및 `RAX` 응답
- 각 축의 스테이지 모델과 motor 정격 전류
- 각 모델의 MRES, travel limit 및 방향
- 각 축에 실제 설치된 센서 구성과 원점 방식
- CW/CCW limit와 EPICS high/low limit의 최종 대응
- speed table 0의 가속 pattern
- 정상 정지와 긴급 정지의 GUI 노출 방식
- 오류 복구 명령을 자동 실행할지 사용자 확인 후 실행할지 여부
- GUI 프레임워크

## 13. 다음 구현 단계 제안

다음 단계에서는 IOC 동작을 넣기 전에 빌드 가능한 프로젝트 골격을 생성한다.

예상 산출물:

```text
configure/RELEASE
kohzuAriesLynxApp/src/KohzuAriesLynxController.h
kohzuAriesLynxApp/src/KohzuAriesLynxController.cpp
kohzuAriesLynxApp/src/Makefile
kohzuAriesLynxApp/Db/Makefile
iocBoot/iocKohzuAriesLynx/st.cmd
```

첫 골격 단계에서는 네트워크 명령이나 모터 이동을 구현하지 않고 EPICS Base,
asyn 및 motor 라이브러리 링크와 IOC shell 등록 구조까지만 만든다.
