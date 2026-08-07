# 실제 ARIES/LYNX 연결 및 시운전 기록

## 범위와 현재 상태

- controller endpoint: `10.1.101.51:12321`
- 실제 모터 스테이지 연결: 축 1만 연결했다고 사용자가 확인
- production IOC: 계속 비활성
- motor record Enable, HOME, MOVE, JOG, STOP, WRP, WSY, WTB, REM: 실행하지 않음
- 이번 단계: raw TCP 읽기 전용 식별·구성·축 상태·설정 조회만 수행

RAX가 보고하는 axis device와 실제 TITAN-II에 연결된 모터 스테이지는 구분한다.
RAX에서 여러 축이 보이더라도 해당 축에 모터 부하가 연결됐다는 뜻은 아니다.

## 2026-08-04 읽기 전용 확인

TCP 포트 연결에 성공했다.

```text
10.1.101.51:12321 open
```

실제 전송과 원문 응답은 다음과 같다. 모든 명령은 manual상 read 계열이며 controller
설정이나 축 위치를 변경하지 않는다.

```text
IDN
C\tIDN\tARIES\t1\t4\t4

RAX
C\tRAX\t6\t6\t11111100\t00000000\t00000000\t00000000
     \t00000000\t00000000\t00000000\t00000000

RDP1
C\tRDP1\t56000

STR1
C\tSTR1\t0\t0\t0\t0\t0\t0

ROG1
C\tROG1\t0

RSY1/2
C\tRSY1\t2\t4

RSY1/16
C\tRSY1\t16\t50000
```

해석:

- IDN: ARIES version 정보 필드는 `1,4,4`; mock의 `1,4,3`과 다르지만 parser는 전체
  field를 문자열로 보존하므로 현재 구현과 호환
- RAX: 총 device 6, 제어 가능 axis 6, axis device 1~6 존재
- RDP1: 현재 controller pulse 좌표 56,000
- STR1: 정지, EMG OFF, ORG/NORG OFF, CW/CCW limit OFF, controller soft-limit 내부,
  encoder correction 허용 범위 밖
- ROG1: power-on 이후 원점 복귀 미완료
- SYS.2: 현재 Origin return Method 4
- SYS.16: 현재 최고 속도 상한 50,000 pulse/s

STR의 correction allowable stop range가 0인 것은 encoder feedback 설정과 함께 해석해야
한다. 현재 단계에서는 오류로 단정하거나 SYS 값을 변경하지 않는다.

## 다음 장비 단계

production IOC 전체를 바로 활성화하지 않는다. 다음에는 별도의 실제 장비용 read-only
IOC startup 파일을 만들어 controller 32축 slot 중 RAX가 보고한 1~6축만 polling하고,
모든 motor record가 Disable 상태인지 확인한다. 이 시험에서는 다음을 금지한다.

- motor record Enable
- HOME/ORG
- VAL/RLV/JOG
- STOP/WRP
- SYS/WTB write
- REM 및 추가 recovery 명령

read-only IOC 결과가 raw TCP 결과와 일치한 뒤 축 1의 모델 설정 적용과 저속 시운전을
별도 승인 단계로 진행한다.

read-only startup 파일은 다음 위치에 둔다.

```text
iocBoot/iockohzuAriesLynx/readOnlyHardware.cmd
```

이 파일은 motor/diagnostics/commissioning database를 로드하지 않으며 2.2초 polling 후
report를 출력하고 자동 종료한다.

### read-only IOC 실행 결과

실제 endpoint로 한 번 실행했으며 정상 종료했다.

```text
identity: ARIES 1 4 4
configured axes: 32
detected axes: 6
communication: connected
axis 1: position=56000 moving=no homed=no CW-limit=no CCW-limit=no EMG=no
axis 2: position=-15585 moving=no homed=no CW-limit=yes CCW-limit=yes EMG=no
axis 3: position=-9999  moving=no homed=no CW-limit=yes CCW-limit=yes EMG=no
axis 4: position=-179   moving=no homed=no CW-limit=yes CCW-limit=yes EMG=no
axis 5: position=45499  moving=no homed=no CW-limit=yes CCW-limit=yes EMG=no
axis 6: position=0      moving=no homed=no CW-limit=yes CCW-limit=yes EMG=no
```

축 1은 raw TCP 결과와 일치한다. 축 2~6에서 CW/CCW limit가 동시에 검출되는 것은
사용자가 확인한 미연결 스테이지 상태와 일치하는 미사용 입력으로 취급한다. RAX가
axis device 6개를 보고했다는 이유만으로 이 축들을 Enable하거나 이동하지 않는다.
다음 실제 동작 시험 대상은 축 1로만 제한한다.

