# 5축 고정점 운동 설계와 시험 계획

## 1. 목적과 현재 범위

이 문서는 아래에서부터 `X -> Y -> Z -> Pitch -> Yaw` 순서로 적층된 시험 스테이지에서
Pitch와 Yaw 자세를 바꾸면서, Yaw 테이블에 고정된 임의의 한 점을 실험실 좌표에서
움직이지 않게 유지하는 소프트웨어 구조를 정의한다. CRL 케이스 앞쪽 구멍의 한 점을
고정하는 것이 최초 사용 사례지만, 계산에는 케이스 형상을 직접 포함하지 않고 사용자가
지정하는 임의의 고정점 좌표를 사용한다.

현재 단계의 목표는 이상적인 강체 기구 모델, 좌표 변환, 안전 검사와 단계별 시험 방법을
확정하는 것이다. 실제 장비의 축 비직교, 조립 편심, 회전축 오차와 케이스 장착 오차는
우선 0으로 둔다. 이를 구분해 측정할 도구와 카메라가 현재 없으므로 실제 오차 보정은
측정 수단이 마련될 때까지 보류하며, 관찰만으로 보정값을 추정하지 않는다.

기존 작업 중 다음 항목은 이미 별도로 검증됐다.

- 1~5축 모델, 분해능, 속도 및 초기 소프트 리미트
- 모든 축의 실제 EPICS 양·음 방향
- 축 1, 2, 4의 센서 기반 HOME과 축 3의 Method 10 원점
- 축 5의 양쪽 하드 리미트, Method 8 CCW 원점과 Method 10 작업 원점
- 단축 motor record, Ophyd, Bluesky 이동과 STOP 처리

근거와 시험 기록은 `docs/05-test-stage-specifications.md`,
`docs/07-real-controller-commissioning.md`, `docs/08-ophyd-bluesky-basics.md`와
`docs/09-ophyd-bluesky-integration-log.md`를 따른다.

## 2. 이상적 기구 가정

최초 구현은 다음 조건을 가정한다.

1. X, Y, Z 병진축은 서로 직교한다.
2. 병진축은 회전 스테이지 아래에 있으므로 그 이동 방향은 실험실 좌표에 고정된다.
3. 모든 병진축 원점과 회전축 중심선은 수평 편심 없이 같은 수직 중심선에 놓인다.
4. Pitch 회전축은 좌우 방향이고 Y축과 평행하다.
5. Pitch가 0일 때 Yaw 회전축은 수직이고 Z축 중심선과 일치한다.
6. Pitch와 Yaw 회전축의 연장선은 한 점에서 직교한다.
7. Yaw 테이블 표면 중심과 실제 Yaw 회전축은 일치한다.
8. 스테이지 사이에 별도 어댑터 플레이트가 없다.
9. 구조물은 변형 없는 강체이고 백래시와 회전 중심 오차는 0이다.

공식 모델 도면의 명목 치수는 다음과 같다.

- SA05A-R2B01 바닥면에서 Pitch 회전 중심: `86 mm`
- SA05A-R2B01 바닥면에서 상부 장착면: `18 mm`
- RA04A-W01 바닥면에서 Yaw 테이블 표면: `30 mm`

따라서 Pitch 회전 중심은 Yaw 테이블 표면 중심보다 위쪽에 있다.

```text
86 - (18 + 30) = 38 mm
```

공식 도면은 `documents/stage-specifications/SA05A-R2B01_family.pdf`와
`documents/stage-specifications/RA04A-W01.pdf`에 보존한다.

## 3. 실제 축 방향

사용자가 실제 이동을 관찰해 확인한 EPICS 방향은 다음과 같다.

| 축 | 양의 방향 | 음의 방향 |
|---|---|---|
| X | 앞쪽 | 뒤쪽 |
| Y | 오른쪽 | 왼쪽 |
| Z | 위쪽 | 아래쪽 |
| Pitch | 앞쪽 `+X` 상승 | 앞쪽 `+X` 하강 |
| Yaw | 위에서 볼 때 시계방향 | 위에서 볼 때 반시계방향 |

3축 motor record의 `DIR=Neg`는 controller pulse 방향을 위 표의 EPICS Z 방향으로
변환하는 구현 설정이다. 기구 계산에서는 EPICS `+Z`를 항상 실제 위쪽으로 사용한다.

위에서 본 물리 방향은 다음과 같다.

```text
                         앞쪽
                          +X
                           ^
                     -Yaw / \ +Yaw
                         /   \
          왼쪽 -Y  <===========>  +Y 오른쪽
                    Pitch 회전축
                           |
                           v
                          -X
                         뒤쪽

                    +Z: 화면 밖 위쪽
                    -Z: 화면 안 아래쪽
```

`+X=앞`, `+Y=오른쪽`, `+Z=위`를 그대로 묶으면 왼손 좌표가 된다. 표준 오른손
회전행렬과 라이브러리를 안전하게 사용하기 위해 내부 계산 좌표는 Y만 반전한다.

```text
Xc =  Xstage
Yc = -Ystage
Zc =  Zstage
```

내부 계산 좌표에서 `+Xc=앞`, `+Yc=왼쪽`, `+Zc=위`이고 `Xc x Yc = Zc`가 된다.

