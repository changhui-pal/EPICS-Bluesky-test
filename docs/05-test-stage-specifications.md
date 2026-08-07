# 시험용 KOHZU 5축 스테이지 사양

## 적용 범위

시험 대상으로 제공된 다섯 모델의 KOHZU 공식 제품 페이지와 사양 PDF를 확인했다.
아래 값은 TITAN-A2와 controller 모두 `M1`인 half-step 조건에 맞춘다. 모델 순서는
실제 controller 1~5번이며, 적층 구조는 아래쪽 1번부터 위쪽 5번 순서다. 방향과
원점복귀 방법을 commissioning하기 전까지 모두 `enabled = false`로 유지한다.

| 임시 축 | 모델 | 종류 | 이동 범위 | M1 분해능 | 최고속도 | 센서 | 모터 정격 |
|---:|---|---|---:|---:|---:|---|---|
| 1 | XA05A-L202 | X | ±25 mm | 0.0005 mm/pulse | 5 mm/s | F-107 LIMIT, F-108 HOME | PK523HPMB, 0.75 A/상, 0.36° |
| 2 | XA05A-R201 | X | ±7.5 mm | 0.0005 mm/pulse | 5 mm/s | F-116 HOME/LIMIT | PK523HPMB, 0.75 A/상, 0.36° |
| 3 | ZA05A-W101 | Z | ±4 mm | 0.00025 mm/pulse | 2.5 mm/s | F-115 HOME/LIMIT | PK513PB, 0.35 A/상, 0.72° |
| 4 | SA05A-R2B01 | swivel | ±3.5° | 약 0.000637°/pulse | 9.6°/s | F-116 HOME/LIMIT | PK513PB, 0.35 A/상, 0.72° |
| 5 | RA04A-W01 | rotation | ±177° | 0.002°/pulse | 20°/s | F-113 LIMIT, HOME 없음 | PK524HPMB, 0.75 A/상, 0.36° |

원점 방식은 센서 사양이 자동으로 결정하지 않고 사용자가 선택한다. 기본값은 ARIES
공장 기본이자 KOHZU 표준인 Method 4다. 1, 2, 4축은 우선 Method 4로 등록하고 실제
센서 입력 확인 후 필요하면 다른 호환 방법을 선택한다. 5축 RA04A-W01은 HOME 센서가
없지만 실제 limit 시험 후 CCW limit를 원점으로 사용하는 Method 8을 선택했다. 3축
ZA05A-W101도 모든 센서가 고장났으므로 중심으로 이동한 다음 Method 10의 ORG를
실행해 현재 위치를 0으로 만든다.

## motor record와 pulse 속도

M1 half-step 분해능을 `MRES`로 사용하면 제조사 최고속도는 다음 pulse 속도가 된다.

| 모델 | 계산 | 최고 pulse 속도 |
|---|---:|---:|
| XA05A-L202 | 5 / 0.0005 | 10,000 pulse/s |
| XA05A-R201 | 5 / 0.0005 | 10,000 pulse/s |
| ZA05A-W101 | 2.5 / 0.00025 | 10,000 pulse/s |
| SA05A-R2B01 | 9.6 / 0.000637 | 약 15,071 pulse/s |
| RA04A-W01 | 20 / 0.002 | 10,000 pulse/s |

모두 공장 기본 `SYS.16 = 50,000 pulse/s`보다 작으므로 이 다섯 모델 때문에 SYS.16을
올릴 필요는 없다. SYS.16은 controller의 허용 상한이고 실제 기계 최고속도는 각
모델의 `VMAX`로 별도 제한한다.

catalog의 `VMAX`와 `MRES`는 공식 사양값이다. `LLM/HLM`은 각 모델 공식 전체
이동거리의 1%를 양 끝에서 각각 제외하여 총 98%를 사용한다.

| 축 | 공식 범위 | 끝단별 1% 여유 | 초기 LLM/HLM |
|---:|---:|---:|---:|
| 1 | ±25 mm | 0.5 mm | -24.5 / +24.5 mm |
| 2 | ±7.5 mm | 0.15 mm | -7.35 / +7.35 mm |
| 3 | ±4 mm | 0.08 mm | -3.92 / +3.92 mm |
| 4 | ±3.5° | 0.07° | -3.429608 / +3.429608° |
| 5 | 측정 0~357.350° | 기존 중심 범위와 같은 여유 | +5.214 / +352.134° |