## 2026-08-04 축 1 IOC 저속 왕복 시험

`axis1HardwareTest.cmd`로 실제 controller에 연결해 축 1 motor record만 로드했다.
HOME, JOG, WRP, WSY, REM은 실행하지 않았다. 시험 전후에는 motor record를 Disable로
유지했으며 시험이 끝난 뒤 IOC를 종료했다.

시험 결과:

```text
controller: connected, ARIES 1 4 4, detected axes 6
initial:  RBV=56000 pulse, DMOV=1, MOVN=0, HLS=0, LLS=0, EMG=0
forward:  RLV=+100 pulse, final RBV=56100 pulse
return:   RLV=-100 pulse, final RBV=56000 pulse
final:    DMOV=1, MOVN=0, HLS=0, LLS=0, Disable
diagnostic: LastErrorCode=0, LastWarningCode=0
```

속도 table 0은 시작 100 pulse/s, 최고 200 pulse/s, 가속도 200 pulse/s²로 설정했고
motor record의 `VELO=200 pulse/s`, `VBAS=100 pulse/s`, `ACCL=0.5 s`로 시험했다.
두 이동 모두 driver가 APS 요청을 수락했고 원래 controller 좌표로 복귀했다. 정지
상태에서 motor record STOP도 호출해 정상 명령 경로를 확인했다.

## 2026-08-04 축 1 HOME 및 소프트 리미트 시험

축 1에 XA05A-L202 설정(`MRES=0.0005 mm/pulse`, `DIR=Pos`)을 적용하고 Method 4
HOME을 실행했다. ORG가 정상 수락되었고 완료 후 controller 상태는 `homed=yes`,
위치는 `0`이었다. 실제 `SYS.2` readback도 Method 4와 일치했다.

초기 시운전 속도 `0.5 mm/s`로 소프트 리미트 양 끝과 원점을 순서대로 이동했다.

```text
HOME:       0 mm, homed=yes
high limit: +24.5 mm, HLS=0, LLS=0, LVIO=0
low limit:  -24.5 mm, HLS=0, LLS=0, LVIO=0
final:       0 mm, DMOV=1, MOVN=0, Disable
diagnostic: LastErrorCode=0, LastWarningCode=0
```

두 끝점은 제조사 기계 범위 ±25 mm에서 각각 0.5 mm 안쪽이며, 시험 중 물리 limit
입력은 작동하지 않았다. 시험 후 원점으로 복귀하고 축을 Disable한 다음 IOC를
종료했다.

## 2026-08-04 축 1 JOG 및 이동 중 STOP 시험

원점 `0 mm`에서 `JVEL=0.1 mm/s`로 정방향 JOG를 실행했다. driver는 CW 방향 FRP를
수락했고 2초 후 motor record STOP으로 정상 감속 정지하여 `RBV=+0.1995 mm`가
되었다. 이어 역방향 JOG를 실행했으며 JOG 버튼 해제 경로가 CCW 방향 FRP 뒤
`STP1/0`을 보내 정상 정지했다.

```text
forward JOG + STOP: RBV=+0.1995 mm, DMOV=1, MOVN=0
reverse JOG release: RBV=0 mm, DMOV=1, MOVN=0
limits: HLS=0, LLS=0
diagnostic: LastErrorCode=0, LastWarningCode=0
final: 0 mm, Disable
```

시험 후 축을 Disable하고 IOC를 종료했다.

## 2026-08-04 축 2 HOME 및 소프트 범위 시험

축 2 전용 `axis2HardwareTest.cmd`로 XA05A-R201 설정을 로드했다. 시작 위치는
controller 좌표 `-15585 pulse`였고 EMG 및 양쪽 limit 입력은 비활성이었다.

Method 4 HOME은 CCW limit까지 접근한 뒤 자동으로 방향을 반전하고 NORG를 찾아
정상 완료했다. 첫 시도에서는 HOME 전용 `HVEL`과 `VBAS`가 같아 speed-table 검증에서
이동 전에 차단되었으며, `HVEL=0.1 mm/s`, `VBAS=0.025 mm/s`로 수정했다.

