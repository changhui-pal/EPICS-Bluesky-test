# 운영·시험·개발 환경 재현

## 범위

이 문서는 Python GUI/Ophyd/Bluesky 계층의 재현 방법과 별도로 설치해야 하는 EPICS
의존성을 구분한다. Python requirements만 설치해도 IOC binary나 EPICS support module이
생성되지는 않는다.

검증 기준은 Python 3.11이다. requirements에는 프로젝트가 직접 사용하는 패키지만
호환 범위로 기록한다. 특정 컴퓨터의 모든 간접 패키지를 담는 `pip freeze` 결과는
운영 설치 목록으로 사용하지 않는다.

## 의존성 계층

```text
requirements/runtime.txt  실제 GUI와 Ophyd/Bluesky 실행
          ↑
requirements/test.txt     runtime + pytest
          ↑
requirements/dev.txt      test + 개발용 정적 검사
```

- 운영 컴퓨터: `runtime.txt` 또는 `environment.runtime.yml`
- CI·mock 시험 환경: `test.txt`
- 개발 컴퓨터: `dev.txt` 또는 `environment.dev.yml`

`websockets`는 mock client뿐 아니라 Uvicorn의 실제 GUI WebSocket protocol에도 필요하므로
runtime 의존성이다. FastAPI가 사용하는 Pydantic 등 간접 패키지는 FastAPI의 dependency
resolver에 맡긴다.

## Conda 권장 설치

저장소 최상위에서 실행한다. YAML의 pip requirements 경로가 저장소 기준이기 때문이다.

운영 환경:

```bash
conda env create -f environment.runtime.yml
conda activate kohzu-runtime
python -m pip check
```

개발 환경:

```bash
conda env create -f environment.dev.yml
conda activate kohzu-dev
python -m pip check
ruff check .
python -m pytest -q
```

새 환경의 Python을 런처에서도 사용하려면 활성화한 상태에서 `which python`으로 경로를
확인하고 `config/runtime.ini`의 `[python] executable`을 그 값으로 바꾼다. 이 항목은
장비별 런타임 설정이므로 Conda 환경을 활성화하는 것만으로 자동 변경되지는 않는다.

## 로컬 장비 설정 초기화

다음 두 실제 설정 파일은 컴퓨터 경로와 controller 정보, 현재 축 할당 상태를 포함하므로
Git에서 제외된다.

```text
config/runtime.ini
config/axis-assignments.ini
```

저장소에는 각각의 형식과 안전한 초기 상태를 담은 `runtime.example.ini`와
`axis-assignments.example.ini`만 추적한다. `./start_kohzu_control.sh`는 로컬 파일이
없을 때 예제를 한 번 복사하며 기존 파일은 덮어쓰지 않는다. IOC를 시작하기 전에
`runtime.ini`의 controller 주소, EPICS 경로, Python 실행 파일을 수정하고 GUI 또는
직접 편집으로 필요한 축 모델을 할당한다. 수동 초기화도 가능하다.

```bash
python3 tools/initialize_local_config.py
```

예제의 controller 주소 `192.0.2.10`은 문서용 주소이고 Python 경로도 자리표시자이므로
수정하지 않은 상태에서는 운영 launcher의 필수 파일 검사를 통과하지 않는다. 축 할당
예제는 모든 축이 `enabled=false`이고 모델이 없는 상태라 장비 설정을 적용하지 않는다.

환경을 이미 만들었다면 다음처럼 갱신한다.

```bash
conda env update -f environment.dev.yml --prune
```

## venv/pip 대안

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements/dev.txt
python -m pip check
ruff check .
python -m pytest -q
```

운영 설치에서는 마지막 두 설치·시험 줄 대신 다음을 사용한다.

```bash
python -m pip install -r requirements/runtime.txt
```

## Python 외부 운영 의존성

현재 검증한 IOC build 조합은 다음과 같다.

```text
EPICS Base 7.0.7
asyn R4-44-2
synApps motor R7-3-1
GNU make 및 C/C++ compiler
```

경로는 `configure/RELEASE`에서 지정한다. 다른 설치 경로에서는 Git 추적 파일을 직접
바꾸기보다 EPICS가 지원하는 `configure/RELEASE.local`에 환경별 override를 두는 방식을
권장한다. `RELEASE.local`은 각 컴퓨터의 로컬 파일로 관리한다.

PyEpics 실행에는 IOC와 별개로 EPICS Channel Access shared library를 찾을 수 있어야
한다. 자동 탐색이 되지 않으면 해당 시스템의 실제 파일로 다음 값을 지정한다.

```bash
export PYEPICS_LIBCA=/usr/local/epics/base-7.0.7/lib/linux-x86_64/libca.so
```

그 밖에 실제 운영에는 ARIES/LYNX controller 네트워크, IOC binary build, 32축 DB,
`config/runtime.ini`, `config/axis-assignments.ini`의 장비별 값이 필요하다. mock 시험은
실제 controller 대신 loopback simulator와 `MOCK:`/`FIXED:` prefix를 사용한다.

## 설치 후 검증 단계

Python만 확인:

```bash
python -c "import bluesky, epics, fastapi, ophyd, uvicorn, websockets"
python -m pip check
ruff check .
python -m pytest -q
```

현재 Ruff 기준은 문법 오류와 정의되지 않은 이름 등 실행 오류 가능성이 큰 규칙부터
적용한다. 기존 코드의 형식과 import 순서를 일괄 변경하지 않으며, 스타일 규칙은 별도
정리 작업에서 단계적으로 추가한다.

EPICS와 mock controller까지 확인:

```bash
make -j2
./tests/run_mock_integration.sh
./tests/run_stage_apply_integration.sh
./tests/run_gui_integration.sh
```

마지막 세 통합시험은 loopback port와 EPICS CA socket을 사용하며 실제 controller 주소에
접속하지 않는다. 운영 장비 실행은 이 설치 검증과 별개로 장비 설정을 검토한 뒤
`./start_kohzu_control.sh`로 수행한다.

## 버전 갱신 정책

1. feature/chore branch에서 직접 dependency 범위 하나씩 갱신한다.
2. `python -m pip check`와 전체 Python 시험을 실행한다.
3. 세 mock 통합시험을 실행한다.
4. 검증한 실제 버전을 `runtime.txt` 상단 주석에 기록한다.
5. Pull Request 검토 후 `main`에 병합한다.

major version 범위는 자동으로 넘지 않는다. 재현이 더 엄격하게 필요한 배포 시점에는
검증된 환경에서 별도의 lock artifact를 만들 수 있지만, 사람이 관리하는 직접 의존성
목록은 이 requirements 구조를 기준으로 유지한다.