## 4. 좌표계

### 4.1 계산 좌표계 C

내부 계산 좌표계 `C`의 원점은 Pitch와 Yaw 회전축 연장선의 교차점으로 둔다. 모든
축이 0일 때 축 방향은 `Xc`, `Yc`, `Zc`와 일치한다. 두 회전이 같은 원점을 사용하므로
각 회전축마다 별도 평행이동을 삽입할 필요가 없다.

### 4.2 사용자 좌표계 S

사용자가 고정점을 입력하는 좌표계 `S`의 원점은 모든 축이 0일 때의 Yaw 테이블 표면
중심으로 둔다. 축 방향은 장비에서 직관적으로 사용하는 앞, 오른쪽, 위쪽이다.

계산 좌표계에서 Yaw 표면 중심은 다음 위치다.

```text
S_origin_in_C = (0, 0, -38 mm)
```

사용자가 `S`에서 고정점 `q=(qx,qy,qz)`를 입력하면 내부 오른손 계산 좌표의 고정점
벡터 `r`은 다음과 같다.

```text
r = (qx, -qy, qz - 38)
```

케이스 장착 위치와 방향은 필수 입력이 아니다. 케이스의 특정 점을 이미 `S` 좌표로
제공하면 장착 상태가 그 좌표에 포함돼 있다. 케이스 도면 좌표를 자동 변환하거나 충돌
검사를 구현할 때만 케이스 pose가 추가로 필요하다.

## 5. 이상적 순기구학

각도는 EPICS 명령과 같이 degree로 입력하고 행렬 계산 직전에 radian으로 바꾼다.
열벡터와 active rotation을 사용한다.

실제 `+Pitch`는 앞쪽 `+X`를 위로 올린다. 내부 오른손 좌표의 표준 `Ry(+p)`는 앞쪽을
아래로 내리므로 실제 Pitch 행렬은 `Ry(-p)`다.

```text
Rp(p) = Ry(-p)
```

실제 `+Yaw`는 위에서 볼 때 시계방향이다. 내부 오른손 좌표에서 표준 `Rz(+y)`는
반시계방향이므로 실제 Yaw 행렬은 `Rz(-y)`다.

```text
Rw(y) = Rz(-y)
```

Pitch 스테이지가 아래에서 Yaw 스테이지 전체를 운반하므로 한 점에는 Yaw 회전을 먼저,
Pitch 회전을 나중에 적용한다.

```text
R(p, y) = Rp(p) * Rw(y) = Ry(-p) * Rz(-y)
```

현재 병진축의 내부 계산 좌표를 `t=(Xc,Yc,Zc)`라 하면 고정점의 실험실 위치는 다음과
같다.

```text
world_point = t + R(p, y) * r
```

EPICS 병진 목표로 반환할 때는 Y를 다시 반전한다.

```text
Xstage =  Xc
Ystage = -Yc
Zstage =  Zc
```

## 6. 고정점 보정 계산

현재 자세를 `t0, p0, y0`, 목표 회전 자세를 `p1, y1`이라 한다. 현재 실험실 위치에서
고정할 목표점은 다음과 같다.

```text
fixed_world = t0 + R(p0, y0) * r
```

목표 회전 후에도 같은 점을 유지하기 위한 병진 목표는 다음과 같다.

```text
t1 = fixed_world - R(p1, y1) * r
```

모든 축이 0인 기준 자세에서 시작하면 식은 다음처럼 단순해진다.

```text
t1 = r - R(p1, y1) * r
```

이 식은 최종 자세의 고정만 보장한다. 시작점과 끝점 사이에서도 고정점을 계속 유지하려면
Pitch와 Yaw의 보간 각도마다 같은 식으로 X, Y, Z 목표를 계산해 동기화된 궤적으로
실행해야 한다. 단순히 다섯 축을 동시에 시작하는 것만으로는 가속도와 이동 시간이 달라
중간 경로의 고정점이 유지되지 않는다.

## 7. 최초 소프트웨어 인터페이스

최초 구현은 실제 이동보다 계산과 검토 인터페이스를 먼저 제공한다.

```python
result = calculate_fixed_point_move(
    fixed_point_surface_mm=(qx, qy, qz),
    current_xyz_mm=(x0, y0, z0),
    current_pitch_deg=p0,
    current_yaw_deg=y0,
    target_pitch_deg=p1,
    target_yaw_deg=y1,
)
```

반환값에는 최소한 다음 항목이 있어야 한다.

- 계산된 X, Y, Z, Pitch, Yaw 절대 목표
- 각 축의 현재값, 목표값과 이동량
- 계산 전후 고정점의 실험실 좌표와 residual
- 각 목표의 motor record 소프트 리미트 통과 여부
- 입력과 출력에 사용한 좌표계 및 단위
- 적용된 명목 기구 파라미터와 보정 파라미터

실행 인터페이스는 기본적으로 `dry_run=True`이고, 별도의 실제 장비 승인 경로를 구현하기
전에는 `dry_run=False`를 제공하지 않는다.

## 8. 안전 조건

계산 결과가 유한하다는 이유만으로 실제 이동을 허용하지 않는다. 실행 전 최소 조건은
다음과 같다.

