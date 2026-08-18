# KOHZU EPICS Control Test

KOHZU 5축 스테이지를 ARIES/LYNX controller, EPICS motor record,
Ophyd/Bluesky와 웹 GUI로 연결하며 학습·시험하는 프로젝트다. 현재 구현은 최대 32개의
안정된 IOC 축 slot에 스테이지 모델을 동적으로 할당하고, 필요한 축만 GUI 패널로
활성화하는 구조다.

## 구성

```text
Browser GUI ─ WebSocket ─ FastAPI backend ─ persistent Ophyd motor
                                             │
Bluesky RunEngine ───────────────────────────┤
                                             │ Channel Access
                                      EPICS motor record
                                             │
                         asynMotorController / Model 3 driver
                                             │ Ethernet/TCP
                                      ARIES ─ Motionnet ─ LYNX
                                                          │
                                                      TITAN-A2
                                                          │
                                                    KOHZU stage
```

브라우저는 EPICS PV에 직접 접근하지 않는다. Backend가 축별 Ophyd 객체와 EPICS monitor를
유지하고, 유한 이동은 Bluesky RunEngine을 통해 실행한다.

## 현재 구현 범위

- ARIES/LYNX TCP protocol과 최대 32축 EPICS motor IOC
- 모델 catalog와 축별 영구 할당
- GUI 패널 생성·삭제 및 3단계 반응형 보기
- 사용자 좌표 절대·상대 이동, CW/CCW JOG와 정상 감속 STOP
- motor record 주요 field 편집과 readback 확인
- 사용자 선택형 Origin Method 1~15와 HOME
- GUI 종료 시 축 Disable, 설정 보존과 다음 실행 시 패널 복원
- 이상적 5축 고정점 운동 계산, MRES 양자화와 Ophyd/Bluesky 실행 경로
- 실제 장비와 분리된 mock controller/IOC/GUI 통합시험

이 프로젝트는 기능 구현과 학습을 우선하는 시험 환경이다. GUI에는 사용자 인증과 TLS가
없고, HOME method와 모델 교체 후 방향·센서 적합성은 사용자가 확인한다. 실제 장비의
기구 오차 보정은 측정 수단이 없어 현재 보류되어 있다.

## 빠른 시작

검증 기준은 Python 3.11, EPICS Base 7.0.7, asyn R4-44-2, motor R7-3-1이다.

개발 환경을 만든다.

```bash
conda env create -f environment.dev.yml
conda activate kohzu-dev
python -m pip check
```

로컬 장비 설정을 처음 생성한다. launcher도 파일이 없을 때 같은 작업을 자동으로 한 번
수행하며 기존 설정은 덮어쓰지 않는다.

```bash
python3 tools/initialize_local_config.py
```

다음 파일을 현재 컴퓨터와 장비에 맞게 검토한다.

```text
configure/RELEASE.local
config/runtime.ini
config/axis-assignments.ini
```

추적되는 `config/*.example.ini`는 형식만 제공한다. 기본 controller 주소와 Python 경로는
자리표시자이고 모든 축은 모델 없는 Disable 상태이므로 실제 값을 입력해야 한다.

IOC를 빌드하고 통합 launcher를 실행한다.

```bash
make -j2
./start_kohzu_control.sh
```

기본 GUI 주소는 `http://127.0.0.1:8080`이다. Ctrl-C를 누르면 GUI가 축 상태를 정리한 뒤
IOC가 종료된다. 마지막 통합 로그는 다음에서 확인한다.

```bash
less logs/kohzu-control/latest/session.log
```

새 컴퓨터의 전체 설치, EPICS 경로와 PyEpics 설정은
[`docs/12-environment-setup.md`](docs/12-environment-setup.md), 빌드·실행·로그 운용은
[`docs/13-build-and-operation.md`](docs/13-build-and-operation.md)를 따른다.

## 시험

Python 단위시험과 실제 장비를 사용하지 않는 mock 통합시험은 다음과 같다.

```bash
ruff check .
python -m pytest -q
./tests/run_mock_integration.sh
./tests/run_stage_apply_integration.sh
./tests/run_gui_integration.sh
```

Mock 시험은 loopback endpoint와 별도 PV prefix를 사용한다. 실제 IOC와 같은 prefix의
mock IOC를 동시에 실행하지 않는다.

## 설정 파일

| 파일 | 역할 | Git 관리 |
|---|---|---|
| `config/stage-models.ini` | 재사용 가능한 스테이지 모델 catalog | 추적 |
| `config/runtime.example.ini` | runtime 설정 형식과 안전한 예제 | 추적 |
| `config/axis-assignments.example.ini` | 32개 빈 축 slot 예제 | 추적 |
| `config/runtime.ini` | controller, EPICS, Python, GUI의 실제 환경값 | 제외 |
| `config/axis-assignments.ini` | 현재 축 모델·방향·HOME method·활성 상태 | 제외 |
| `configure/RELEASE.local` | 컴퓨터별 EPICS build 경로 override | 제외 |

모델의 필드 형식, 추가·수정·삭제 및 IOC 적용 절차는
[`docs/04-stage-model-configuration.md`](docs/04-stage-model-configuration.md)에 있다.

## 문서 안내

처음 보는 경우에는 환경 구성 → 장비 설정 → GUI 구조 순으로 읽는 것이 가장 빠르다.

- [운영·시험·개발 환경 재현](docs/12-environment-setup.md)
- [IOC 빌드와 통합 운용](docs/13-build-and-operation.md)
- [스테이지 모델과 축 할당 설정](docs/04-stage-model-configuration.md)
- [동적 GUI 구조와 운용](docs/06-dynamic-gui-foundation.md)
- [Ophyd와 Bluesky 기초](docs/08-ophyd-bluesky-basics.md)
- [5축 고정점 운동 설계와 시험](docs/10-fixed-point-kinematics.md)

설계 근거와 구현 이력:

- [ARIES/LYNX protocol 분석과 드라이버 기준](docs/01-aries-lynx-protocol-analysis.md)
- [구현 진행 기록](docs/02-implementation-progress.md)
- [Motor record와 ARIES 단위 변환](docs/03-motor-unit-conversion.md)
- [시험용 5축 스테이지 사양](docs/05-test-stage-specifications.md)
- [실제 controller 시운전 기록](docs/07-real-controller-commissioning.md)
- [Ophyd/Bluesky 실제 IOC 연동 기록](docs/09-ophyd-bluesky-integration-log.md)
- [Python 모듈별 역할](docs/11-python-module-roles.md)
- [제조사 매뉴얼과 스테이지 사양 자료](documents/)

현재 구현 상태의 시간순 기록은 README에 누적하지 않고
[`docs/02-implementation-progress.md`](docs/02-implementation-progress.md)에 유지한다.