```text
HOME: Method 4, CCW limit -> reverse -> NORG, final RBV=0 mm
high test: +7.349 mm, HLS=0, LLS=0, LVIO=0
low test:  -7.349 mm, HLS=0, LLS=0, LVIO=0
final: 0 mm, DMOV=1, MOVN=0, Disable
diagnostic: LastErrorCode=0, LastWarningCode=0
```

정확한 `+7.350 mm` 요청은 raw pulse 변환 결과가 표시상 상한 `14700 pulse`와 같았지만
부동소수점 경계 비교에서 범위 밖으로 판정되어 driver가 이동 전에 차단했다. 1 um
안쪽인 `±7.349 mm` 시험은 정상 완료했다.

이후 soft-limit 비교에 IEEE-754 표현 오차만 허용하는 ULP 기반 tolerance를 추가하고
단위시험과 mock TCP 통합시험을 통과했다. 수정된 driver로 정확한 `+7.350 mm`
(`14700 pulse`)를 실제 장비에서 다시 요청해 정상 수락 및 도착을 확인했다.

축 2 JOG/STOP 시험도 이어서 수행했다.

```text
forward JOG + STOP: 0 -> +0.2115 mm, CW, 정상 정지
reverse JOG release: +0.2115 -> +0.0010 mm, CCW, 정상 정지
final absolute return: 0 mm
limits: HLS=0, LLS=0
diagnostic: LastErrorCode=0, LastWarningCode=0
final state: DMOV=1, MOVN=0, Disable
```

시험 중 `DISP=1`이 정상적인 절대 목표와 JOG write까지 막는 것을 확인했다. 이후
commissioning을 단순화해 `DISP`를 운전 잠금에서 제거하고 `_able`만 명령 허용 상태로
사용하도록 변경했다. EnableRequest는 정지 상태만 확인하며 확인 PV는 기록용이다.

## 2026-08-05 축 3 수동 중심 원점 시험

축 3 ZA05A-W101은 물리 limit 센서가 고장 난 상태이므로 센서 기반 HOME을 사용하지
않고 작업자가 실제 위치를 관찰하며 저속 이동했다. controller CW가 아래쪽이고
CCW가 위쪽임을 확인했으며, `DIR=Neg` 적용 시 EPICS `+Z`가 위쪽이 되는 것도
readback으로 검증했다.

초기 위치에서 아래쪽으로 1 mm, 2 mm, 2 mm, 1 mm, 0.4 mm를 순차 이동해 아래쪽
안전 끝 후보를 찾았다. 그 위치에서 위쪽으로 4 mm 이동한 지점을 Method 10으로
원점 지정했다. 이후 위쪽 `+3.9 mm`와 아래쪽 `-4.0 mm`를 실제로 확인하고 원점으로
복귀했다.

```text
direction: controller CW=down, CCW=up, motor DIR=Neg
resolution: 0.00025 mm/pulse
origin: Method 10, RBV=0, raw=0, homed=yes
upper test: +3.90000 mm, raw=-15600 pulse
lower test: -4.00000 mm, raw=+16000 pulse
final: 0 mm, DMOV=1, MOVN=0, Disable
limits: HLS=0, LLS=0, LVIO=0 (physical limit inputs are not trusted)
diagnostic: LastErrorCode=0
```

아래쪽 끝 확인 동안 LLM을 임시 `-4.0 mm`로 확장했으나 시험 후 정식 운전 범위
`LLM=-3.92 mm`, `HLM=+3.92 mm`로 복원했다. 방향, 고장 센서 상태, 범위 및 원점
확인값을 기록한 뒤 IOC를 종료했다.

## 2026-08-05 축 4 Pitch 시험

축 4 SA05A-R2B01에서 controller CW가 스테이지 앞쪽을 올리는 방향임을 작업자가
확인했다. 이를 EPICS `+Pitch`로 정의하고 `DIR=Pos`를 유지했다. Method 4 HOME은
정상 완료되어 `RBV=0`, `homed=yes`, 실제 SYS.2=4로 확인됐다.

계산상 소프트 범위 `±3.43°`는 분해능 `0.000637°/pulse`에서 5384.615 pulse가 되어
정확히 표현할 수 없다. 바깥쪽 5385 pulse 요청은 driver가 차단했고, 안쪽 5384 pulse에
해당하는 `±3.429608°`는 양방향 모두 정상 도착했다.

```text
direction: CW=front up=+Pitch, DIR=Pos
origin: Method 4, RBV=0, homed=yes
high test: +3.429608 deg, raw=+5384 pulse
low test:  -3.429608 deg, raw=-5384 pulse
final: 0 deg, DMOV=1, MOVN=0, Disable
limits: HLS=0, LLS=0, LVIO=0
diagnostic: LastErrorCode=0
```