`VELO`는 VMAX의 약 10%,
`VBAS`는 100 pulse/s, `ACCL`은 기본 0.5 s에 해당하도록 정한 보수적인 최초
commissioning 값이며 KOHZU 권장값이라는 뜻은 아니다. 센서가 고장 난 수직 3축은
검증 후 `VELO=0.2 mm/s`, `ACCL=1.0 s`로 더 보수적으로 정했다. 실제 하중과 설치
방향을 확인한 저속 시험 후 조정한다. 제조사 범위를 그대로 LLM/HLM 후보로 기록했지만,
설치물 간섭이 있으면
그보다 안쪽으로 줄여야 한다.

축 4의 계산상 98% 범위 `±3.43°`는 `MRES=0.000637°/pulse`로 정확히 표현되지 않는다.
경계 요청이 바깥쪽 pulse로 반올림되지 않도록 5384 pulse에 해당하는
`±3.429608°`를 실제 LLM/HLM으로 사용한다.

## TITAN-A2 전류 확인

M1은 pulse 분할 설정일 뿐 모터 전류를 결정하지 않는다. XA05A-L202,
XA05A-R201과 RA04A-W01은 0.75 A/상 모터지만, ZA05A-W101과 SA05A-R2B01은
0.35 A/상 모터다. 따라서 후자의 TITAN-A2에 0.75 A RUN 설정을 그대로 적용해서는
안 되며, 전원 투입 전에 해당 채널의 RUN 설정이 0.35 A 모터에 맞는지 TITAN-A2
매뉴얼과 실제 스위치에서 확인해야 한다. IOC 설정은 이 물리 전류 설정을 대신하지
않는다.

## 저장한 공식 자료

- `documents/stage-specifications/XA05A-L202.pdf`: XA05A-L202 전용 사양서
- `documents/stage-specifications/XA05A-R201_legacy.pdf`: 제3자 archive에서 확보한
  KOHZU 구형 catalog XA05A-R201 사양 페이지
- `documents/stage-specifications/ZA05A-W101.pdf`: ZA05A-W101 전용 사양서
- `documents/stage-specifications/SA05A-R2B01_family.pdf`: SA05A-R2B01이 포함된 family 사양서
- `documents/stage-specifications/RA04A-W01.pdf`: RA04A-W01 전용 사양서

각 PDF에서 모델명이 존재하는지 확인했다. 같은 폴더의 `.txt` 파일은 PDF 내용을
검색하고 값의 전사를 대조하기 위해 `pdftotext`로 만든 검토용 파생 파일이다.

## 활성화 전에 필요한 확인

1. 각 축에서 임시 `Pos`가 실제 CW/CCW 중 어느 방향인지 확인하고 `DIR` 확정
2. 1, 2, 4축의 기본 HOME/LIMIT 센서 극성과 `STR` 상태 확인
3. 3축 센서 입력이 고장 상태임을 확인하고 센서 의존 Method 선택 방지
4. 3축은 중심에서 Method 10, 5축은 검증된 CCW limit에서 Method 8 실행
5. TITAN-A2 RUN/STOP 전류 설정 확인, 특히 0.35 A/상 두 모델
6. 설치물 간섭을 반영한 LLM/HLM 축소 여부 결정

## 설치 좌표계 및 방향 확인

사용자가 확인한 실제 5축 설치 좌표계는 다음과 같다.

| 축 | 장비 좌표 역할 | EPICS 방향 설정 |
|---:|---|---|
| 1 | 빔과 평행한 직선축; CW/EPICS +가 앞쪽 | `Pos` |
| 2 | 빔에 수직인 횡방향 직선축 | `Pos` |
| 3 | 상하 Z축 | `Neg` |
| 4 | pitch; CW/EPICS +에서 앞쪽이 올라감 | `Pos` |
| 5 | yaw; 위에서 볼 때 CW=시계방향=EPICS + | `Pos` |

기본 방향 규약은 controller의 CW를 EPICS 양의 방향, CCW를 음의 방향으로 사용한다.
축 3만 설치 방향이 반대이므로 motor record의 `DIR=Neg`를 적용한다. 직선축의 CW와
CCW는 모터 회전 기준이며, 실제 장비 좌표의 명칭은 위 표의 설치 방향을 따른다.

이 확인 전에는 assignment를 활성화하거나 실제 이동·원점복귀 명령을 보내지 않는다.

### 범위 중심 원점의 안전 조건

현재 좌표가 실제 위치와 다를 수 있으므로 기존 motor record soft limit만 믿고 양 끝을
찾을 수는 없다. 최초 측정은 작업자가 계속 관찰하면서 매우 낮은 속도와 짧은 상대
이동으로 수행하고, 각 끝점은 충돌 전에 정지한다. 측정한 두 끝 좌표의 중간으로 이동해
그 위치에서 Method 10의 ORG를 실행해 0으로 설정한 다음에만 위 LLM/HLM을 적용한다.
Method 10의 HOME은 허용하지만 중심을 찾는 과정 자체는 자동화하지 않는다.