1. 다섯 축 모두 연결되고 fresh readback을 제공한다.
2. 모든 축이 정지 상태이고 EMG와 hardware limit가 비활성이다.
3. 각 축의 원점과 현재 좌표가 유효하다고 작업자가 확인한다.
4. 계산된 모든 절대 목표가 해당 motor record LLM/HLM 내부다.
5. 궤적의 모든 중간점도 LLM/HLM 내부다.
6. Z축은 센서 고장 상태이므로 Method 10 원점의 유효성을 별도로 확인한다.
7. 계산 모듈은 `_able`, HOME 또는 controller SYS를 직접 변경하지 않는다.
8. 실행 중 한 축이라도 실패하거나 연결이 끊기면 전체 축에 STOP을 요청한다.
9. STOP 후 성공으로 잘못 완료되지 않도록 `SafeStopEpicsMotor` 경로를 사용한다.
10. 충돌 모델이 없는 최초 단계에서는 작은 각도와 낮은 속도만 사용하고 작업자가 계속
    관찰한다.

축 목표뿐 아니라 중간 궤적의 충돌 가능성은 별도 문제다. 초기 소프트웨어는 구조물 형상을
모르므로 `collision_checked=false`를 명시하고 실제 CRL과 취약 부품을 장착한 자동 운전을
허용하지 않는다.

## 9. 시험 진행 순서

### 단계 A: 수학 단위시험

하드웨어와 EPICS 없이 순수 계산 함수를 검증한다.

1. `p=y=0`이면 병진 보정이 0이다.
2. Yaw 회전축 위의 점은 Yaw만 바꿀 때 병진 보정이 0이다.
3. Yaw 축에서 벗어난 점은 Yaw 변경 시 X/Y 보정이 발생한다.
4. Yaw 표면 중심 `(0,0,0)`도 Pitch 변경 시 38 mm lever arm에 따른 X/Z 보정이
   발생한다.
5. `+Pitch`에서 앞쪽 점의 계산 Z가 증가하는 부호를 확인한다.
6. `+Yaw`에서 위에서 본 점이 시계방향으로 회전하는 부호를 확인한다.
7. 임의의 자세에서 계산 후 `world_point` residual이 `1e-9 mm` 이하인지 확인한다.
8. 자세를 갔다가 되돌리면 원래 병진 위치로 돌아온다.
9. NaN, infinity, 잘못된 단위와 범위 밖 입력을 거부한다.

### 단계 B: 궤적 및 소프트 리미트 시험

회전 구간을 작은 step으로 보간하고 각 sample에서 X/Y/Z를 계산한다.

1. 모든 sample에서 고정점 residual을 확인한다.
2. 목표점뿐 아니라 중간점의 축 소프트 리미트를 검사한다.
3. 최대 이동량, 속도와 가속도 요구량을 계산한다.
4. 같은 최종 자세라도 여러 보간 경로가 다른 중간 이동을 만들 수 있음을 기록한다.
5. 기본 경로를 joint-space 선형 보간으로 시작하되 경로 선택을 API에 명시한다.

### 단계 C: mock IOC와 Bluesky dry-run

실제 controller와 다른 `MOCK:` prefix만 사용한다.

1. 다섯 motor의 현재 상태 snapshot을 읽는다.
2. 계산 결과와 limit 판정을 출력하되 move PV에는 쓰지 않는다.
3. stale readback, limit, moving, disconnect와 EMG 조건에서 전체 거부를 확인한다.
4. 승인되지 않은 raw `_able`과 controller write가 발생하지 않는지 mock 명령 로그로
   확인한다.
5. 이후 fake motor에서만 분할 궤적의 정상 완료와 중간 실패 시 전체 STOP을 검증한다.

### 단계 D: 실제 장비 단축 부호 재확인

기존 시운전 결과를 사용하되 다축 시험 직전에 작은 왕복 이동으로 다시 확인한다.

- X: `+`가 앞
- Y: `+`가 오른쪽
- Z: `+`가 위
- Pitch: `+`에서 앞쪽 상승
- Yaw: `+`가 위에서 시계방향

각 축은 원래 위치로 복귀하고 Disable한다. 이 단계에서는 고정점 다축 보정을 실행하지
않는다.

### 단계 E: 실제 장비의 작은 고정점 시험

실제 CRL 대신 가벼운 십자 표적이나 바늘을 사용하고, 광학 테이블에 고정한 외부 카메라
또는 측정기를 기준으로 삼는다. 스테이지에 같이 움직이는 기준만으로는 고정 여부를
판정할 수 없다.

권장 순서는 다음과 같다.

1. 고정점 `(20,0,0) mm`, Yaw `+/-0.5 deg`
2. 같은 고정점, Yaw `+/-1 deg`
3. 고정점 `(0,0,0) mm`, Pitch `+/-0.2 deg`
4. 같은 고정점, Pitch `+/-0.5 deg`
5. 고정점 `(20,10,10) mm`, 작은 Pitch/Yaw 복합 이동
6. 각 시험 후 모든 축을 시작 자세로 복귀하고 Disable

