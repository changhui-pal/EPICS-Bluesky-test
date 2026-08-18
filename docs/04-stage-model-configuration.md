# 스테이지 모델과 축 할당 설정

## 목적

IOC에는 1~32축 motor record와 axis 객체를 계속 유지하고, GUI는 그중 필요한 축의
패널만 생성하거나 삭제한다. 스테이지 모델 변경은 IOC 객체를 다시 만드는 작업이
아니라 해당 축에 검증된 모델 설정을 적용하는 작업이다.

시험 모델 5종의 공식 사양을 catalog에 등록했다. 1~5축에는 사용자가 제시한 순서로
모델 이름만 임시 기입했으며 실제 배선 방향과 원점복귀 방법을 확인할 때까지 모든
축은 disabled 상태다. 상세 근거는 `docs/05-test-stage-specifications.md`에 기록했다.

## 파일

- `config/stage-models.ini`: 재사용 가능한 스테이지 모델 catalog
- `config/axis-assignments.example.ini`: Git에서 관리하는 1~32번 빈 축 slot 형식
- `config/axis-assignments.ini`: Git에서 제외되는 현재 장비의 persistent 축 할당
- `tools/validate_stage_config.py`: hardware와 무관한 read-only 검증기
- `tools/stage_config_dry_run.py`: 적용될 값을 보여 주는 read-only 보고서
- `tools/stage_config_apply.py`: 명시적 승인 옵션이 필요한 guarded IOC 적용 도구

## 모델 형식

아래는 형식 설명용 가상 예이며 실제 KOHZU 모델이 아니다.

```ini
[model:EXAMPLE_HALF_STEP]
description = Example only, not a real stage
egu = mm
mres = 0.0005
low_limit = -10
high_limit = 10
vmax = 5
default_velocity = 2
base_velocity = 0.05
acceleration_time = 0.5
```

모든 거리·속도 필드는 같은 `egu`를 사용한다.

- `mres`: TITAN-A2 M1 half-step에서 controller pulse 1개당 EGU, 양수
- `low_limit`, `high_limit`: stage 사양과 설치 조건을 반영할 motor record LLM/HLM
- `vmax`: 모델에 허용할 motor record VMAX
- `default_velocity`: 모델 적용 시 VELO 기본값
- `base_velocity`: VBAS 기본값
- `acceleration_time`: ACCL 기본값, 초

추가로 `motor`, `motor_current_a_per_phase`, `basic_step_angle_deg`, `sensor`,
`source_pdf`를 검토용 metadata로 기록할 수 있다. 이 값들은 motor record에 직접
적용하지 않으며 특히 `sensor`가 축별 원점복귀 방법을 자동 선택하지 않는다.

회전 방향 반전은 음수 MRES가 아니라 축의 `direction`으로 표현한다.

## 축 할당 형식

미사용 축:

```ini
[axis:1]
enabled = false
```

할당 축:

```ini
[axis:1]
enabled = true
model = EXAMPLE_HALF_STEP
direction = Pos
sensors = S2,L-
home_method = 4
```

- `model`: catalog의 모델 이름
- `direction`: motor record DIR에 대응하는 `Pos` 또는 `Neg`
- `sensors`: 사용할 수 있다고 선언하고 실제 commissioning에서 확인할 ARIES 입력
  (`S1`, `S2`, `S3`, `L+`, `L-`, `Z`), 없으면 `none`
- `faulty_sensors`: 장착되어 있지만 고장난 입력을 별도로 기록
- `home_method`: 사용자가 선택한 ARIES SYS.2 값 1~15, 생략 시 기본 4

센서 정보는 설치 상태를 기록하는 참고 자료다. IOC와 validator는 센서 목록을 이용해
HOME Method를 허용하거나 거부하지 않는다. 사용자가 ARIES/LYNX manual과 실제 배선을
확인하여 Method 1~15 중 하나를 선택한다. 센서가 없는 축에서 현재 위치를 원점으로
삼으려면 사용자가 Method 10을 선택할 수 있다.

runtime에서는 축별 `OriginMethod` PV가 선택값을 보존한다. 1, 2, 4축은 4, 3축은
10, 5축은 8로 초기화한다. HOME 요청 전에만 controller SYS.2를 선택값으로 맞추며 WSY 성공
후 RSY readback까지 일치해야 ORG를 허용한다.

