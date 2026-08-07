# Ophyd/Bluesky 실제 IOC 연동 기록

## 목적

KOHZU ARIES/LYNX IOC의 표준 EPICS motor record를 classic Ophyd `EpicsMotor`로
연결하고, Bluesky RunEngine에서 안전하게 읽기·이동·스캔할 수 있는지 단계적으로
검증한다. GUI와 detector는 이번 최초 모터 연동 범위에 포함하지 않는다.

기초 설명과 설치 참고는 `docs/08-ophyd-bluesky-basics.md`를 따른다.

## 시험 원칙

- IOC와 Ophyd는 서로 다른 터미널에서 실행한다.
- 처음에는 실제 이동 없이 연결과 readback만 확인한다.
- 한 번에 한 축만 Enable하고 시험한다.
- 실제 이동 전 현재 위치, 소프트 리미트, `DMOV`, `MOVN`, `LVIO`, `HLS`, `LLS`를 확인한다.
- 최초 이동은 이동 범위 중앙에서 작은 상대 이동으로 수행하고 원래 위치로 복귀한다.
- 3번 축은 센서 고장 때문에 Method 10 원점이 확실할 때만 시험한다.
- 5번 축은 Method 8 원점 `0°`가 운전 소프트 범위 밖이므로 원점 주변 왕복 시험을 하지 않는다.
- 사용자가 전달한 터미널 출력과 물리 관찰 결과를 근거로 각 단계를 완료 처리한다.

## 환경

| 항목 | 값 |
|---|---|
| 시험 날짜 | 2026-08-06 |
| conda 환경 | `kohzu-bluesky` 예정 |
| Ophyd API | classic `ophyd.EpicsMotor` |
| IOC prefix | `KOHZU:` |
| motor PV | `KOHZU:m1` ~ `KOHZU:m5` |
| controller | `10.1.101.51:12321` |

## 진행 상태

| 단계 | 내용 | 상태 |
|---:|---|---|
| 1 | conda 환경 생성 및 패키지 설치 | 완료 |
| 2 | IOC 실행과 `caget` 연결 확인 | 완료 |
| 3 | Ophyd 1번 축 연결 및 읽기 전용 확인 | 완료 |
| 4 | Ophyd 1번 축 소량 왕복 이동 | 완료 |
| 5 | 2·4·5번 축 Ophyd 검증 | 진행 예정 |
| 6 | 3번 축 조건부 Ophyd 검증 | 진행 예정 |
| 7 | Bluesky RunEngine `mv`/`mvr` 검증 | 완료 |
| 8 | 검출기 없는 소규모 `list_scan` | 완료 |
| 9 | 정지·예외·소프트 리미트 처리 | 진행 예정 |

## 단계별 결과

### 1. conda 환경과 패키지

2026-08-06 완료.

```text
conda 25.7.0
Python executable: /home/changhui1788/.conda/envs/kohzu-bluesky/bin/python
Python 3.11.15
ophyd 1.11.2
bluesky 1.15.1
pyepics 3.5.10
```

conda가 26.7.0 업데이트를 알렸지만 환경 생성 및 패키지 import에는 영향이 없는 단순
업데이트 안내이므로 이번 연동 중 conda 자체는 변경하지 않는다. `kohzu-bluesky`
환경이 시스템 Python과 분리돼 있고 필요한 세 패키지의 import가 모두 성공했다.

### 2. IOC 및 Channel Access

축 1 전용 실제 controller IOC를 실행하고 Channel Access를 localhost로 제한한 뒤
motor record를 읽었다.

```text
RBV=0 mm
DMOV=1
MOVN=0
LVIO=0
HLS=0
LLS=0
MSTA=16386 (0x4002: done 및 homed)
DESC=KOHZU XA05A-L202
EGU=mm
MRES=0.0005 mm/pulse
LLM=-24.5 mm
HLM=+24.5 mm
_able=Disable
```

나머지 조회값도 예상값과 일치했고 IOC 오류는 보고되지 않았다. 실제 이동 없이
controller → IOC → Channel Access 읽기 경로와 검증된 축 1 모델 설정을 확인했다.

### 3. Ophyd 읽기 전용 연결