처음에는 한 목표 자세의 endpoint 정확도를 확인한다. endpoint가 맞은 뒤에만 작은
sample 간격의 연속 궤적을 시험한다. 한 대의 카메라는 화면 평면의 두 성분만 관찰하므로
3차원 검증에는 직교한 두 카메라, 다이얼 게이지 또는 레이저 변위 센서를 사용한다.

## 10. 향후 보정 모델

이상적 모델을 변경하지 않고 다음 보정값을 별도 구조로 추가한다.

```text
pitch_center_z_correction
pitch_axis_offset_x
pitch_axis_offset_z
yaw_axis_offset_x
yaw_axis_offset_y
x_axis_scale_and_squareness
y_axis_scale_and_squareness
z_axis_scale_and_squareness
pitch_zero_offset
yaw_zero_offset
fixed_point_measurement_offset
```

보정값의 기본값은 모두 0이다. 보정은 raw motor pulse나 motor record DIR을 임의로
바꾸지 않고 기구 변환 계층에서만 적용한다. 각 값에는 측정 날짜, 방법, 단위, 불확도와
적용 여부를 함께 기록한다.

## 11. 단계 A 구현 결과

2026-08-11에 실제 모터 이동이 없는 순수 Python 기구 계산 모듈과 단위시험을 추가했다.

- `kohzu_kinematics/fixed_point.py`: 불변 geometry, pose, vector 및 limit 자료형
- `surface_point_to_calculation()`: Yaw 표면 사용자 좌표를 내부 오른손 좌표로 변환
- `rotation_matrix()`: 검증된 실제 부호의 `Ry(-Pitch) * Rz(-Yaw)` 구현
- `world_fixed_point()`: 이상적 모델의 순기구학
- `calculate_fixed_point_move()`: 현재 pose에서 목표 Pitch/Yaw의 endpoint 병진 보정,
  residual과 선택적 소프트 리미트 판정
- `tests/test_fixed_point_kinematics.py`: 단계 A의 부호, 38 mm lever arm, 임의 자세,
  왕복, invalid input 및 limit 시험 15개

새 모듈은 EPICS와 Ophyd를 import하지 않으며 Enable, HOME, STOP 또는 move PV에 접근하는
코드가 없다. 새 시험 15개와 기존 시험을 합친 Python 단위시험 38개가 모두 통과했다.
Ophyd 시험이 Channel Access context를 만들 수 있도록 전체 시험은 프로젝트의
`kohzu-bluesky` 환경에서 실행했다.

```bash
python3 -m unittest -v tests/test_fixed_point_kinematics.py
/home/changhui1788/.conda/envs/kohzu-bluesky/bin/python \
    -m unittest discover -s tests -p 'test_*.py' -v
```

## 12. 단계 B 구현 결과

2026-08-11에 실제 이동 없는 궤적 sampling과 dry-run 보고를 구현했다.

- `kohzu_kinematics/trajectory.py`: joint-space 선형 Pitch/Yaw sampling
- 각 sample의 고정점 보정 X/Y/Z 및 residual 계산
- 경로 전체의 public EPICS LLM/HLM 판정과 최초 실패 sample/축 검출
- sample 간 유한차분 속도·가속도와 축별 최대 절대값 계산
- 시작 자세 대비 축별 최대 excursion 계산
- `format_trajectory_report()`: hardware write 없음과 충돌 미검사를 명시하는 텍스트
  dry-run 보고서
- `tests/test_fixed_point_trajectory.py`: endpoint, 보간, residual, limit, 속도·가속도,
  보고서와 invalid input 시험 14개

`intervals=N`은 양 끝을 포함한 `N+1`개 sample을 만든다. 속도와 가속도는 sample
사이의 유한차분 진단값이며 controller에 보낼 가감속 profile이 아니다. 첫 sample 이전과
마지막 sample 이후의 속도 불연속은 계산하지 않으므로 보고서에도 이 제한을 표시한다.

고정점 `(20,0,0) mm`, Pitch `0 -> 0.5 deg`, Yaw `0 -> 1 deg`, 5초/10구간 예제는
다음 최종 보정 목표를 계산했다.

```text
X=-0.327801 mm
Y=-0.349048 mm
Z=-0.175951 mm
Pitch=+0.500000 deg
Yaw=+1.000000 deg
maximum fixed-point residual=0 mm (reported precision)
```

이 예제는 현재 정식 X/Y/Z/Pitch limit와 작업 Yaw 원점 기준 runtime limit를 입력했을
때 모든 sample에서 통과했다. 이는 수학 dry-run 결과이며 충돌 안전이나 실제 실행
가능성을 승인하지 않는다.

새 기구 시험 29개와 기존 시험을 합친 Python 단위시험 52개가 모두 통과했다.

## 13. 단계 C 구현 결과

2026-08-12에 mock IOC read-only snapshot과 dry-run 연결을 구현했다.

- `kohzu_kinematics/snapshot.py`: 주입 가능한 numeric PV reader와 5축 snapshot
- 축별 `RBV`, `DMOV`, `MOVN`, `HLS`, `LLS`, `LVIO`, `LLM`, `HLM` 고정 allowlist
- controller `Recovery:EmergencyActive` read
- alarm, missing PV, 잘못된 binary 값과 stale observation 거부
- EMG, moving/not-done, hardware limit와 LVIO에서 dry-run 전체 거부
- 안전 snapshot의 현재 pose와 LLM/HLM을 단계 B 궤적 계산에 전달
- `tools/fixed_point_dry_run.py`: read-only CLI

