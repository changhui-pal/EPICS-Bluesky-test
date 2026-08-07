# Motor record와 ARIES 단위 변환

## 1. 기본 원칙

사용자와 GUI는 스테이지에 맞는 engineering unit(EGU)을 사용하고 ARIES는 motor
pulse 단위를 사용한다. 이 둘을 연결하는 motor record의 핵심 필드는 `MRES`다.

```text
MRES = EGU / controller pulse
```

현재 TITAN-A2는 M1 half-step을 유지한다. 따라서 스테이지 사양이 full/half step에서
`1 um / 0.5 um`이라면 M1에서의 `MRES`는 다음과 같다.

```text
EGU=mm: MRES = 0.0005 mm/pulse
EGU=um: MRES = 0.5 um/pulse
```

`1/20 micro-step = 0.05 um` 값은 드라이버를 실제 1/20 micro-step으로 설정했을 때만
사용한다. M1 half-step 운용에는 적용하지 않는다. 현재 generic motor record의
`EGU=pulse`, `MRES=1`은 모델 미등록 상태의 placeholder일 뿐 실제 운전 설정이 아니다.

## 2. 위치 변환

motor record의 dial 위치를 `DVAL`, controller pulse 위치를 `P`라고 하면:

```text
P = DVAL / MRES
```

예를 들어 `MRES=0.0005 mm/pulse`, 목표 dial 위치가 `10 mm`이면 목표는 20,000
pulse다. 사용자 좌표 `VAL`에서 dial 좌표로 변환할 때는 motor record가 `DIR`과
`OFF`를 적용한다. Model 3 `move()`에 전달되는 위치는 이미 pulse 좌표이므로 KOHZU
드라이버가 mm를 다시 변환하지 않는다.

위치 readback은 반대 방향으로 처리한다.

```text
controller RDP pulse -> Model 3 motorPosition_ -> motor record
DVAL = pulse * MRES
VAL  = DVAL과 DIR/OFF로 계산한 사용자 좌표
```

## 3. 속도 변환

motor record의 `VBAS`와 `VELO`는 EGU/s이고 Model 3 인수는 step/s, 즉 이
프로젝트에서는 pulse/s다.

```text
minVelocity = VBAS / abs(MRES)   [pulse/s]
maxVelocity = VELO / abs(MRES)   [pulse/s]
```

예:

```text
MRES = 0.0005 mm/pulse
VBAS = 0.05 mm/s  -> 100 pulse/s
VELO = 2.0 mm/s   -> 4,000 pulse/s
```

## 4. 가속도와 WTB 시간

motor record는 `ACCU` 선택에 따라 `ACCL` 또는 `ACCS`를 기준으로 가속도를
계산한다. `ACCL`이 기준이고 `VELO > VBAS`이면:

```text
acceleration[EGU/s2] = (VELO - VBAS) / ACCL
Model 3 acceleration[pulse/s2] = acceleration[EGU/s2] / abs(MRES)
```

KOHZU 드라이버는 Model 3 인수에서 ARIES WTB 시간을 다시 계산한다.

```text
timeSeconds = (maxVelocity - minVelocity) / acceleration
WTB time unit = round(timeSeconds * 100)   # 1 unit = 10 ms
```

위 속도 예에서 `ACCL=0.5 s`이면 Model 3 acceleration은 7,800 pulse/s2이고 WTB
시간은 50이다. table 0과 trapezoidal pattern 2를 사용하므로 결과는 다음과 같다.

```text
WTB1/0/100/4000/50/50/2
```

현재는 acceleration과 deceleration 시간을 같게 설정한다.

## 5. ARIES 속도 규약

WTB 전송 전 다음을 검사한다.

- start speed: 1~2,500,000 pulse/s
- top speed: 2~5,000,000 pulse/s
- start speed는 top speed의 50% 이하
- 매뉴얼 3-1-3의 top-speed 구간별 속도 양자화
- top-speed 구간별 acceleration/deceleration 시간 범위
- WTB 시간 1~10,000 unit
- 유한한 양수 속도와 가속도
- 현재 검출된 축 번호
- `RSY<axis>/16`으로 읽은 축별 최고 속도 상한

## 6. SYS.16 기본값 운용

SYS.16의 공장 기본값 50,000 pulse/s는 정상 운전 속도가 아니라 controller가 허용하는
최고 pulse 속도 상한이다. 다음 조건을 만족하면 기본값을 바꿀 필요가 없다.

```text
VELO / abs(MRES) <= SYS.16
```

EGU에서 본 SYS.16 상한은 다음과 같다.

```text
maximum EGU speed = SYS.16 * abs(MRES)
```

`MRES=0.0005 mm/pulse`이면 기본 SYS.16은 25 mm/s에 해당한다. 하지만 실제 stage의
기계적 허용 속도가 더 낮을 수 있으므로 모델별 `VMAX`와 평상시 `VELO`를 먼저 낮게
제한해야 한다. IOC는 SYS.16을 변경하지 않고 현재 값을 읽어 WTB 설정을 검증한다.

## 7. 현재 구현 범위

- 위치·속도·가속도의 EGU/pulse 관계 확인
- table 0 WTB 변환과 규약 검사 구현
- WTB 전 `RSY<axis>/16` 확인
- APS 이동 전 fresh pulse 위치와 motor raw soft limit 재검증
- motor record `RLV`는 record가 절대 목표로 변환하므로 일반 PV 경로에서는 APS 사용
- 직접 Model 3 relative 요청에는 RPS 명령 생성 경로 사용
- production `st.cmd` 비활성 유지