Ophyd 1.11.2의 classic `EpicsMotor("KOHZU:m1", name="x")`를 생성했다. 이전 안내의
`x.done`은 이 버전에 존재하지 않으며 정확한 component는 `x.motor_done_move`다.
`MOVN`은 `x.motor_is_moving`으로 읽는다.

`x.read()`는 `KOHZU:m1.RBV`와 `KOHZU:m1.VAL`을 각각 `x`, `x_user_setpoint`으로
반환했다. `x.describe()`는 `units=mm`, control limits `-24.5/+24.5`, precision 4를
정확히 표시했으므로 motor record 구조 인식은 정상이다.

관찰된 timestamp `631152000.0`은 Unix 기준 1990-01-01이며 EPICS epoch 0에 해당한다.
현재 record timestamp가 설정되지 않았을 가능성이 있으므로 `caget -a`와 PyEPICS
signal timestamp를 추가 확인한 뒤 읽기 전용 단계를 완료한다.

추가 확인에서 `RBV`, `VAL`, `DMOV`가 모두 `<undefined>`였다. 이 motor record는
`SCAN=Passive`, `PINI=NO`이며 IOC 시작 후 아직 한 번도 process되지 않았기 때문이다.
Disable 상태에서는 `.PROC=1`도 SDIS에 의해 차단됐다. 정지 축을 개발용 Enable한 뒤
같은 목표 위치에서 한 번 process하고 즉시 Disable하자 이동 없이 다음 timestamp가
정상 생성됐다.

```text
2026-08-07 09:28:02.309997
RBV=0, VAL=0, DMOV=1, MOVN=0, final _able=Disable
```

사용자 결정에 따라 motor record의 `PINI`나 driver를 변경하지 않는다. IOC 시작 직후
한 번도 process되지 않은 motor record의 timestamp가 undefined일 수 있음을 인지하고,
최초 process 이후 유효해지는 현재 동작을 유지한다. Ophyd 값과 연결 자체는 정상이다.

conda 환경의 Ophyd로 최종 읽기 전용 확인:

```text
x.value=0.0 mm
x_user_setpoint=0.0 mm
timestamp=1786062482.309996
datetime=2026-08-07 09:28:02.309996 KST
motor_done_move=1
motor_is_moving=0
```

따라서 1번 축 `EpicsMotor` 연결, 값, metadata, 완료 상태 및 최초 process 이후 timestamp가
정상임을 확인했다.

### 4. Ophyd 실제 이동

축 1을 `Commissioning:EnableRequest`의 `EpicsSignal.put(1, wait=True)`로 Enable했다.
요청 PV는 자동으로 Idle로 복귀했고 `_able=Enable`을 확인했다. 이후 다음 Ophyd 절대
이동을 실행했다.

```python
status = x.set(0.1)
status.wait(timeout=10)
```

결과:

```text
status.done=True
status.success=True
position=0.1 mm
DMOV=1
MOVN=0
LLS=0
HLS=0
readback timestamp=1786064365.343006
setpoint timestamp=1786064364.631437
```

Ophyd `MoveStatus`가 motor record의 완료 상태를 정상 추적했고, 명령 시각과 실제 도착
readback 시각도 유효하게 구분됐다.

`x.set(0.0)`으로 복귀한 결과도 `done=True`, `success=True`, `RBV=0`, `DMOV=1`,
`MOVN=0`, 양쪽 limit 0이었다. `DisableRequest.put(1, wait=True)` 후 요청 PV는 Idle로
복귀하고 `_able=Disable`을 확인했다. 최종 readback timestamp는
`1786064700.685644`, setpoint timestamp는 `1786064699.976507`이었다. 사용자가 물리
동작도 모두 예상대로였음을 확인했다. 축 1 Ophyd 단독 왕복 이동 시험을 완료한다.

### 5. Bluesky plan

축 1에서 `RunEngine({})`을 생성하고 초기 `RE.state='idle'`을 확인했다. 개발용
Enable 후 다음 plan을 실행했다.

```python
RE(bps.mv(x, 0.1))
RE(bps.mvr(x, -0.1))
```