Disable 상태의 passive motor record는 driver 값이 읽히더라도 record timestamp가
`<undefined>`일 수 있다. server timestamp가 있으면 그 값을 사용하고, 없으면 synchronous
CA get 응답 완료 시각을 observation freshness로 사용한다. 보고서 앞부분에는
`server_timestamps_complete=true/false`를 표시해 두 경우를 구분한다. 이는 HOME 또는
record process를 유발하지 않으면서 현재 IOC 구조에서 가능한 freshness 수준이며, 실제
다축 실행 승인에는 더 강한 driver-level snapshot 또는 timestamp PV가 필요하다.

`Recovery:EmergencyActive`는 event-driven `I/O Intr` PV라 값이 계속 Clear이면 IOC 시작
timestamp를 유지할 수 있다. 따라서 이 PV는 연결, alarm과 `Clear(0)` 값은 검사하지만
timestamp freshness 계산에서는 제외한다. 축의 동적 상태 PV freshness 검사는 유지한다.

전용 `FIXED:` mock IOC는 5개 모델 record를 모두 Disable로 로드하고 loopback
simulator만 사용한다. 고정점 `(2,1,0) mm`, Pitch `0.2 deg`, Yaw `0.5 deg`, 5초/10구간
dry-run에서 전체 sample의 residual과 soft limit가 통과했다. mock ARIES 로그에서
polling read 외 다음 controller write는 모두 0건이었다.

```text
WSY ORG APS RPS FRP WTB STP WRP REM
```

통합시험은 `tests/run_fixed_point_dry_run_integration.sh`로 실행한다. 기존 실제 축 5
IOC는 사용자의 명시적 승인 후 Disable/정지 상태를 확인하고 종료했으며, 시험 후 자동
재시작하지 않았다.

## 14. 단계 D 실행 guard 구현 결과

2026-08-12에 실제 EPICS 쓰기 adapter와 분리된 궤적 실행 코어를 추가했다.

- `kohzu_kinematics/execution.py`: backend protocol, 실행 policy와 stop-on-failure
- 실행 직전 live 시작 pose와 dry-run 시작 pose 일치 검사
- 모든 sample의 소프트 리미트 통과 여부와 독립적인 sample 최대 이동량 검사
- 충돌 미검사 궤적은 명시적 policy 승인 없이는 실행 거부
- 매 sample 직전 EMG·이동·하드 리미트·LVIO·disconnect 재검사를 backend 계약으로 요구
- 각 sample 완료 후 endpoint 허용오차 확인
- timeout, 상태 변경, endpoint 오차 및 사용자 interrupt를 포함한 모든 실행 중 실패에서
  `stop_all()` 호출
- 원래 실패와 STOP 실패가 동시에 발생하면 두 오류를 함께 보고

현재 모듈에는 실제 Channel Access write backend나 실행 CLI가 없다. 따라서 이 단계의
코드는 실제 장비를 움직일 수 없고, 향후 backend가 구현되더라도 충돌 미검사에 대한
명시적 승인이 필요하다. mock backend 시험은 정상 완료, 시작 pose 변경, limit 미평가,
과대 sample, live safety 변화, timeout, endpoint 오차와 STOP 실패를 검증한다.

## 15. 단계 E Ophyd backend 구현 결과

2026-08-12에 단계 D의 `TrajectoryBackend`를 5개 `SafeStopEpicsMotor`에 연결하는
`OphydFiveAxisBackend`를 추가했다.

- X/Y/Z/Pitch/Yaw의 `RBV`를 `StagePose`로 읽음
- `EmergencyActive`, `DMOV`, `MOVN`, `HLS`, `LLS`, `LVIO`를 sample 직전에 검사
- 5축 `set()`을 모두 발행한 뒤 복합 Ophyd status를 timeout과 함께 기다림
- 완료 후 5축 `RBV`를 반환해 실행 guard가 endpoint 허용오차를 확인
- 실패 시 한 축 STOP 오류가 있어도 나머지 축의 STOP을 계속 시도
- `SafeStopEpicsMotor`에 read-only `.LVIO` component 추가

fake Ophyd motor 통합시험은 안전 상태 판정, EMG/하드 리미트 거부, 5축 set 발행,
readback, 전체 STOP과 정확한 역할 구성을 확인한다. 추가로 단계 B 궤적부터 단계 D
실행 guard, Ophyd backend와 5개 fake motor까지 연결해 10개 구간의 총 50개 setpoint와
최종 pose가 일치함을 검증했다.

이 backend는 생성만으로 Enable, HOME 또는 이동을 실행하지 않는다. 실제 motor 객체를
생성하는 운전 CLI/Bluesky plan은 아직 없으므로 실제 IOC에 대한 쓰기 경로도 아직
노출되지 않았다.

## 16. 단계 F Bluesky plan 구현 결과

