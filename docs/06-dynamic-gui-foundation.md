# 동적 축 패널 GUI 기반

## 선택한 방식

현재 환경에는 PyDM, PyQt, PySide, tkinter가 없고 Phoebus 4.7.4만 설치되어 있다.
추가 패키지 설치 없이 동적 패널 생성·삭제 요구를 구현하기 위해 Python 표준 HTTP
server와 브라우저 UI를 사용한다. EPICS 접근은 설치된 caget/caput 실행 파일을
argument array로 호출한다.

server는 기본적으로 `127.0.0.1`에만 bind하며 다른 listen 주소를 거부한다. 웹 페이지와
API가 same-origin이고, write 요청에는 server 시작 때 생성한 임의 token이 필요하다.

## 현재 기능

- controller 축 1~32 선택
- catalog의 5개 KOHZU 모델 선택
- 같은 축 패널 중복 생성 방지
- 패널 생성과 삭제; IOC motor record와 axis 객체에는 영향 없음
- 선택 모델과 persistent assignment 불일치 경고
- 위치, 단위, 이동 상태, limit, HOME 방법/상태 표시
- 다섯 commissioning 상태와 Ready 표시
- guarded EnableRequest와 unconditional DisableRequest
- OriginMethod 1~15 사용자 선택
- commissioning Ready·Enable 상태 축의 HOME
- 방향·센서·리미트·원점의 사용자 commissioning 확인 및 취소
- 오류·경고 번호, 해석된 설명, 발생 명령과 원문 표시
- 전체 EMG 상태와 guarded recovery 상태 표시
- 확인 대화상자 후 ReleaseEMG 또는 RefreshAxes 명시 요청
- CA 연결 실패를 패널별로 표시하고 1초 간격 갱신

모델 선택과 패널 생성은 표시만 바꾸며 stage configuration을 적용하지 않는다. 모델
변경은 별도 guarded apply 절차를 사용해야 한다.

## 의도적으로 제외한 write

backend의 URL allowlist는 정해진 commissioning, recovery, OriginMethod 및 운용 중
재HOME 요청으로 제한한다. 다음 write는 이번 단계에 존재하지 않는다.

- motor VAL/RLV/JOGF/JOGR
- raw `_able`
- WRP/SET 좌표 변경
- controller SYS/WTB 명령

OriginMethod는 사용자가 controller manual을 기준으로 1~15 중 선택한다. GUI와 driver는
센서 목록으로 Method를 제한하지 않는다. 변경 시 먼저 Disable하고 선택적인
`HomeEstablished` 확인을 0으로 되돌린다. controller SYS.2는 선택 시점에 쓰지 않고
실제 HOME preflight에서 적용하고 readback한다.

HOME은 backend가
`Commissioning:Ready=1`과 `_able=0`(Enable)을 모두 다시 확인한 경우에만 motor
record의 HOMF를 요청한다. 이후 driver가 정지·EMG, SYS.2
WSY/RSY 확인을 거쳐 ORG를 전송한다. Enable endpoint도
Commissioning:EnableRequest만 쓰므로 Ready가 0이면 IOC가 차단한다.

사용자 확인 API는 DirectionVerified, SensorsVerified, LimitsVerified,
HomeEstablished 네 항목만 허용하며 ConfigApplied는 설정 적용 도구만 변경한다. 확인
승인은 ConfigApplied=1, DMOV=1, MOVN=0 및 Disable을 backend에서 다시 검사한다.
HomeEstablished는 운전 허가 조건이 아닌 사용자 메모성 확인이다. 확인 취소는 먼저
Disable하며 Origin Method 변경과 모델 재적용은 HomeEstablished를 무효화한다.

Recovery write는 두 allowlist endpoint로 제한한다. ReleaseEMG는 확인 대화상자를
거친 뒤 기존 driver PV만 요청하며, driver가 모든 검출 축의 STR에서 물리 EMG 해제를
새로 확인하기 전에는 REM을 보내지 않는다. RefreshAxes도 확인 후 명시적으로 RAX를
요청하고, 완료 상태에는 축 map 검토와 재HOME 필요성을 표시한다. GUI는 자동 recovery를
실행하지 않는다.

## 실행

IOC 및 CA 주소 환경을 준비한 뒤 다음을 실행한다.

```bash
cd ~/Documents/codex-EPICS-control-test
python3 gui/kohzu_gui_server.py --prefix KOHZU:
```

브라우저에서 `http://127.0.0.1:8080`을 연다. server를 외부 network에 bind하는 옵션은
현재 허용하지 않는다.

실제 장비 없는 통합시험:

```bash
./tests/run_gui_integration.sh
```

시험은 loopback simulator/IOC와 port 18080 GUI server를 사용한다. 5모델/32축 구성,
상태/진단 조회, token 검증, move API 부재와 commissioning 미완료 Enable/HOME 차단을
확인한다. 기존 sensor advisory mask에 없는 Method 1도 선택 가능하고, Method 10 선택,
guarded Enable 및 HOME에서 ORG가 한 번 전송되는 것을 검증한다. 활성 mock
EMG에서는 REM이 전송되지 않고 차단 설명이 표시되며, 명시적 RefreshAxes에서만 RAX가
한 번 추가되는지도 검증한다.

## 다음 GUI 단계

다음 단계에서는 실제 방향·센서·리미트를 확인하는 저속 수동 시험 절차를 정의한다.
위치/JOG 제어는 버튼 누름/해제 실패 시 JOG 정지, browser 연결 상실, 명령 확인과
recovery 권한을 먼저 정의한 뒤 확장한다.
