# 고정점 운동 Python 모듈 역할

## 1. 전체 구조

고정점 운동 Python 코드는 책임에 따라 세 계층으로 나뉜다.

```text
tools/
  사용자 실행 명령과 입출력

kohzu_kinematics/
  장비와 독립적인 기구학·궤적 계산

kohzu_ophyd/
  계산된 궤적을 EPICS 장비에서 실행
```

전체 end-to-end 호출 관계는 다음과 같다.

```text
tools/fixed_point_run.py
│
├─ snapshot.py
│   └─ 현재 IOC 값 읽기
│
├─ fixed_point.py
│   └─ 고정점 기구 계산
│
├─ trajectory.py
│   └─ 중간 sample 생성
│
├─ quantization.py
│   └─ 실제 pulse 격자로 변환
│
├─ motor.py
│   └─ EPICS motor를 Ophyd 객체로 연결
│
├─ trajectory_backend.py
│   └─ 계산 sample과 다섯 motor 연결
│
└─ bluesky_plan.py
    └─ RunEngine에서 sample 순차 실행
```

간단히 말하면 `kohzu_kinematics`는 어디로 움직일지 계산하고, `kohzu_ophyd`는
그 계산값을 EPICS motor에 전달하며, `tools`는 사용자가 기능을 실행하는 명령줄
프로그램이다.

## 2. `kohzu_kinematics`

EPICS, IOC와 Ophyd에 의존하지 않는 계산 계층이다.

### `__init__.py`

패키지에서 외부에 제공하는 class와 함수를 한곳에 모은다. 호출자는 내부 파일 위치를
일일이 지정하지 않고 다음처럼 사용할 수 있다.

```python
from kohzu_kinematics import StagePose, calculate_snapshot_dry_run
```

### `fixed_point.py`

고정점 운동의 핵심 기구학을 계산한다.

- X/Y/Z/Pitch/Yaw 자세 표현
- 사용자 좌표계와 내부 오른손 좌표계 변환
- Pitch와 Yaw 회전행렬 계산
- 현재 자세에서 고정점의 실험실 위치 계산
- 목표 Pitch/Yaw에서 고정점을 유지하는 X/Y/Z 계산
- 이상적 모델의 고정점 잔차 계산
- 축 software limit 표현

즉, Pitch와 Yaw를 목표 각도로 바꿀 때 X/Y/Z를 어디로 보내야 같은 점이 실험실
좌표에서 유지되는지를 계산한다.

### `trajectory.py`

시작 자세부터 목표 자세까지의 전체 중간 궤적을 만든다.

- Pitch/Yaw를 구간별로 선형 보간
- 각 중간 각도에서 필요한 X/Y/Z 계산
- `N`개 구간에 대해 양 끝을 포함한 `N+1`개 sample 생성
- 각 sample의 고정점 잔차와 software limit 검사
- 최대 이동량과 sample 기반 속도·가속도 계산
- dry-run 보고서 생성

`fixed_point.py`가 한 자세의 계산을 담당한다면 이 파일은 그 계산을 이동 경로 전체에
적용한다.

### `quantization.py`

연속 실수로 계산된 각 sample을 motor record가 실제로 표현할 수 있는 가장 가까운
좌표로 변환한다. 축별 `MRES`, `OFF`, `DIR`을 사용한다.

```text
DIR=Pos: user = OFF + pulse × MRES
DIR=Neg: user = OFF - pulse × MRES
```

- 각 목표를 가장 가까운 정수 pulse 좌표로 변환
- 양자화된 좌표에서 고정점 잔차 재계산
- 양자화된 궤적의 속도, 가속도, 이동량과 limit 결과 재계산

Bluesky 실행에는 연속 계산값이 아니라 이 양자화된 좌표가 전달된다. `FOFF`와 `OFF`를
변경하지 않으며 지나간 궤적도 저장하거나 역재생하지 않는다.

### `snapshot.py`

현재 IOC 상태를 read-only로 읽어 궤적 계산 입력으로 구성한다.

- 1~5축의 현재 `RBV` 읽기
- `LLM/HLM`, `MRES/OFF/DIR` 읽기
- `DMOV/MOVN/HLS/LLS/LVIO` 상태 읽기
- PV 값, alarm과 timestamp 검사
- snapshot을 사용한 연속 궤적 계산
- 이어서 양자화된 실행 궤적 생성

결과에는 이상적인 `continuous_trajectory`와 실제 실행용 양자화 결과인 `trajectory`가
함께 들어간다. 이 모듈은 PV 쓰기 기능을 제공하지 않는다.

### `execution.py`

하드웨어 종류와 독립적인 궤적 실행 규칙을 정의한다.

- 실행 정책 `ExecutionPolicy`
- 시작 자세, software limit와 sample 간격 검사
- backend를 통한 sample 순차 실행
- 선택적인 실패 시 STOP 처리
- 최종 실행 결과 반환

실제 EPICS 명령을 직접 보내지 않고 backend interface를 사용한다. 기본 프로파일에서는
복잡한 검사를 사용하지 않으며 과거 안전 실험은 opt-in 코드로 보존한다.

### `approval.py`

dry-run 궤적을 식별하는 SHA-256 hash를 생성한다. 고정점, 시작·목표 자세, 모든 중간
sample, 실행 시간, 구간 수와 실행 문맥이 입력에 포함된다. 과거 안전 실험인
`--safety-checks`에서 검토한 궤적과 실행할 궤적이 같은지 확인할 때 사용하며 기본
실행에서는 승인을 요구하지 않는다.