2026-08-12에 `fixed_point_trajectory_plan()`을 추가해 Ophyd backend를 Bluesky
RunEngine의 status와 abort 처리에 연결했다.

- 실행 전 단계 D의 궤적·sample 간격·충돌검사 승인 및 시작 pose 검사를 재사용
- sample마다 live 안전 상태를 확인한 뒤 5축을 하나의 `bps.mv()` group으로 발행
- Python blocking wait가 아니라 RunEngine이 Ophyd status와 timeout을 관리
- sample 완료 후 실제 5축 RBV를 endpoint 허용오차와 비교
- `finalize_wrapper`로 이동 시작 후 예외·abort·generator close에서 5축 STOP
- 정상 완료 후에도 RunEngine 자체 cleanup이 사용한 movable에 STOP을 호출할 수 있음
- 예외 때 plan finalizer와 RunEngine cleanup의 STOP이 중복될 수 있으므로 정상 감속 STOP은
  반복 호출해도 안전해야 함

fake RunEngine 시험은 정상 2구간의 10개 setpoint, 두 번째 구간 직전 주입한 안전 실패,
첫 구간 status 대기 중 외부 `RE.abort()`를 검증했다. 예외와 abort 모두 다섯 motor의
STOP 호출을 확인했다. `RE.halt()`는 Bluesky 정의상 cleanup을 실행하지 않는 비상 중단이므로
이 plan의 finalizer 보장을 적용하지 않는다.

아직 실제 IOC prefix로 `SafeStopEpicsMotor`를 생성하는 운전 entry point는 없다. 따라서
이 단계에서도 실제 장비 쓰기나 이동은 발생하지 않았다.

## 17. 단계 G 실제 IOC entry point와 승인 gate

2026-08-12에 `tools/fixed_point_run.py`를 추가했다. 기본 모드는 실제 IOC의 snapshot을
읽고 dry-run 보고서와 `PLAN SHA256`만 출력하며 Ophyd motor 객체를 생성하거나 PV에
쓰지 않는다. hash는 EPICS prefix, 고정점, geometry, duration, 구간 수와 모든 sample의
5축 목표를 canonical JSON으로 직렬화해 계산한다.

실제 실행 경로는 다음 세 조건을 동시에 요구한다.

1. `--execute`
2. 바로 앞 dry-run과 정확히 같은 `--approve-plan-sha256`
3. 현재 충돌 검사가 없음을 인정하는 `--allow-collision-unchecked`

조건을 통과한 후에도 모든 축이 `Enable`, commissioning `Ready`, 정지, limit 해제이고
EMG가 Clear여야 첫 sample을 실행한다. CLI는 HOME이나 Enable을 자동 실행하지 않는다.
시작 pose나 입력값이 달라지면 새 hash가 생성되어 이전 승인은 사용할 수 없다.

실제 IOC의 `(20,0,0) mm`, Pitch/Yaw `+0.1 deg`, 10초/100구간 기본 실행에서 read-only
보고서, software limit PASS와 승인 hash 출력을 확인했다. `--execute`는 사용하지 않았고
hardware write는 없었다.

## 18. 다음 구현 단계

다음 작업은 단계 C의 snapshot 계약을 강화하고 mock Ophyd 계층과 연결하는 것이다.

1. 다섯 축 값을 한 polling generation에서 읽었다는 일관성 판정
2. 실행 전 commissioning flag와 실제 원점 보존 상태 재확인
3. 실제 장비에서 STOP·timeout만 먼저 검증한 뒤 최소 각도 운동 승인
4. 최소 운동은 CRL 없이 더 작은 각도/고정점으로 별도 dry-run 후 수행
5. GUI에는 아직 이동 기능 없이 dry-run 입력과 보고서만 표시하는 방안 검토

## 19. 2026-08-12 실제 IOC 실행 전 상태 감사

실제 `KOHZU:` IOC에서 1~5축을 read-only로 조회했다. 모델 설정은 모두 적용됐고
선택 method는 축별로 `4,4,10,4,10`이지만, 모델 재적용이 물리 확인 flag를 의도적으로
초기화했으므로 전 축 `Ready=0`, `Disable=1`이다.

```text
ConfigApplied:       1,1,1,1,1
DirectionVerified:   0,0,0,0,0
SensorsVerified:     0,0,0,0,0
LimitsVerified:      0,0,0,0,0
HomeEstablished:     0,0,0,0,0
Ready:               0,0,0,0,0
OriginMethodSelected:4,4,10,4,10
OriginMethodActual:  0,0,0,0,0
MSTA:                2,2,2,10,16386
RBV/RVAL:            all zero
DMOV/MOVN:           all 1/0
HLS/LLS/LVIO:        all zero
EmergencyActive:     Clear
```

motor status bit 정의상 `MSTA=16386`인 축 5만 DONE과 HOMED가 함께 설정돼 있다.
축 4의 `MSTA=10`은 DONE과 HOME sensor active이며 HOMED 증거는 아니다. 축 1~3의
`MSTA=2`는 DONE만 의미한다. 과거 commissioning 문서에는 각 축의 방향, 센서 상태,
범위 및 원점 시험이 기록돼 있지만, 현재 controller/IOC 수명에서 원점이 보존됐다고
flag만으로 대체해서는 안 된다.