`iocBoot/iockohzuAriesLynx/applyConfiguredHomeMethods.cmd`는 초기 Method만 적용한다.
초기 구현의 `OriginMethodMaskConfig`와 `AllowedHomeMethods`는 센서 mask를 강제하지
않는 현재 정책에서 사용되지 않아 제거했다. Method 1~15의 센서 적합성은 사용자가
판단한다.

모델은 센서 구성을 강제로 결정하지 않는다. 같은 모델도 설치된 limit/origin 센서에
따라 서로 다른 `home_method`를 선택할 수 있다.

## 검증 조건

- 모델 이름과 필수 필드
- 유한한 수치와 양수 MRES
- `low_limit < high_limit`
- `0 < base_velocity <= default_velocity <= vmax`
- EGU/s를 MRES로 나눈 WTB pulse 속도 범위
- base 속도가 default 속도의 50% 이하
- default 속도 구간의 WTB 가속 시간 범위
- `vmax / mres`가 현재 SYS.16을 넘으면 필요한 최소 SYS.16 변경값을 경고
- 모든 1~32축 slot 유지
- 할당 축의 sensor 이름, 정상/고장 sensor 중복 여부
- 선택한 home method에 필요한 sensor가 모두 선언됐는지 확인하고 가능한 방법 제시

기본 비교값은 공장 SYS.16인 50,000 pulse/s다. 모델이 이를 넘는다는 이유만으로
거부하지 않고 `ceil(vmax / mres)`를 필요한 최소 SYS.16 값으로 알린다. 단, 실제로
SYS.16을 변경하기 전에는 stage와 TITAN-A2의 허용 속도를 검토해야 한다. WTB의 절대
상한 5,000,000 pulse/s를 넘는 모델은 controller로 표현할 수 없으므로 계속 거부한다.
검증기는 SYS.16을 읽거나 변경하지 않는다.

## 실행

```bash
cd ~/Documents/codex-EPICS-control-test
python3 tools/validate_stage_config.py
python3 -m unittest tests/test_stage_config_validator.py
python3 tools/stage_config_dry_run.py
python3 -m unittest tests/test_stage_config_dry_run.py
```

이 도구는 설정을 읽기만 하며 IOC PV 또는 controller에 값을 쓰지 않는다.

## Dry-run motor record 보고서

`stage_config_dry_run.py`는 enabled 축에 적용될 `DESC`, `EGU`, `MRES`, `LLM/HLM`,
`VMAX`, `VELO`, `VBAS`, `ACCL`, `DIR`, 선언 센서, Method 1~15 사용자 선택 정책과 선택한
SYS.2 원점 방법을 사람이 검토할 수 있는 텍스트로 출력한다. 출력에는 `dbpf`나 IOC shell 명령이 없으며 마지막 상태도
`DISABLED pending operator review and re-home`으로 표시한다.

## Guarded IOC 적용

`stage_config_apply.py`는 모델 이름이 들어 있는 assignment를 준비 대상으로 삼는다.
현재 1~5축 모두 `enabled=false`지만 모델 설정은 미리 적용할 수 있다. 적용 완료 후
각 축의 `_able`은 assignment의 `enabled` 값을 따른다.

기본 실행은 계획만 출력한다.

```bash
python3 tools/stage_config_apply.py --prefix KOHZU:
```

실제 IOC 쓰기는 작업자가 출력과 현재 IOC prefix를 확인한 뒤 `--apply`를 명시해야
한다. 이 명령은 실제 IOC가 준비된 별도 단계에서만 실행한다.

```bash
python3 tools/stage_config_apply.py --prefix KOHZU: --apply
```

안전 조건과 처리 순서는 다음과 같다.

1. 모든 대상 축에 대해 `_able=1(Disable)`, `DMOV=1`, `MOVN=0`을 먼저 읽음
2. 한 축이라도 조건이 다르거나 통신에 실패하면 어떤 설정도 쓰지 않고 전체 거부
3. `_able=1`과 motor record의 SDIS를 유지하여 record processing 차단
4. DESC, EGU, DIR, MRES, LLM/HLM, VMAX, VELO, VBAS, ACCL과 HOME method 적용
5. 각 write를 즉시 readback 비교
6. assignment가 `enabled=true`인 축만 최종적으로 Enable