## 3. `kohzu_ophyd`

EPICS motor record를 Ophyd 객체로 연결하고 Bluesky가 궤적을 실행할 수 있게 하는
장비 연동 계층이다.

### `__init__.py`

Ophyd 계층의 공개 class와 plan을 한곳에서 가져올 수 있게 한다.

```python
from kohzu_ophyd import (
    SafeStopEpicsMotor,
    OphydFiveAxisBackend,
    fixed_point_trajectory_plan,
)
```

### `motor.py`

Ophyd `EpicsMotor`를 확장한 `SafeStopEpicsMotor`를 정의한다.

- motor record의 `_able`과 `.LVIO` PV 연결
- 명시적 STOP과 `.DMOV` callback 사이의 경쟁 상태 처리
- 중복된 DMOV 완료 callback 방지
- 이동 status를 성공 또는 실패 상태로 일관되게 종료

실제 이동에서 Ophyd는 이 객체를 통해 motor record에 목표값을 쓰고 `.DMOV` 완료를
기다린다.

### `trajectory_backend.py`

기구학 궤적과 실제 Ophyd motor 다섯 개 사이의 adapter다.

```text
x     → KOHZU:m1
y     → KOHZU:m2
z     → KOHZU:m3
pitch → KOHZU:m4
yaw   → KOHZU:m5
```

- 다섯 축 `.RBV`로 현재 `StagePose` 구성
- 모든 축의 `_able=Enable` 확인
- 선택적인 안전 모드에서 Emergency와 limit 상태 확인
- 한 sample의 다축 이동 요청과 완료 대기
- 필요할 때 전체 축 STOP

`kohzu_kinematics`가 정의한 일반 실행 interface를 실제 Ophyd 장치로 구현한다.

### `bluesky_plan.py`

양자화된 궤적을 Bluesky generator plan으로 변환한다.

- sample을 순서대로 순회
- 직전 sample과 값이 달라진 축만 선택
- 모든 축이 동일한 양자화 sample은 생략
- `bluesky.plan_stubs.mv()`로 선택 축들을 함께 요청
- 각 sample 완료 후 다음 sample로 진행
- opt-in 안전 정책을 사용한 실패 경로에서 STOP 실행

생성된 plan은 Bluesky `RunEngine`이 실행한다.

## 4. `tools`

사용자가 터미널에서 직접 실행하는 진입점이다.

### `validate_stage_config.py`

스테이지 모델 catalog와 축 할당 파일의 형식을 검사한다. 모델 이름, 단위, `MRES`,
속도, 가속도, software limit, 축 번호, 방향과 HOME method를 확인하며 IOC에는 연결하지
않는다.

### `stage_config_dry_run.py`

모델 catalog와 축 할당을 읽고 IOC에 적용할 설정을 출력한다. PV를 읽거나 쓰지 않으며
각 축의 `MRES`, `DIR`, limit와 속도 등을 사람이 검토할 수 있게 보여준다.

### `stage_config_apply.py`

검토된 모델 설정을 실행 중인 IOC의 motor record에 적용한다.

1. 대상 축이 `_able=Disable`인지 확인
2. `DESC`, `EGU`, `DIR`, `MRES` 등 설정
3. `LLM/HLM`, 속도, 가속도와 HOME method 설정
4. 각 설정의 readback 검증
5. 성공한 할당 축을 `_able=Enable`로 전환

기본 명령은 계획만 출력하고 `--apply`를 추가해야 실제 PV를 쓴다. HOME, ORG,
controller 설정이나 실제 이동 명령은 보내지 않는다.

### `fixed_point_dry_run.py`

고정점 궤적 전용 read-only 명령이다.

1. IOC의 현재 1~5축 snapshot 읽기
2. 고정점과 목표 Pitch/Yaw 입력
3. 이상적인 연속 궤적 계산
4. `MRES/OFF/DIR` 양자화
5. 고정점 잔차와 software limit 보고

어떤 PV에도 값을 쓰지 않는다.

### `fixed_point_run.py`

현재 고정점 기능의 최종 사용자 실행 진입점이다.

`--execute`가 없으면 snapshot, 연속 궤적, 양자화 결과와 보고서만 생성하고 하드웨어에
쓰지 않는다. `--execute`가 있으면 다음 실행 계층도 구성한다.

1. 1~5축 `SafeStopEpicsMotor` 생성
2. `_able=Enable` 확인
3. `OphydFiveAxisBackend` 생성
4. `fixed_point_trajectory_plan` 생성
5. Bluesky `RunEngine`으로 실행
6. Ophyd가 각 sample의 EPICS 이동 완료 감시

따라서 이 파일이 계산, IOC snapshot, Ophyd 장치와 Bluesky plan을 하나의 end-to-end
동작으로 조립한다.

## 5. 실행 시 각 계층의 역할

```text
fixed_point_run.py
        |
        | snapshot과 입력을 전달
        v
kohzu_kinematics
        |
        | 양자화된 위치 sample들
        v
Bluesky RunEngine
        |
        | plan을 순서대로 실행
        v
Ophyd motor 객체
        |
        | EPICS PV에 이동 명령, 완료 감시
        v
EPICS IOC → ARIES/LYNX → 실제 스테이지
```

dry-run에서는 snapshot과 `kohzu_kinematics` 계산까지만 수행한다. 실제 Ophyd motor
객체와 Bluesky `RunEngine`은 `fixed_point_run.py --execute`일 때만 생성·실행된다.