따라서 다음 실제 쓰기 단계는 1·2·4축 Method 4 HOME, 축 3의 물리 위치 확인 후
Method 10, 축 5 X축 평행 작업 위치 확인 후 Method 10 재확립 여부를 먼저 결정한다.
그 뒤 현재 설치 상태를 재확인해 commissioning flag를 복구하고, 5축을 Enable하기
전에 다시 read-only dry-run과 승인 hash를 생성한다. 이번 감사에서는 PV write, HOME,
Enable 또는 이동을 실행하지 않았다.

## 20. 기본 end-to-end 우선 프로파일로 단순화

이 프로젝트는 EPICS, Ophyd와 Bluesky의 기능을 구현하며 학습하는 시험 프로젝트이므로
기본 동작 확인보다 앞서 추가했던 다수의 안전 gate를 기본 경로에서 비활성화했다.
구현 코드는 삭제하지 않고 이후 재사용할 수 있는 opt-in 실험으로 보존한다.

기본 프로파일에서 실제로 사용하는 별도 제어 PV는 `_able` 하나다.

- motor record의 `SDIS`는 `_able`에 연결
- IOC 시작 시 `_able=1(Disable)`
- `stage_config_apply.py --apply`가 선택 모델 필드를 적용
- 적용 완료 후 모델이 할당된 1~5축을 `_able=0(Enable)`로 전환
- 이후 Ophyd/Bluesky plan은 `_able=Enable`만 요구
- HOME method 선택과 실행 책임은 사용자에게 있음

기본 경로에서 사용하지 않는 항목은 다음과 같다.

- commissioning DB와 ConfigApplied/Direction/Sensors/Limits/Home/Ready flag
- `_able` access-security group
- dry-run SHA-256 승인과 충돌 미검사 승인
- sample별 상태·endpoint·간격 검사
- plan finalizer의 추가 STOP

마지막 네 실행 guard는 `--safety-checks` 및 `ExecutionPolicy` opt-in으로 보존했다.
RunEngine 자체의 표준 motor cleanup 동작은 Bluesky의 기본 동작이므로 그대로다.

실제 IOC와 CA port가 충돌하지 않는 깨끗한 mock 환경에서 32축 generic IOC 시작,
1~5축 모델 적용, `_able` 자동 Enable과 controller motion/write 명령 0건을 확인했다.

## 21. 최초 실제 Bluesky/Ophyd 고정점 end-to-end 시험

단순화된 32축 IOC를 실제 controller에 연결하고 commissioning DB 없이 시작했다.
`stage_config_apply.py --apply`는 1~5축 모델을 적용한 뒤 `_able=Enable`로 전환했다.

Yaw 표면 임시 고정점 `(20,0,0) mm`에서 현재 전 축 0을 기준으로 Pitch와 Yaw를
`+0.1 deg`로 바꾸는 100구간 궤적을 실제 실행했다. 계산 목표와 실제 최종 readback은
다음과 같다.

```text
axis       calculated       actual
X          -0.066262 mm     -0.0661632 mm
Y          -0.034907 mm     -0.0348491 mm
Z          -0.034964 mm     -0.0348491 mm
Pitch      +0.100000 deg    +0.099735 deg
Yaw        +0.100000 deg    +0.101000 deg
```

첫 실행에서는 Pitch의 정상 DMOV 완료 callback이 중복 전달돼 이미 완료된 Ophyd
`MoveStatus`를 다시 완료하려는 `InvalidState`가 발생했다. 물리 축은 모두 목표에 도착해
정지했지만 Python 반환이 지연됐다. `SafeStopEpicsMotor._done_moving()`이 callback 목록을
먼저 분리하도록 수정해 중복 DMOV 완료를 무시하고 회귀시험을 추가했다.

수정 검증을 위해 현재 자세에서 같은 고정점을 유지하며 Pitch/Yaw를 0으로 되돌리는
10구간 reverse 궤적을 실행했다. 이번에는 `EXECUTION COMPLETE`로 정상 반환했다.

```text
final RBV:
X=-0.000163219 mm, Y=+0.000650934 mm, Z=-0.0000990716 mm
Pitch=-0.000274 deg, Yaw=-0.001 deg
all axes: _able=Enable, DMOV=1, MOVN=0, HLS=0, LLS=0
```

잔차는 motor/controller pulse 표현과 각 sample의 반올림 결과다. 이번 시험으로 실제
`IOC -> motor record -> Ophyd -> Bluesky RunEngine -> 5축 controller` end-to-end 이동과
복귀가 확인됐다. IOC는 시험 후에도 실행 중이고 1~5축은 Enable 상태다.

## 22. MRES·OFF·DIR 기반 실행 좌표 양자화

FOFF와 OFF 정책을 변경하거나 과거 궤적을 저장하지 않고, 매 실행의 연속 기구 계산
결과를 현재 motor record가 표현 가능한 user 좌표로 변환하도록 구현했다. snapshot은
기존 동적 상태와 limit 외에 축별 `MRES`, `OFF`, `DIR`을 읽는다.

```text
Pos: user = OFF + pulse * MRES
Neg: user = OFF - pulse * MRES
```