설정값을 쓰는 동안에는 `_able=Disable`로 SDIS를 활성화하여 MRES 등 설정 변경이
motor record 처리나 이동 요청으로 이어지지 않게 한다. 모든 readback이 일치한 뒤에만
`enabled=true`인 축만 `_able=Enable`로 바꾼다. HOME, ORG, 이동 및 controller 설정 명령은 보내지
않는다. 과거 commissioning PV 기반 검사는 `--development-guards`에서만 보존하며 기본
프로파일에서는 사용하지 않는다.

실제 장비 없이 Channel Access 적용 경로를 검증하려면 다음을 실행한다.

```bash
./tests/run_stage_apply_integration.sh
```

시험은 `127.0.0.1:22322`의 별도 simulator와 `MOCK:` prefix만 사용한다. 실제
`caget/caput`으로 5축 값을 적용하여 모델 field, OriginMethod 수락값과 최종 `_able=0`을
확인한다. simulator에는 polling read만 허용하고 controller write,
이동 또는 정지 명령이 하나라도 나타나면 실패한다.

## 과거 commissioning/guarded Enable 실험

아래 구조는 구현 이력과 향후 재검토를 위해 보존한 개발 실험이다. 현재 기본 IOC는
commissioning DB와 access security를 로드하지 않으며, 모델 적용과 실제 운전은 `_able`
하나만 사용한다.

32축 각각에 모델 적용, 방향, 센서, 리미트, 원점 확인 PV와 이들의 논리 결과인
`Commissioning:Ready`를 둔다. 현재 Ready는 모델, 방향, 센서, 리미트 확인과 motor
record의 `DMOV=1`, `MOVN=0`을 사용하며 HomeEstablished는 포함하지 않는다. 모델을
다시 적용하면 기존 물리 확인을 모두 0으로 초기화하고 field
readback이 끝난 뒤 ConfigApplied만 1로 설정한다.

운영 클라이언트는 `_able` 대신 다음 요청을 사용한다.

- `Commissioning:EnableRequest=1`: 정지 상태를 확인해 Enable
- `Commissioning:DisableRequest=1`: 확인 상태와 무관하게 항상 Disable

두 요청은 처리 후 Idle로 자동 복귀한다. 확인 PV와 Ready는 운전 기록 및 화면 표시
용도이며 Enable을 차단하지 않는다.

GUI가 기록할 수 있는 사용자 확인은 DirectionVerified, SensorsVerified,
LimitsVerified, HomeEstablished로 제한한다. 모든 승인에는 적용 완료, 정지 및 Disable이
필요하다. ConfigApplied는 사용자 승인 대상이 아니며 guarded stage configuration
apply 도구만 성공 후 설정한다.

확인을 취소하면 IOC가 먼저 축을 Disable한다. Origin Method 변경과 모델 재적용은
`InvalidateHomeRequest`를 사용하여 선택적인 HomeEstablished 확인을 지운다.

## `_able` Channel Access 보호

project-local `kohzuAsynMotor.template`은 motor-R7-3-1 `asyn_motor.db` 구조를 따르되
`_able` record에 `ASG=KOHZU_INTERNAL_ENABLE`을 정적으로 지정한다. 정적 지정이므로
CA server가 시작되는 순간부터 동일한 정책이 적용된다.

`kohzuAriesLynxAccessSecurity.acf` 정책은 다음과 같다.

- DEFAULT: 일반 project PV의 CA read/write 허용
- KOHZU_INTERNAL_ENABLE: `_able`의 CA read만 허용하고 write rule은 제공하지 않음

IOC 시작 파일에서는 motor/commissioning record를 로드하고 iocInit 전에 다음을
실행해야 한다.

```text
asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
```

CA access security는 IOC 내부 database link를 막지 않으므로 EnableAction과
DisableAction은 계속 `_able`을 변경할 수 있다. 통합시험에서 직접
`caput MOCK:m1_able 0`은 write-access 오류로 거부되고 값 1이 유지됐으며, 같은 IOC의
guarded EnableRequest와 DisableRequest는 정상 동작했다. 이 검증 범위는 Channel
Access이며 다른 protocol을 외부에 제공할 때는 해당 protocol의 보안 정책을 별도로
검토해야 한다.
