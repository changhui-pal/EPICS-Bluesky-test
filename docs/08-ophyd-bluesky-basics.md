# Ophyd와 Bluesky 기초

## 1. Ophyd가 하는 일

Ophyd는 Python 프로그램에서 하드웨어를 일관된 객체로 다루게 해 주는 라이브러리다.
EPICS를 대체하거나 모터를 직접 구동하는 프로그램이 아니다. 실제 통신과 안전 처리는
IOC가 담당하고, Ophyd는 IOC가 제공하는 여러 PV를 하나의 장치 객체로 묶는다.

예를 들어 EPICS motor record `KOHZU:m1`에는 목표 위치, 현재 위치, 이동 완료,
리미트, 정지 등 여러 PV가 있다. Ophyd의 `EpicsMotor`는 이 PV들을 묶어 다음과 같은
고수준 동작을 제공한다.

- 현재 위치와 상태 읽기
- 목표 위치 설정
- 이동 완료까지 기다리기
- 소프트 리미트 확인
- 이동 중 정지
- Bluesky가 이해하는 `read()`, `describe()`, `set()` 인터페이스 제공

관계를 단순화하면 다음과 같다.

```text
Bluesky plan
    ↓
Ophyd EpicsMotor
    ↓ Channel Access
EPICS motor record PV
    ↓ asyn motor driver
ARIES/LYNX controller
    ↓
KOHZU stage
```

Ophyd 객체는 단독 Python 코드에서도 사용할 수 있지만, 보통 Bluesky RunEngine과
함께 사용한다. Ophyd가 장치를 표현하고, Bluesky는 이동·측정 순서 실행과 데이터
문서 생성을 담당한다.

공식 문서:

- [Ophyd documentation](https://blueskyproject.io/ophyd/)
- [Ophyd와 EPICS의 관계](https://blueskyproject.io/ophyd/user_v1/explanations/relationship-to-epics.html)
- [EpicsMotor reference](https://blueskyproject.io/ophyd/builtin-devices.html)

## 2. 이번 프로젝트에서 사용할 API

첫 시험에서는 classic Ophyd의 `ophyd.EpicsMotor`를 사용한다. 공식 문서에 v2 API도
포함돼 있지만 아직 provisional로 표시된 부분이 있으므로, 이미 널리 사용되고 motor
record를 바로 지원하는 API를 먼저 사용한다.

IOC PV prefix와 Ophyd 객체의 대응은 다음과 같다.

| Controller 축 | 기능 | motor prefix | Ophyd 이름 |
|---:|---|---|---|
| 1 | 빔 방향 전후 X | `KOHZU:m1` | `x` |
| 2 | 좌우 Y | `KOHZU:m2` | `y` |
| 3 | 상하 Z | `KOHZU:m3` | `z` |
| 4 | Pitch | `KOHZU:m4` | `pitch` |
| 5 | Yaw | `KOHZU:m5` | `yaw` |

## 3. 설치

시스템 Python을 직접 변경하지 않고 프로젝트 전용 가상환경을 사용하는 것을
권장한다. 다음 명령은 저장소 최상위 디렉터리에서 실행한다.

```bash
python3 --version
python3 -m venv .venv-bluesky
source .venv-bluesky/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install ophyd bluesky pyepics ipython pytest
```

각 패키지의 역할은 다음과 같다.

- `ophyd`: EPICS 장치의 Python 객체화
- `bluesky`: RunEngine과 이동·스캔 plan
- `pyepics`: EPICS Channel Access 클라이언트
- `ipython`: 대화형 시험 환경
- `pytest`: 프로젝트의 Python 회귀시험 실행

공식 Ophyd 페이지는 PyPI의 `pip install ophyd`와 conda-forge의
`conda install -c conda-forge ophyd`를 안내한다. 이 프로젝트에서는 재현하기 쉬운
venv와 pip 절차를 우선 사용한다. 설치 여부는 다음과 같이 확인한다.

```bash
python3 -c "import ophyd, bluesky, epics; print(ophyd.__version__, bluesky.__version__)"
```

가상환경을 종료하려면 다음 명령을 사용한다.

```bash
deactivate
```

공식 설치 안내: [Ophyd installation](https://blueskyproject.io/ophyd/user_v2/tutorials/installation.html)

## 4. EPICS 연결 조건

Ophyd를 실행하기 전에 IOC가 실행 중이어야 한다. 같은 컴퓨터의 IOC만 찾도록 제한할
때는 Python을 시작하기 전에 다음 환경변수를 설정할 수 있다.

```bash
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
```

IOC가 다른 컴퓨터에 있으면 `127.0.0.1` 대신 IOC 호스트의 IP 주소를 사용한다.
브로드캐스트를 사용하는 기존 EPICS 네트워크에서는 시설의 Channel Access 설정을
따른다. 같은 이름의 PV를 제공하는 IOC가 두 개 이상 실행되면 잘못된 IOC에 연결될 수
있으므로, 하드웨어 IOC와 시험 IOC를 동시에 같은 `KOHZU:` prefix로 실행하지 않는다.

먼저 셸에서 PV를 확인한다.

```bash
caget KOHZU:m1.RBV
caget KOHZU:m1.DMOV
```

`caget`이 연결되지 않으면 Ophyd도 연결되지 않는다. 이 경우 Python 코드보다 IOC,
방화벽, `EPICS_CA_ADDR_LIST`를 먼저 확인한다.

## 5. Ophyd만 사용한 첫 연결

가상환경을 활성화한 뒤 IPython을 실행한다.

```bash
source .venv-bluesky/bin/activate
ipython
```

다음 코드는 객체를 만들지만 곧바로 축을 움직이지는 않는다.

```python
from ophyd import EpicsMotor

x = EpicsMotor("KOHZU:m1", name="x")
y = EpicsMotor("KOHZU:m2", name="y")
z = EpicsMotor("KOHZU:m3", name="z")
pitch = EpicsMotor("KOHZU:m4", name="pitch")
yaw = EpicsMotor("KOHZU:m5", name="yaw")

motors = [x, y, z, pitch, yaw]
for motor in motors:
    motor.wait_for_connection(timeout=5)
    print(motor.name, motor.connected, motor.position, motor.limits)
```

기본 상태 조회 예제:

```python
x.read()
x.describe()
x.position
x.limits
x.moving
x.motor_done_move.get()
```

`read()` 결과에는 값과 timestamp가 포함되고, `describe()`에는 데이터 형식과 단위
등의 메타데이터가 포함된다.

## 6. Ophyd 직접 이동

직접 이동은 Bluesky 없이 Ophyd 기능만 확인할 때 사용한다. 축이 IOC의 정상 절차로
Enable되어 있고, 물리 주변에 간섭이 없을 때만 실행한다.

```python
# 현재 위치에서 +0.1 mm 절대 위치로 이동하는 것이 아니라,
# 좌표 0.1 mm로 이동한다.
status = x.set(0.1)
status.wait(timeout=10)
print(x.position)
```

`set()` 인수는 절대 위치다. 현재 위치를 기준으로 상대 이동하려면 현재 값을 더한다.

```python
target = x.position + 0.1
status = x.set(target)
status.wait(timeout=10)
```

간단한 동기식 방법도 있다.

```python
x.move(0.1, wait=True, timeout=10)
```

이동 중 정지는 다음과 같다.

```python
x.stop(success=False)
```

### KOHZU STOP과 MoveStatus 경쟁 방지

Ophyd 1.11.2의 기본 `EpicsMotor.stop()`은 motor record의 `.STOP`을 먼저 쓴 뒤
진행 중인 `MoveStatus`를 호출자가 지정한 `success` 값으로 완료한다. KOHZU IOC가
STOP 직후 `DMOV=1`을 매우 빠르게 게시하면 DMOV 콜백이 먼저 상태를
`success=True`로 완료할 수 있다. 실제 정지와 `DMOV/MOVN`은 정상이지만
`stop(success=False)`의 의미가 보존되지 않는 경쟁 조건이다.

이 프로젝트는 STOP 처리와 DMOV 상태 완료만 직렬화하는 클래스를 제공한다.

```python
from kohzu_ophyd import SafeStopEpicsMotor

x = SafeStopEpicsMotor("KOHZU:m1", name="x")
x.wait_for_connection(timeout=5)
```

사용법은 `EpicsMotor`와 같다.

```python
status = x.set(1.0)
x.stop(success=False)

print(status.done)     # True
print(status.success)  # False
```

이 클래스는 실제 `.STOP` 쓰기나 `DMOV`, `MOVN`, 위치 PV 갱신을 지연하지 않는다.
정상 이동 완료에도 지연을 추가하지 않고, 같은 `MoveStatus`를 STOP 경로와 DMOV
콜백이 동시에 완료하지 못하게 한다. `settle_time`은 성공 판정이 끝난 뒤 완료 통지를
늦추는 속성이므로 이 경쟁 조건의 해결책이 아니다.

구현은 Ophyd 1.11.2의 내부 subscription 자료구조를 사용하므로 Ophyd 버전을 변경할
때 `tests/test_kohzu_ophyd_motor.py`를 반드시 다시 실행한다.

Ophyd는 motor record의 소프트 리미트를 읽어 범위를 벗어난 목표를 거부할 수 있지만,
이 기능을 물리 안전장치의 대체물로 사용하면 안 된다.

## 7. Bluesky 기초

Bluesky의 plan은 실행할 동작을 표현하는 Python generator다. RunEngine(`RE`)이 plan을
받아 Ophyd 장치를 구동하고 실행 상태 및 데이터를 관리한다.

```python
from bluesky import RunEngine
from bluesky import plan_stubs as bps
from bluesky import plans as bp

RE = RunEngine({})
```

### 절대 이동

```python
RE(bps.mv(x, 0.1))
```

### 상대 이동

```python
RE(bps.mvr(x, 0.1))
RE(bps.mvr(x, -0.1))
```

### 두 축 동시 이동

하나의 `mv`에 여러 축과 목표값을 넣으면 Bluesky가 두 이동을 함께 시작하고 모두
완료될 때까지 기다린다.

```python
RE(bps.mv(x, 0.1, y, -0.1))
```

### 검출기 없는 모터 위치 스캔

첫 연동에서는 검출기 없이 위치 이동 순서만 확인할 수 있다.

```python
positions = [-0.1, 0.0, 0.1, 0.0]
RE(bp.list_scan([], x, positions))
```

검출기를 연결한 뒤에는 빈 리스트 대신 Ophyd detector 객체를 넣는다.

```python
# detector 객체를 정의한 이후의 형태
RE(bp.scan([detector], x, -0.1, 0.1, 5))
```

RunEngine은 plan 실행 중 장치의 `set()` 완료를 기다리고 실행 문서를 발생시킨다.
[RunEngine API](https://blueskyproject.io/bluesky/main/generated/bluesky.run_engine.RunEngine.html)
에서 `abort`, `halt`, suspender 등의 실행 제어 기능을 확인할 수 있다.

## 8. 현재 장비에서의 최초 시험 순서

처음부터 다축 스캔을 실행하지 말고 다음 순서로 진행한다.

1. IOC와 controller가 통신 중인지 확인한다.
2. 모든 축을 Disable 상태로 두고 Ophyd 연결과 읽기만 확인한다.
3. 시험할 한 축만 정상 commissioning 절차로 Enable한다.
4. 현재 위치와 소프트 리미트를 읽는다.
5. 이동 범위 중앙에서 작은 절대 이동을 실행한다.
6. 원래 위치로 복귀한다.
7. Bluesky `mv`, `mvr`을 각각 시험한다.
8. 작은 `list_scan`을 실행한다.
9. 실행 중 정지와 예외 처리를 시험한다.
10. 한 축 검증 후 다음 축으로 진행한다.

권장 최초 이동량은 다음과 같다.

| 축 | 최초 상대 이동량 |
|---:|---:|
| 1 | ±0.1 mm |
| 2 | ±0.1 mm |
| 3 | ±0.05 mm |
| 4 | ±0.05° |
| 5 | ±1° |

표의 값은 현재 위치가 소프트 리미트에서 충분히 떨어진 경우의 상대 이동량이다.
5번 축의 현재 운전 원점은 Method 8 기준 `+179.000°`에서 Method 10으로 설정한
X축 평행 작업 원점이며, 소프트 범위는 `-173.786° ~ +173.134°`다. 작업 원점 상실 후
Method 8 복구 원점 `0°`에서는 곧바로 왕복 시험하지 말고, 복구 절차를 끝내 Method 10
작업 원점을 다시 확립한 뒤 그 주변에서 작은 왕복 시험을 수행한다.

3번 Z축은 HOME 및 limit 센서가 고장 난 상태다. 전원 재인가나 좌표 신뢰성 상실 후에는
사람이 위치를 확인하고 Method 10으로 원점을 다시 확립하기 전까지 Bluesky 자동 이동과
스캔을 실행하지 않는다.

## 9. Enable과 원점은 Ophyd의 책임이 아니다

`EpicsMotor`를 만들었다고 축이 자동 Enable되거나 HOME되는 것은 아니다. 현재 개발
기간에는 commissioning PV와 `_able/SDIS` 잠금을 사용하지만 이들은 Codex 시험용이며
개발 완료 후 DB에서 주석 처리한다. Ophyd 시험은 다음 조건을 확인한 뒤 시작한다.

- 올바른 모델과 방향이 적용됨
- 신뢰할 수 있는 원점이 확립됨
- 소프트 리미트가 적용됨
- 축이 정지 상태임
- 사용자가 의도한 축만 Enable됨

개발 기간에도 Python에서 내부 `_able` PV를 직접 쓰지 않고 commissioning 요청 PV를
사용한다. 최종 운전에서는 이 잠금 계층을 로드하지 않으며 표준 motor record를 직접
사용한다. 자동 HOME은 별도의 안전 정책을 정한 뒤 구현한다.

## 10. 자주 생기는 문제

### `TimeoutError` 또는 연결 실패

- IOC가 실행 중인지 확인한다.
- `caget`으로 같은 PV가 보이는지 확인한다.
- PV prefix가 `KOHZU:m1`처럼 정확한지 확인한다.
- `EPICS_CA_ADDR_LIST`와 방화벽을 확인한다.
- 동일 prefix의 IOC가 여러 개 실행 중인지 확인한다.

### 이동 명령이 바로 완료되지만 움직이지 않음

- 축이 Disable 상태인지 확인한다.
- motor record의 `DMOV`, `MOVN`, `LVIO`, `MSTA`를 확인한다.
- 목표가 현재 위치와 같은지 확인한다.
- 소프트 또는 하드 리미트가 활성화됐는지 확인한다.

### 소프트 리미트 예외

- `motor.limits`와 `motor.position`을 확인한다.
- 리미트를 넓혀 우회하지 말고 좌표와 원점이 올바른지 먼저 확인한다.
- 5번 축은 Method 10 작업 원점 기준 운전 범위 `-173.786° ~ +173.134°`를 사용한다.

### plan 실행 중 문제 발생

- 우선 해당 motor의 실제 이동 상태를 관찰한다.
- RunEngine의 pause/abort와 motor stop의 차이를 이해한 뒤 비상 절차를 정한다.
- 즉시 위험한 상황에서는 소프트웨어 plan 정리보다 controller의 검증된 정지 수단을
  우선한다.

## 11. 다음 구현 범위

기초 연결이 확인되면 다음 파일을 별도로 추가하는 것이 좋다.

- 1~5축 `EpicsMotor` 객체를 정의하는 startup 모듈
- 연결 및 읽기 전용 smoke test
- 축별 작은 왕복 이동 plan
- 이동 후 원위치 복귀를 보장하는 plan
- 3번 축 자동 사용을 막는 안전 조건
- RunEngine 결과와 예외를 기록하는 시험 로그

첫 자동 시험에서는 GUI나 detector를 포함하지 않고 IOC, Ophyd, Bluesky의 모터 이동
경로만 검증한다.