catalog과 축 4 시험 IOC의 정식 LLM/HLM도 `±3.429608°`로 보정했다.

## 2026-08-05 축 5 Method 4 센서 확인

축 5 RA04A-W01에 실제 NORG 센서가 있는지 확인하기 위해 Method 4를 관찰 실행했다.
시작 좌표는 `+90.998°`였다. 축은 CCW limit 방향으로 이동한 뒤 limit를 감지해
정상적으로 반전했지만, 이후 CW 방향 전 범위에서 NORG를 검출하지 못하고 계속
이동했다. `+194°`를 넘어선 것을 확인해 STOP했으며 감속 정지 좌표는 `+222.58°`였다.

```text
Method 4: accepted
CCW limit phase: detected and reversed
NORG phase: no sensor detected; HOME did not complete
ROG/homed: false
controller error: 0
```

따라서 제조사 사양과 같이 축 5에는 Method 4에 필요한 NORG 센서가 없는 것으로
판정했다. STOP 후 Method 선택을 10으로 되돌리고 시험 시작 좌표 `+90.998°`로
복귀한 다음 Disable 상태에서 IOC를 종료했다. 축 5의 정상 원점 정책은 계속
Method 10이며, 실제 중심을 확인한 위치에서만 실행한다.

### 축 5 CW/CCW 하드 리미트와 중심 확인

사용자 확인에 따라 위에서 볼 때 CW를 시계방향/EPICS `+Yaw`, CCW를
반시계방향/EPICS `-Yaw`로 정의하고 `DIR=Pos`를 유지했다. 기존 좌표가 중심에서 크게
어긋나 있었으므로 commissioning 중 소프트 범위를 임시 확장하고 양쪽 하드 리미트를
JOG로 직접 확인했다.

```text
CW hard limit:  raw=178676 pulse, old RBV=+357.352 deg, HLS=1
CCW hard limit: raw=1 pulse,      old RBV=+0.002 deg,   LLS=1
measured span:  178675 pulse = 357.350 deg
midpoint:       89338.5 pulse
selected center: 89338 pulse (mathematical center -0.001 deg)
```

raw `89338 pulse` 위치로 이동한 뒤 Method 10을 실행해 controller 좌표와 EPICS RBV를
0으로 설정했다. 반 pulse 중간점은 표현할 수 없어 중심 오차는 0.001°다. 시험 후
운전 소프트 범위를 catalog의 보수적인 `LLM=-173.46°`, `HLM=+173.46°`로 복원하고
축을 Disable한 뒤 IOC를 종료했다. 물리 CW/CCW limit는 모두 존재하고 정상 동작하지만
NORG 센서는 없으므로 Method 4는 사용할 수 없다.

### 축 5 CCW limit 원점으로 변경

중심 원점이 육안상 약간 어긋나 보인다는 사용자 판단에 따라 축 5 원점 정책을
CCW limit 기반 Method 8로 변경했다. 기존 중심 좌표 0에서 Method 8을 실행했으며
CCW 방향으로 이동해 limit를 찾은 뒤 정상 완료했다.

```text
OriginMethod selected/actual: 8 / 8
home result: RBV=0 deg, raw=0, homed=yes
direction: CW=positive, CCW=negative
final: DMOV=1, MOVN=0, Disable
```

기존 중심 기준 운전 범위 `-173.46~+173.46°`와 같은 물리 안전 영역을 새 CCW 원점
좌표로 변환하여 `LLM=+5.214°`, `HLM=+352.134°`로 설정했다. 이 범위는 양쪽 물리
하드 리미트에서 각각 약 5.2° 안쪽이다. catalog, axis assignment와 축 5 시험 IOC도
Method 8 및 새 좌표 범위로 갱신했다.

### 축 5 50% VMAX 절대 이동

Method 8 CCW 원점 `0°`에서 모델 최고속도 `20°/s`의 50%인 `10°/s`로 절대 위치
`180°`를 요청했다. speed table 0과 SYS.16 검증 후 APS가 수락되었으며 약 20초 안에
목표 raw `90000 pulse`에 도착했다.

```text
start: 0 deg
target/final: 180 deg = 90000 pulse
velocity: 10 deg/s = 5000 pulse/s
final: DMOV=1, MOVN=0, HLS=0, LLS=0, LVIO=0, Disable
diagnostic: LastErrorCode=0, LastWarningCode=0
```