절대 이동 후 `0.1 mm`, 상대 이동 후 `0.0 mm`였고 두 plan 모두 예상대로 빈 UID
tuple을 반환했다. 각 이동 후 `DMOV=1`, `MOVN=0`, 양쪽 limit 0, `RE.state='idle'`이었고
최종 Disable도 정상 동작했다. 사용자가 실제 왕복 동작도 정상임을 확인했다.

검출기 없이 다음 절대 위치 목록으로 `list_scan`을 실행했다.

```python
positions = [-0.1, 0.0, 0.1, 0.0]
RE(bp.list_scan([], x, positions), LiveTable([x]))
```

LiveTable은 4개 point에서 `x`와 `x_user_setpoint`가 각각
`-0.1000, 0.0000, 0.1000, 0.0000 mm`로 일치함을 표시했다. 실행 시각은
14:32:11.6~14:32:14.0, scan number는 1, Run Start UID의 표시 prefix는
`7dbc74f0`이었다. 실행 후 `RE.state=idle`, 위치 0, 완료/리미트/Disable 상태도 모두
예상과 일치했다. Bluesky run 및 Event 문서 생성 경로를 확인했다.

### 6. 이동 중 STOP과 MoveStatus 경쟁 조건

축 1에서 기본 `EpicsMotor`로 목표 `10.0 mm` 이동을 시작하고 `MOVN=1`, `DMOV=0`을
확인한 뒤 같은 Python 셀에서 `stop(success=False)`를 실행했다. 실제 축은
`5.025 -> 5.053 mm`에서 정상 감속 정지했고 최종 `DMOV=1`, `MOVN=0`, `MSTA=16386`,
`LVIO=0`, `_able=Enable`이었다. 하지만 진행 중이던 `MoveStatus`는
`done=True`, `success=True`로 완료됐다.

원인은 Ophyd 1.11.2 기본 `EpicsMotor.stop()`이 `.STOP`을 먼저 쓴 뒤
`PositionerBase.stop(success=False)`를 호출하는 동안, 빠른 DMOV 완료 콜백이
리미트/알람 없는 정지 상태를 먼저 성공으로 완료하는 경쟁 조건이다. IOC와 물리
STOP의 오류가 아니며 기본 `EpicsMotor`는 목표값과 최종 위치를 비교해 성공을
판정하지 않는다.

단순히 처리 순서를 뒤집은 첫 시험은 `success=False`를 만들었지만 DMOV 콜백 재진입으로
동일 Status를 두 번 완료하려는 `InvalidState` 예외가 발생했다. 따라서
`kohzu_ophyd.SafeStopEpicsMotor`를 추가했다. 이 클래스는 활성 MoveStatus 완료 콜백을
먼저 분리하고 motor record STOP을 전송한 다음 요청한 결과로 콜백을 정확히 한 번
완료하며, STOP 처리와 DMOV 완료를 `RLock`으로 직렬화한다.

Ophyd fake device 단위시험에서 다음 네 경우를 확인했다.

- 정상 DMOV 완료: `success=True`
- `stop(success=False)`: `success=False`
- `stop(success=True)`: `success=True`
- STOP과 동시 DMOV 완료: 명시적 STOP 결과 유지, 중복 완료 예외 없음

새 시험 4개를 포함한 전체 Python 단위시험 23개가 통과했다.

실제 축에서도 `SafeStopEpicsMotor`를 검증했다. 먼저 `6.0 mm` 정상 이동이
`done=True`, `success=True`, `DMOV=1`, `MOVN=0`으로 완료됐다. 이어서 목표
`10.0 mm` 이동 중 `stop(success=False)`를 실행해 `6.000 -> 6.025 mm`에서 감속
정지했으며 Status는 `done=True`, `success=False`였다. 같은 조건의
`stop(success=True)` 시험은 `6.025 -> 6.050 mm`에서 감속 정지하고 Status가
`done=True`, `success=True`였다.

두 STOP 시험 모두 명령 시점에 `DMOV=0`, `MOVN=1`이었고 최종 `DMOV=1`, `MOVN=0`,
`MSTA=16386`, `LVIO=0`, `_able=Enable`이었다. Status 중복 완료 예외는 발생하지
않았다. 따라서 실제 STOP 동작, 호출자가 지정한 Status 결과, 빠른 DMOV 콜백의 경쟁
방지를 모두 확인했다.

## 최종 판정

시험 진행 중.