각 연속 sample의 user target을 dial pulse로 변환한 뒤 가장 가까운 정수 pulse로
반올림하고 다시 user 좌표로 변환한다. 정확히 반 pulse이면 dial 좌표에서 0으로부터
멀어지는 방향(`ROUND_HALF_UP`)을 사용한다. 중간 sample과 최종 sample 모두 같은
방식을 적용하며 forward/reverse는 각각 현재 snapshot에서 독립적으로 계산한다.

양자화 후에는 실행 가능한 pose로 고정점 world position, residual, 속도·가속도,
excursion과 software limit를 다시 계산한다. Bluesky/Ophyd에는 연속 target이 아니라
이 양자화된 sample만 전달한다. dry-run은 연속 최종 목표와 양자화 실행 목표를 모두
표시한다.

현재 실제 IOC 좌표에서 임시 고정점 `(20,0,0) mm`, Pitch/Yaw `+0.1 deg`, 100구간을
read-only 계산한 결과는 다음과 같다.

```text
continuous target:
X=-0.066606500, Y=-0.034604699, Z=-0.035159107 mm
Pitch=0.100000000, Yaw=0.100000000 deg

quantized executable target:
X=-0.066663219, Y=-0.034849066, Z=-0.035099072 mm
Pitch=0.099735, Yaw=0.101000 deg

maximum quantized fixed-point residual=0.000568409816 mm
software limits=PASS
```

FOFF와 OFF 값은 읽기만 했고 변경하지 않았다. 이 단계의 실제 IOC 검증은 read-only였고
추가 물리 이동은 실행하지 않았다.

실제 다축 motor plan, GUI 이동 버튼과 자동 Enable은 이 계산·단위시험 단계에 포함하지
않는다.

## 23. 양자화 궤적 실제 왕복 시험

같은 임시 고정점 `(20,0,0) mm`에서 Pitch/Yaw를 현재값에서 `+0.1 deg`로 이동한 뒤,
과거 경로를 저장하거나 역재생하지 않고 현재 snapshot에서 Pitch/Yaw `0 deg` 목표를
새로 계산해 복귀했다. 각 실행은 10초/100구간이며 모든 중간점과 종점을 MRES 격자로
양자화했다. 연속 구간을 양자화하면 인접 sample이 같은 pulse가 될 수 있으므로, plan은
직전 양자화 pose와 값이 달라진 축만 set하고 전 축이 동일한 sample은 건너뛴다.

```text
                         m1    m2    m3    m4    m5
start RVAL/RRBV           1     2    -1    -2    -1
forward RVAL/RRBV       -132   -69   139   155    50
return RVAL/RRBV          0     2     0    -2    -1
expected return           0     2     0    -2    -1
```

복귀 후 전 축 `DMOV=1`이고 X축의 `MOVN=0`, `HLS=0`, `LLS=0`을 확인했다. 이동 전후
`OFF`는 각각 `-0.000663219023373`, `-0.000349065850381`,
`-0.000349071638063`, `0.001`, `0.001`로 변하지 않았고 `FOFF`도 모두 `Variable`로
유지됐다.

독립적으로 다시 계산한 복귀의 연속 목표와 실제 양자화 목표는 다음과 같다.

```text
continuous target:
X=-0.000577851, Y=+0.000406533, Z=-0.000227518 mm
Pitch=0, Yaw=0 deg

quantized executable/final RBV:
X=-0.000663219, Y=+0.000650934, Z=-0.000349072 mm
Pitch=-0.000274, Yaw=-0.001 deg

maximum quantized fixed-point residual=0.000543737358 mm
```

여기서 시작 raw pulse와 복귀 raw pulse가 X와 Z에서 각각 한 pulse 다른 것은 오류가
아니다. 시작점 자체가 현재 `OFF/MRES/DIR`로 표현한 이상적 0도 고정점의 최근접 격자점과
달랐기 때문이다. 이번 정책은 원래 raw pulse 또는 지나간 궤적의 재현이 아니라, 매번
현재 pose에서 계산한 이상적 목표를 각 축의 가장 가까운 표현 가능 좌표로 요청한다.
따라서 동일 raw pulse로의 정확한 복귀가 필요하면 그것은 별도의 시작 pose 저장/복원
정책이어야 한다.

## 24. 운전 도구와 시험 환경 정리

2026-08-13에 `kohzu-bluesky` Conda 환경에 pytest를 설치해 Ophyd, Bluesky, pyepics와
시험 runner를 한 환경으로 통일했다. 전체 결과는 `103 passed, 7 subtests passed`다.

기본 `fixed_point_run.py --execute`가 보존된 안전 실험을 사용하지 않으면서도
`EmergencyActive` PV를 생성하고 연결 대기하던 의존성을 제거했다. 이제 기본 실행은
다섯 motor와 `_able`만 연결한다. `--safety-checks`를 명시한 경우에만 Emergency PV를
생성하고 `OphydFiveAxisBackend`도 이 경우에만 emergency signal을 필수로 요구한다.
임의 고정점, 목표각, 시간과 구간 수를 입력하는 read-only/실행 명령은 README에 정식
운전 절차로 기록했다.
