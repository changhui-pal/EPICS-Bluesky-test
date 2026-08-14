# 구현 진행 기록

이 문서는 코드 구현과 검증 범위를 단계별로 기록한다. 향후 각 구현 단계가 끝날 때
변경 파일, 구현 기능, 의도적으로 제외한 기능 및 시험 결과를 추가한다.

## 2026-08-01: 요구사항 및 프로토콜 분석

- ARIES/LYNX와 TITAN-A2 매뉴얼을 분석했다.
- Ethernet/TCP 명령 형식, CRLF delimiter, TAB 응답 및 비동기 `SYS` 이벤트를 정리했다.
- Model 3 메서드와 ARIES 명령의 대응 방안을 작성했다.
- speed table 0, M1 half-step, motor record soft limit 등의 운용 원칙을 확정했다.
- 센서 구성과 원점 방법을 스테이지 모델에서 분리해 축별로 설정하기로 했다.

상세 내용은 `docs/01-aries-lynx-protocol-analysis.md`에 기록되어 있다.

## 2026-08-03: IOC 및 Model 3 골격

구현:

- EPICS Base 7.0.7, asyn R4-44-2, motor R7-3-1 빌드 연결
- `KohzuAriesLynxController`와 `KohzuAriesLynxAxis` 클래스
- 최대 32축 controller 생성 인수
- `KohzuAriesLynxCreateController` IOC shell 명령

안전 상태:

- production `st.cmd`의 TCP/controller 생성은 주석 상태
- poller 미시작
- 모든 이동 메서드는 `asynError` 반환
- motor record 미생성

검증:

- IOC 빌드 및 초기화 성공
- IOC shell 명령 등록 확인

## 2026-08-03: 읽기 전용 프로토콜 계층

구현:

- ARIES 응답의 `C`, `E`, `W` 구분
- TAB 필드 및 오류/경고 번호 파싱
- axis command token 매칭
- 비동기 `E/W SYS` 메시지 분리
- asynOctet CRLF 입출력
- 읽기 전용 `IDN`, `RAX` transaction

검증:

- 정상 IDN/RAX 응답
- 축 오류 `E APS1 304`
- 비동기 `E SYS 5`, `W SYS 52`
- 잘못된 응답 거부
- parser unit test 통과

## 2026-08-03: Mock TCP 통합 시험

추가 파일:

- `tests/mock_aries_server.py`
- `tests/mock_ioc.cmd`
- `tests/run_mock_integration.sh`

가상 서버는 로컬에서 한 IOC 연결만 받고 초기에는 `IDN`과 `RAX`에 응답하도록
작성했다. 이후 읽기 전용 축 명령과 비구동 `STP` 검증을 단계별로 추가했다. `IDN`
응답 전에 `W SYS 52`를 보내 비동기 이벤트가 transaction 응답을 방해하지 않는지
확인한다. 가상 서버는 모터 이동을 시작하는 명령을 구현하지 않는다.

통합 시험의 성공 조건:

- IDN 결과: `ARIES 1 4 3`
- RAX 검출 축 수: 6
- controller communication 상태: connected
- controller report에 마지막 비동기 `W SYS 52` 이벤트 존재

실제 장비에는 접속하지 않으며 production `st.cmd`도 변경하지 않는다.

## 2026-08-03: 읽기 전용 축 polling

구현:

- `RDP`: controller pulse 위치 조회
- `STR`: 이동, EMG, ORG, CW/CCW hardware limit 상태 조회
- `ROG`: 원점 복귀 완료 상태 조회
- RAX에서 검출된 축만 polling하고 나머지 pre-created 축은 비활성 처리
- 위치와 상태를 Model 3 parameter library에 반영
- 통신 실패를 `motorStatusCommsError_`와 `motorStatusProblem_`에 반영
- 읽기 전용 discovery 성공 후에만 poller 시작

현재 CW limit은 high-limit, CCW limit은 low-limit에 대응시켰다. 실제 방향과 motor
record `DIR`의 관계는 실제 장비 저속 시험에서 확인해야 한다.

Mock 확장:

- 1~6축의 `RDP`, `STR`, `ROG` 응답 지원
- 각 축은 정지, homed, ORG sensor on 상태
- 축 n의 mock 위치는 `n * 100` pulse
- 1번 축과 6번 축 readback을 통합 시험에서 확인

이 단계에서 제외된 기능:

- 이동, jog, home 및 set-position 명령
- 실제 ARIES 접속

## 2026-08-03: Generic motor record 연결

구현:

- synApps motor의 `asyn_motor.db`를 사용하는 최대 32축 substitutions 추가
- controller 축 주소 0~31을 `m1`~`m32` record에 연결
- 스테이지 모델이 정해지기 전의 공통 단위를 `pulse`, `MRES=1`로 설정
- 초기 placeholder에는 motor record가 허용하는 raw pulse 범위만 임시 적용
- mock IOC에서 초기화 직후 32개 record를 모두 `Disable`로 전환
- 실패 시 누락된 기대값과 IOC 출력을 표시하도록 통합 시험 진단 개선

검증:

- substitutions 설치와 IOC database 로드 성공
- mock의 1번 축 `RBV=100 pulse`, 6번 축 `RBV=600 pulse` 확인
- 1번 축 `DMOV=1` 확인
- 미설정 record의 `_able=Disable` 확인
- 로컬 TCP mock 통합 시험 통과

현재 placeholder의 속도, 가속도, 이동 범위 및 분해능은 실제 운전값이 아니다. 이후
스테이지 모델 등록 단계에서 제조사 사양과 축별 설치 조건을 검증한 값으로 교체해야
한다. production `st.cmd`에는 아직 database나 controller를 활성화하지 않았으며 이동,
jog, home 및 set-position 메서드도 계속 `asynError`를 반환한다.

## 2026-08-03: 정상 감속 정지와 emergency lock 정책

구현:

- Model 3 `stop()`을 ARIES `STP<axis>/0` 명령에 연결
- routine STOP에는 mode 0(감속 정지)만 사용하고 mode 1(비상정지)은 사용하지 않음
- 검출 축 범위를 벗어난 정지 요청 거부
- `STR`의 EMG 상태를 기존대로 `motorStatusProblem_`에 반영
- mock 서버가 `STP1/0`만 받아들이고 수신 명령을 기록하도록 확장
- mock motor record의 `STOP` 처리부터 wire command까지 통합 검증

Emergency lock 운용 정책:

- `E SYS 5`: 물리적인 emergency-stop 원인을 제거한 뒤 사용자가 명시적으로 `REM` 요청
- `E SYS 6`: Motionnet 연결을 복구한 뒤 사용자가 명시적으로 `RAX` 재구성 요청
- 두 원인이 함께 발생하면 원인 해결 후 `REM`과 `RAX`가 모두 필요
- IOC는 오류 수신이나 재접속만으로 `REM` 또는 `RAX`를 자동 실행하지 않음
- 이번 단계에서는 release 명령을 PV나 IOC shell 명령으로 노출하지 않음
- emergency stop 이후 pulse 유실과 실제 위치 불일치 가능성이 있으므로 해제만으로
  정상 운전 상태로 간주하지 않으며 재원점 복귀가 필요할 수 있음

검증:

- 전체 IOC 빌드 성공
- protocol parser unit test 통과
- mock server에서 정확히 `STP1/0` 수신 확인
- motor record를 다시 `Disable` 상태로 복귀한 뒤 통합 시험 통과

여전히 구현하지 않은 동작 명령은 absolute/relative move, jog, home, set-position 및
emergency lock release다. production `st.cmd`는 계속 비활성 상태다.

## 2026-08-03: 오류·경고 설명과 진단 PV

구현:

- 제조사 매뉴얼의 system, parameter, drive, feedback, speed-table, trigger 및
  emergency-stop 오류 코드를 설명 문자열로 구조화
- 경고 51, 52, 350의 설명 추가
- `10n` parameter 오류와 `50n` MPS 설정 오류를 해당 parameter/축 번호로 해석
- 알려지지 않은 펌웨어 코드에는 `Unknown ARIES error/warning code`를 제공하면서
  숫자 코드와 원문 응답은 그대로 보존
- 동기 명령 응답과 비동기 `E/W SYS` 이벤트 모두 같은 진단 처리 경로 사용
- 오류와 경고가 서로 덮어쓰지 않도록 각각 마지막 상태를 독립 보존

추가된 읽기 전용 controller 진단 PV:

```text
$(P)Diag:LastErrorCode
$(P)Diag:LastErrorText
$(P)Diag:LastErrorCommand
$(P)Diag:LastErrorRaw
$(P)Diag:LastWarningCode
$(P)Diag:LastWarningText
$(P)Diag:LastWarningCommand
$(P)Diag:LastWarningRaw
```

설명·명령·원문 PV는 EPICS의 40자 string 제한으로 진단 내용이 잘리지 않도록 CHAR
waveform으로 구성했다. 축 명령 오류의 command에는 `APS1`, `STP2`처럼 controller가
응답한 축 번호가 포함된다.

검증:

- 고정 오류 304, parameter 계열 103, MPS 계열 502, 경고 52 및 미등록 코드 단위 시험
- mock에서 비동기 `E SYS 5`와 `W SYS 52`를 IDN 응답보다 먼저 전송
- 오류 코드 5, 원인 제거 후 `REM`이 필요하다는 설명, `SYS` 명령 및 원문 확인
- 경고 코드 52, Motionnet 구성 증가 설명, `SYS` 명령 및 원문 확인
- 오류를 수신해도 IOC가 `REM`이나 `RAX`를 자동 전송하지 않음을 mock 동작으로 유지
- 전체 빌드, parser unit test 및 로컬 TCP 통합 시험 통과

production `st.cmd`에는 진단 database도 아직 로드하지 않았다. 실제 장비 연결은 계속
비활성 상태다.

## 2026-08-03: 명시적 emergency 복구 인터페이스

추가된 PV:

```text
$(P)Recovery:EmergencyActive  # 하나 이상의 검출 축에서 EMG 입력 감지
$(P)Recovery:ReleaseEMG       # guarded REM momentary 요청
$(P)Recovery:RefreshAxes      # 명시적 RAX momentary 요청
$(P)Recovery:Status           # 거부/성공 결과와 후속 조치
```

`ReleaseEMG` 처리:

1. 요청 시점에 1번부터 현재 검출 축까지 `STR`를 다시 조회한다.
2. 한 축이라도 EMG 입력이 활성 상태면 `REM`을 전송하지 않고 거부한다.
3. 한 축이라도 상태 조회에 실패하면 안전 여부를 확인할 수 없으므로 거부한다.
4. 모든 축의 물리 EMG 입력이 해제된 경우에만 `REM`을 한 번 전송한다.
5. 성공하더라도 위치가 유효하다고 간주하지 않고 status에 재원점 필요성을 표시한다.

`RefreshAxes` 처리:

- 사용자가 명시적으로 요청했을 때만 `RAX`를 실행한다.
- 반환된 검출 축 수로 기존 32개 axis 객체의 활성/비활성 flag를 다시 설정한다.
- 복구 후 축 구성 확인과 재원점이 필요하다는 status를 제공한다.
- Motionnet 재접속 또는 오류 수신만으로 자동 실행하지 않는다.

두 요청 bo는 동작 후 driver parameter를 0으로 되돌리는 momentary command다. 요청 실패
시 record에는 write alarm이 발생할 수 있으며 구체적인 이유는 `Recovery:Status`와
`Diag:LastError*`에서 확인한다.

Mock 검증:

- 6축 모두 `STR`에서 EMG active 상태를 반환
- `Recovery:EmergencyActive`가 `Active`로 갱신되는지 확인
- `ReleaseEMG` 요청 후 `REM blocked: physical EMG input remains active` 확인
- mock server에 `REM`이 전혀 도착하지 않았음을 확인
- discovery용 1회와 사용자 요청용 1회, 총 2회의 `RAX`만 수신됨을 확인
- `RAX completed; axis map refreshed, verify and re-home` 결과 확인
- 전체 빌드, parser unit test 및 로컬 TCP 통합 시험 통과

실제 원인이 제거된 장비에서의 `REM` 성공 경로와 Motionnet 복구 동작은 아직 시험하지
않았다. production `st.cmd`는 계속 비활성 상태이며 실제 장비에 어떤 복구 명령도
전송하지 않는다.

## 2026-08-03: Speed table 0 변환과 비구동 설정

구현:

- Model 3의 `minVelocity`, `maxVelocity`, `acceleration` 단위를 pulse domain으로 해석
- table 번호는 프로젝트 결정에 따라 항상 0 사용
- 가속 패턴은 trapezoidal drive인 2 사용
- 감속도 motor record의 acceleration과 동일한 시간으로 설정
- `acceleration time = (top speed - start speed) / acceleration` 계산
- 계산 시간을 WTB의 10 ms 정수 단위로 반올림
- 매뉴얼 3-1-3의 최고 속도 구간별 속도 양자화와 가감속 시간 범위 적용
- 시작 속도가 최고 속도의 50%를 초과하면 전송 전 거부
- NaN/무한대, 음수, 0 acceleration 및 WTB 절대 범위를 벗어난 값 거부
- WTB 직전에 `RSY<axis>/16`을 읽어 축별 최고 속도 제한과 비교
- 검출되지 않은 축 또는 SYS.16 초과 값을 거부

생성 예:

```text
입력: axis=1, minVelocity=100 pps, maxVelocity=1000 pps,
      acceleration=4500 pps²
계산: (1000 - 100) / 4500 = 0.2 s = WTB 20 units
확인: RSY1/16
출력: WTB1/0/100/1000/20/20/2
```

명시적 비구동 설정 명령:

```text
KohzuAriesLynxConfigureSpeedTable0(
    "<motor-port>", <axis>, <start-pps>, <top-pps>, <acceleration-pps2>)
```

이 IOC shell 명령은 controller instance를 motor port 이름으로 찾은 후 table 0만
설정한다. 자동 실행되지 않으며 APS/RPS/JOG/ORG 같은 이동 시작 명령을 호출하지 않는다.

검증:

- 정상 입력에서 `WTB1/0/100/1000/20/20/2` 생성 확인
- 시작 속도 50% 초과와 지나치게 짧은 가속 시간 거부 확인
- mock server에서 `RSY1/16` 조회 확인
- mock SYS.16 값 50000 pps 아래인 WTB만 전송
- 정확한 WTB command 수신과 정상 응답 parsing 확인
- mock server에 APS, RPS, JOG, ORG가 전송되지 않았음을 확인
- 전체 빌드, 단위 시험 및 로컬 TCP 통합 시험 통과

아직 Model 3 `move()`나 `moveVelocity()`에는 speed table 설정을 연결하지 않았다.
production `st.cmd`도 계속 비활성 상태다.

## 2026-08-03: Absolute/relative 이동 명령 생성기

실제 controller I/O와 분리된 순수 명령 생성기를 추가했다.

```text
absolute: APS<axis>/0/<target-pulse>/1
relative: RPS<axis>/0/<delta-pulse>/1
```

고정 정책:

- speed table은 0
- response method는 Quick 방식 1
- Ethernet에서는 STX를 붙이지 않음
- CRLF는 향후 asyn output EOS가 추가하므로 생성 문자열에는 포함하지 않음

입력은 motor record가 `MRES`로 변환한 뒤 Model 3 `move()`에 전달하는 pulse 단위다.
Model 3 interface가 double이므로 wire command 생성 시 가장 가까운 정수 pulse로 한 번만
반올림한다. 반올림 결과가 ARIES 범위 `-134,217,728..+134,217,727` 안에 있는지
검사한다. relative 명령에서는 이 범위가 이동량에 적용되며, 현재 위치와 더한 최종
좌표 범위는 실제 실행 단계에서 최신 `RDP` 또는 controller 응답으로 추가 검증해야 한다.

단위 시험:

- `axis=1`, absolute `1000` -> `APS1/0/1000/1`
- `axis=32`, relative `-12.6` -> `RPS32/0/-13/1`
- 최소·최대 pulse 경계 허용
- 축 0과 pulse 범위 초과 거부
- 전체 빌드와 기존 TCP 통합 회귀 시험 통과

생성기는 controller의 `transact()`에서 호출되지 않으며 Model 3 `move()`도 계속
`asynError`를 반환한다. 따라서 이번 단계에서 APS/RPS는 실제 장비나 mock server에
전송되지 않는다. production `st.cmd`도 계속 비활성 상태다.

## 2026-08-03: 스테이지 모델 catalog와 32축 할당 검증

추가 파일:

- `config/stage-models.ini`
- `config/axis-assignments.ini`
- `tools/validate_stage_config.py`
- `tests/test_stage_config_validator.py`
- `docs/04-stage-model-configuration.md`

설계:

- 모델 catalog에는 M1 half-step 기준 MRES, EGU, 이동 범위, VMAX, 기본 VELO/VBAS와
  ACCL을 저장
- 센서와 원점 복귀 방법은 모델에서 분리하고 축 assignment에 `home_method`로 저장
- 방향 반전은 음수 MRES 대신 축별 `direction=Pos/Neg`로 표현
- GUI 패널 생성·삭제와 무관하게 `axis:1`~`axis:32` slot을 항상 유지
- 실제 모델 정보가 없으므로 catalog는 비우고 모든 축을 disabled로 초기화

Offline 검증:

- 필수 필드, 유한 수치, 양수 MRES 및 travel limit 순서
- `base_velocity <= default_velocity <= vmax`
- EGU 속도를 pulse/s로 변환한 뒤 WTB 범위와 50% 시작 속도 규칙 확인
- default 속도 구간별 WTB acceleration time 확인
- `vmax / mres`가 현재 SYS.16 비교값을 넘으면 필요한 변경값을 경고
- enabled 축이 등록 모델, DIR 및 SYS.2 home method 1~15를 갖는지 확인
- 32개 slot 누락 거부

검증 결과:

- 현재 빈 catalog와 32개 disabled slot: 성공
- 가상 half-step 모델과 enabled 축 할당: 성공
- SYS.16 기본값 초과 모델: 모델은 허용하고 필요한 최소 SYS.16 값을 경고
- enabled 축의 미등록 모델: 거부
- 32축 slot 누락: 거부
- Python unit test 5개 통과

검증기는 파일을 읽기만 하며 IOC record나 controller를 변경하지 않는다. 아직 모델
설정을 motor record에 적용하는 runtime 계층은 구현하지 않았고 production `st.cmd`도
계속 비활성 상태다.

## 2026-08-03: SYS.16 변경 알림과 motor record dry-run

정책 변경:

- `vmax / mres`가 공장 기본 SYS.16 50,000 pulse/s를 넘는 모델을 offline catalog에서
  거부하지 않음
- `ceil(vmax / mres)`를 필요한 최소 SYS.16 값으로 경고
- 실제 SYS.16 변경 전 stage 기계 속도와 TITAN-A2 허용 조건을 검토하도록 안내
- WTB 절대 상한 5,000,000 pulse/s 초과는 표현 불가능하므로 계속 오류 처리
- 실제 WTB 전송 시 읽은 현재 SYS.16보다 top speed가 높으면, SYS.16 변경이 먼저
  완료되지 않은 상태이므로 기존대로 WTB 전송 차단

추가된 `tools/stage_config_dry_run.py`는 enabled 축에 적용될 다음 값을 출력한다.

```text
DESC, EGU, MRES, LLM, HLM, VMAX, VELO, VBAS, ACCL, DIR
planned SYS.2 home_method
required SYS.16
```

안전 특성:

- 출력 첫 부분에 `NO IOC OR CONTROLLER VALUES WERE CHANGED` 표시
- 실행 가능한 `dbpf` 또는 IOC shell 명령을 생성하지 않음
- 모델 적용 후 최종 상태를 `DISABLED pending operator review and re-home`으로 표시
- 현재 실제 모델과 enabled 축이 없으므로 field assignment를 생성하지 않음

검증:

- 60,000 pulse/s가 필요한 가상 모델을 오류 없이 허용하고 `SYS.16=60000` 경고 확인
- dry-run에 motor record 값, DIR, home method와 disabled 상태 포함 확인
- dry-run 출력에 `dbpf`가 없음을 확인
- validator 5개와 dry-run 1개, 총 Python unit test 6개 통과

## 2026-08-03: 시험용 KOHZU 5축 공식 사양 등록

공식 KOHZU 제품 페이지와 PDF에서 XA05A-L202, XA05A-R102, ZA05A-W101,
SA05A-R2B01, RA04A-W01의 M1 half-step 분해능, 이동 범위, 최고속도, 센서와
모터 정격을 대조했다. 공식 PDF 5개를 `documents/stage-specifications/`에 저장하고
검색·전사 검증용 text도 함께 생성했다.

`config/stage-models.ini`에 다음을 반영했다.

- 공식 M1 분해능을 motor record MRES 후보로 사용
- 공식 이동 범위와 최고속도를 LLM/HLM 및 VMAX 후보로 사용
- 최초 저속 시험을 위한 프로젝트 초기 VELO=VMAX 약 10%, VBAS=100 pulse/s,
  ACCL=0.5 s 설정
- 센서, 모터, 상전류, 기본각과 출처 PDF를 비적용 metadata로 보존
- 다섯 모델의 VMAX가 약 10,000~15,071 pulse/s이므로 기본 SYS.16 50,000 pulse/s
  안에 있음을 확인

1~5축에는 제공된 모델 순서를 임시 기록했지만 모두 disabled 상태로 유지했다. 실제
controller 축 순서, DIR, 센서 동작과 SYS.2 원점 방법을 확인하기 전에는 활성화하지
않는다. 또한 ZA05A-W101과 SA05A-R2B01의 모터는 0.35 A/상이므로 0.75 A/상 모델과
같은 TITAN-A2 RUN 전류를 일괄 적용하지 않도록 hardware 확인 항목을 추가했다.

## 2026-08-03: 실제 적층 순서, R201 및 원점 정책 수정

- 실제 controller/적층 순서를 아래부터 1~5축으로 확정
- 2축을 XA05A-R102에서 구형 XA05A-R201로 교체하고, 제3자 archive에 보존된 KOHZU
  구형 catalog 사양을 반영
- 각 공식 전체 이동거리의 1%를 양 끝에서 각각 제외한 98% 범위를 LLM/HLM으로 설정
- 1, 2, 4축은 기본 HOME 센서 위치를 원점으로 사용할 계획
- HOME 센서가 없는 5축과 모든 센서가 고장난 3축은 측정한 기계 범위 중심을 원점으로
  사용하는 `range_center` 전략으로 구분
- range-center 축에는 controller SYS.2 home method를 지정하지 못하도록 validator 보강
- 방향은 임시 `Pos`로 기록하고 실제 연결 후 CW/CCW와 대조하여 수정 예정

이 변경은 offline 설정과 문서에만 적용했으며 축 활성화, 이동, 원점복귀 및 controller
설정 변경은 수행하지 않았다.

## 2026-08-03: 사용자 선택형 Origin return method 검증

ARIES/LYNX 매뉴얼 3-9절의 Method 1~15 필수 센서 표를 설정 검증기에 반영했다.

- 원점 방식은 센서 사양으로 자동 확정하지 않고 사용자가 `home_method`로 선택
- 생략 시 ARIES 공장 기본과 같은 Method 4 사용
- `sensors`는 선택 가능한 방법을 계산하고 잘못된 선택을 경고하는 자료로만 사용
- `faulty_sensors`와 usable sensor가 중복되면 설정 오류
- Method 10은 센서 없이 선택 가능하며 ORG 실행 시 이동 없이 현재 위치를 0으로 설정
- 1, 2, 4축은 Method 4, 3, 5축은 범위 중심에서 사용할 Method 10을 초기 선택
- dry-run에 declared sensors, selectable methods와 user-selected SYS.2를 표시

모든 할당 축은 계속 disabled 상태이며 controller SYS.2 또는 motor record를 변경하지
않았다.

## 2026-08-03: Model 3 HOME과 SYS.2 preflight

아래 구현은 당시 단계의 기록이며, 다음 절의 `OriginMethod` PV 및 HOME 시 WSY 적용
방식으로 대체되었다.

`KohzuAriesLynxAxis::home()`을 ARIES ORG에 연결했다. 처리 순서는 다음과 같다.

1. fresh STR로 해당 축의 물리 EMG 입력 확인
2. `RSY<axis>/2`로 controller의 실제 Origin return method 확인
3. `KohzuAriesLynxSetHomeMethod()`로 등록한 사용자 선택값과 비교
4. Method 10은 speed table 변경 없이 `ORG<axis>/0/1` 전송
5. 다른 Method는 Model 3 HOME 속도·가속도로 table 0 검증 후 ORG 전송

SYS.2가 다르면 필요한 값만 `HomeStatus`에 알리고 ORG와 WSY를 모두 보내지 않는다.
축별 `ExpectedHomeMethod`와 `HomeStatus` 진단 PV를 32축에 추가했다. production
`st.cmd`의 controller 생성은 계속 주석 상태다.

검증:

- C++ 빌드 성공
- protocol parser와 Python 설정 test 성공
- mock Method 10에서 `STR1`, `RSY1/2`, `ORG1/0/1` 순서 확인
- 선택 Method 4/실제 SYS.2=10 불일치 축에서 ORG2가 전송되지 않음을 확인
- 기존 WTB/SYS.16, 정상 STOP, EMG 중 REM 차단과 RAX 명시 요청 시험 유지

## 2026-08-03: 축별 OriginMethod PV와 HOME 시 SYS.2 적용

이전의 read-only `ExpectedHomeMethod` 진단을 사용자 쓰기 가능한 축별
`OriginMethod`와 실제 controller readback `OriginMethodRBV`로 교체했다.

- PV write는 driver 내부 선택값만 변경하고 WSY를 즉시 보내지 않음
- 초기 선택값은 1, 2, 4축 Method 4, 3, 5축 Method 10
- HOME 시 fresh STR로 정지 및 EMG 해제 확인
- RSY로 실제 SYS.2를 읽고 다르면 `WSY<axis>/2/<selected>` 전송
- WSY 응답 뒤 RSY를 다시 읽어 선택값과 일치할 때만 ORG 전송
- readback 불일치, 통신 오류 또는 이동 중에는 ORG 차단 및 HomeStatus 갱신
- Method 10에는 speed table 갱신을 생략하고 다른 방법에는 기존 table 0 검증 적용

mock integration에서 SYS.2 4를 PV 선택 10으로 변경하여
`STR1 → RSY1/2 → WSY1/2/10 → RSY1/2 → ORG1/0/1` 순서를 확인했다. WSY 성공
응답 후에도 RSY 값이 바뀌지 않는 가상 2축에서는 ORG2가 전송되지 않았다.

## 2026-08-03: 센서 기반 runtime OriginMethod 제한

offline validator의 Method별 필수 센서 표를 runtime mask로 연결했다.

- 축별 `AllowedHomeMethods` 문자열 PV 추가
- `OriginMethodMaskConfig`로 post-iocInit mask 설정
- `OriginMethodSelectedRBV`로 driver가 실제 수락한 선택값 제공
- 허용되지 않은 `OriginMethod` write는 controller 통신 전에 asyn error로 거부
- HOME에서도 선택값이 mask에 포함되는지 다시 확인
- driver 생성 기본은 센서 이동을 피하도록 Method 10만 허용
- `applyConfiguredHomeMethods.cmd`가 1~5축 mask와 초기 Method를 명시적으로 적용

현재 mask는 1, 2, 4축 712(Method 4,7,8,10), 3축 512(Method 10), 5축
704(Method 7,8,10)다. 미할당 축은 활성화 전에 센서 구성을 별도로 적용해야 한다.

검증 결과:

- C++ 전체 빌드 성공
- Python 설정 test 11개 성공, `S2,L+,L- → 4,7,8,10 → mask 712` 확인
- mock 3축에서 Method 4 write 거부, 수락값 10 및 허용 목록 `10` 유지
- SYS.2 WSY/RSY/ORG, EMG/REM, STOP 및 SYS.16 기존 통합 시험 통과

## 2026-08-04: Model 3 절대·상대 위치 이동 연결

`KohzuAriesLynxAxis::move()`를 기존 APS/RPS 명령 생성기와 controller transaction에
연결했다. 이동 직전 처리 순서는 다음과 같다.

1. Model 3 double 위치를 controller 정수 pulse로 한 번 반올림
2. fresh RDP/STR/ROG snapshot으로 현재 위치, 정지와 EMG 해제 확인
3. 절대 목표 또는 `현재 위치 + 상대 이동량` 계산
4. raw motor soft-limit 범위 확인
5. speed table 0 생성, RSY SYS.16 확인과 WTB 전송
6. APS/RPS quick-response 명령 전송 후 poll로 완료 확인

축별 `MoveStatus` PV에 사전 차단 이유 또는 수락 목표를 기록한다. soft-limit 계산은
순수 함수로 분리하여 경계값 포함, 1 pulse 초과와 잘못된 limit 순서를 hardware 없이
시험했다.

motor record의 `RLV`는 내부적으로 새 절대 `VAL`을 계산하여 Model 3에 전달하므로 mock
통합 시험에서는 `VAL=1000` 후 `RLV=50`이 각각 `APS1/0/1000/1`과
`APS1/0/1050/1`로 나타났다. 직접 relative Model 3 요청의 RPS 생성은 C++ 단위
테스트에서 확인했다.

검증 결과:

- 전체 C++ 빌드 성공
- protocol/motion C++ test 성공
- Python 설정 test 11개 성공
- 두 이동 모두 WTB 전 SYS.16 확인, 최종 RDP=1050 pulse 확인
- HOME SYS.2, Method mask, STOP, EMG/REM과 RAX 기존 통합 시험 통과
- production TCP/controller 및 실제 축은 계속 비활성

## 2026-08-04: Model 3 연속 JOG(FRP) 연결

`KohzuAriesLynxAxis::moveVelocity()`를 ARIES의 Free Rotation Drive인 `FRP`에
연결했다. 제조사 매뉴얼상 형식은 `FRP axis/table/direction`이고 방향은 0=CW,
1=CCW다. Model 3의 부호 있는 `maxVelocity`는 현재 양수=CW, 음수=CCW로 잠정
대응하며 실제 배선 시험 후 motor record DIR과 함께 확인한다.

FRP 전송 전에는 fresh RDP/STR/ROG snapshot, 축 정지, EMG 해제, 진행 방향의
하드 리미트, 현재 위치의 motor-record raw soft limit을 검사한다. 이후 속도 크기와
가속도로 table 0을 만들고 SYS.16을 확인한 경우에만 FRP를 보낸다. JOG 버튼을 놓으면
기존 정상 정지 경로 `STP<axis>/0`을 사용한다.

motor record는 JOG 중 dial 위치가 soft limit의 약 1초 이동거리 안에 들어오면
LVIO를 설정하고 STOP을 요청한다. 드라이버의 검사는 잘못된 방향으로 출발하는 것을
막는 추가 방어이며, polling/통신/감속 거리 때문에 soft limit을 물리 안전장치로
간주하면 안 된다.

검증 결과:

- 전체 C++ 빌드 성공 및 FRP 생성/0속도/방향별 리미트 단위시험 성공
- Python 설정 test 11개 성공
- mock TCP에서 `FRP1/0/0` 수신 후 JOG 해제 시 추가 `STP1/0` 수신 확인
- FRP 전에 fresh 상태 조회, SYS.16 확인과 WTB0 갱신 확인
- 기존 MOVE/HOME/EMG/진단 통합시험 유지
- production TCP/controller와 실제 모터는 계속 비활성

## 2026-08-04: Model 3 좌표 설정(WRP) 연결

`KohzuAriesLynxAxis::setPosition()`을 ARIES Current Position Write인 WRP에
연결했다. 입력은 Model 3 raw pulse이며 signed 28-bit 범위를 검사하고 한 번
반올림하여 `WRP<axis>/<pulse>`를 생성한다.

처리 순서는 다음과 같다.

1. 유효 축 및 pulse 범위 확인
2. fresh RDP/STR/ROG로 축 정지와 물리 EMG 해제 확인
3. WRP 전송
4. 즉시 RDP를 읽어 요청 pulse와 일치하는지 검증
5. 성공 또는 차단 이유를 축별 `PositionStatus` PV에 기록

좌표 설정은 실제 이동이 아니므로 기존 raw HLM/LLM 범위로 새 좌표를 거부하지
않는다. motor record는 SET 모드에서 DVAL/RVAL write를 hardware position load로
처리하며, 쓰는 field와 FOFF 설정에 따라 VAL, OFF와 사용자 soft limit도 함께
조정한다. 따라서 GUI가 WRP를 직접 보내지 않고 motor record SET 절차를 사용하고,
완료 뒤 RBV/VAL/DVAL/RVAL/OFF/HLM/LLM을 확인해야 한다.

WRP는 좌표 레지스터만 임의 값으로 바꾸며 원점 검색 완료나 homed 의미를 부여하지
않는다. 센서가 없는 축의 현재 위치를 공식 원점으로 확정하는 프로젝트 절차에는
계속 Origin Method 10과 ORG를 사용한다.

검증 결과:

- C++ 빌드와 WRP 생성 범위/반올림 단위시험 성공
- Python 설정 test 11개 성공
- mock motor record에서 `SET=1`, `DVAL=250` write 시 `WRP1/250` 확인
- WRP 직후 RDP 250 readback 검증 및 `PositionStatus` 확인
- 기존 MOVE/JOG/HOME/STOP/EMG 통합시험 유지
- production TCP/controller와 실제 모터는 계속 비활성

## 2026-08-04: 검증된 5축 모델의 guarded IOC 적용 도구

`tools/stage_config_apply.py`를 추가했다. 기본 모드는 Channel Access를 사용하지 않고
1~5축 적용 계획만 출력한다. 실제 write는 `--apply`를 명시해야 하며 다음 조건을
모두 만족해야 한다.

- 모든 대상 축 `_able=1(Disable)`, `DMOV=1`, `MOVN=0`, `DISP=1`
- 첫 write 전에 전 축 preflight 완료
- `_able`과 SDIS를 유지하여 motor record processing 차단
- 설정 접근 동안만 DISP=0, 종료 또는 예외 시 반드시 DISP=1 복원
- 모델 field와 OriginMethod 설정 각각 write 후 readback 비교
- 적용 완료 후에도 축 Enable PV는 쓰지 않음

모델이 할당됐지만 `enabled=false`인 축도 commissioning 준비값은 적용 대상이다.
enabled는 별도 운영 승인 상태이며 이 도구가 변경하지 않는다. 현재 계획은 다음을
확인했다.

- 축 1 XA05A-L202: MRES 0.0005 mm, LLM/HLM -24.5/+24.5, mask 712, Method 4
- 축 2 XA05A-R201: MRES 0.0005 mm, LLM/HLM -7.35/+7.35, mask 712, Method 4
- 축 3 ZA05A-W101: MRES 0.00025 mm, LLM/HLM -3.92/+3.92, mask 512, Method 10
- 축 4 SA05A-R2B01: MRES 0.000637 deg, LLM/HLM -3.429608/+3.429608, mask 712, Method 4
- 축 5 RA04A-W01: MRES 0.002 deg, LLM/HLM +5.214/+352.134, mask 704, Method 8

검증 결과 C++ 전체 빌드, 기존 통합시험 및 Python test 14개가 통과했다. preflight
실패 시 write 0건, 정상 적용에서도 enable PV write가 없고 DISP가 복원됨을 단위시험
했다. production IOC가 비활성이라 실제 `--apply`는 실행하지 않았다.

## 2026-08-04: guarded 적용의 Channel Access 통합시험

`tests/mock_stage_apply_ioc.cmd`와 `tests/run_stage_apply_integration.sh`를 추가했다.
production 주소 대신 loopback `127.0.0.1:22322`와 `MOCK:` PV만 사용한다.

시험은 simulator와 32축 IOC를 시작하고 모든 record를 Disable한 다음,
`stage_config_apply.py --apply`를 실제 caget/caput 경로로 실행한다. 5축의 대표
MRES/LLM/HLM/EGU, 축 3·5 OriginMethod 수락값, 전 축 `_able=1`과 `DISP=1`을
readback으로 확인한다.

통합시험은 통과했으며 설정 적용 중 simulator에는 polling 외 WRP, APS, RPS, FRP,
ORG, WTB, WSY, STP, REM이 전혀 전송되지 않았다. 기존 MOVE/JOG/HOME/STOP/EMG
통합시험도 다시 통과했다. production IOC에는 어떤 설정도 적용하지 않았다.

## 2026-08-04: 축별 commissioning 상태와 guarded Enable

32축 commissioning template을 추가했다. 각 축은 ConfigApplied, DirectionVerified,
SensorsVerified, LimitsVerified, HomeEstablished 상태를 가지며 Ready는 이 값과
DMOV=1, MOVN=0을 결합한다.

EnableRequest는 요청 시 Ready와 정지 상태를 다시 읽어 모두 참일 때만
`_able=0(Enable)`을 출력하고, 부족하면 Disable을 유지한다. DisableRequest는 언제나
`_able=1`을 출력한다. 두 요청은 NPP reset record를 통해 Idle로 자동 복귀한다.
모델 적용 도구는 재적용 전 확인값을 모두 지우고 성공한 축의 ConfigApplied만 1로
설정한다.

CA 통합시험에서 불완전 상태의 Enable 차단, 완전한 mock 확인 상태의 Enable 허용,
무조건 Disable 및 DISP 복원을 확인했다. 전 과정의 ARIES write/motion/stop 명령은
0건이며 production 5축 상태는 변경하지 않았다. 직접 `_able` write를 막는 access
security는 아직 적용하지 않았으므로 공식 GUI/Ophyd 인터페이스에서는 숨긴다.

## 2026-08-06: 미사용 축별 PV 제거와 개발용 PV 분류

현재 정책에서 사용되지 않는 `OriginMethodMaskConfig`, `AllowedHomeMethods` PV와 대응
asyn parameter를 제거했다. 과거 절의 mask 및 GUI 관련 내용은 당시 구현 이력이며 현재
인터페이스가 아니다. `HomeStatus`, `MoveStatus`, `PositionStatus`는 Codex 개발 진단용,
commissioning 및 `_able/SDIS`는 개발 중 잠금용으로 분류했다. 이들은 최종 운전에
사용하지 않으며 driver/Ophyd 개발 완료 후 DB 로드에서 주석 처리한다.

## 2026-08-04: `_able` 직접 Channel Access write 차단

처음에는 IOC 초기화 전 dbpf로 기존 `_able.ASG`를 변경하려 했으나 통합시험에서
직접 caput이 허용되어 이 접근을 폐기했다. 대신 motor-R7-3-1의 asyn motor record
구조를 따르는 project-local `kohzuAsynMotor.template`을 만들고 `_able` 생성 시
`ASG=KOHZU_INTERNAL_ENABLE`을 정적으로 설정했다.

access security 파일은 DEFAULT PV의 기존 read/write를 유지하고 내부 enable group에는
read rule만 제공한다. `asSetFilename()`으로 iocInit 전에 로드한다. 따라서 외부 CA는
상태를 읽을 수 있지만 `_able`을 직접 변경할 수 없고, IOC 내부 DB link인 guarded
EnableAction/DisableAction은 영향을 받지 않는다.

검증 결과:

- 직접 CA `caput _able=0`이 write-access 오류로 실패하고 Disable 값 유지
- 확인 미완료 EnableRequest 차단
- 확인 완료·정지 상태 EnableRequest는 내부 link로 Enable 성공
- DisableRequest는 내부 link로 다시 Disable 및 DISP 복원
- 기존 MOVE/JOG/HOME/STOP/EMG 통합시험 재통과
- C++ build, protocol test 및 Python test 14개 통과
- 실제 production IOC와 장비에는 변경 적용 없음

보호 범위는 현재 Channel Access다. 다른 network protocol로 PV를 공개할 경우 해당
server의 인증·권한 정책을 별도로 검토해야 한다.

## 2026-08-04: localhost 동적 축 패널 GUI 기반

설치 환경을 확인한 결과 PyDM/PyQt/PySide/tkinter는 없고 Phoebus 4.7.4가 존재했다.
별도 package 설치 없이 실제 실행 가능한 동적 UI를 위해 Python 표준 HTTP server와
HTML/JavaScript frontend를 추가했다.

GUI는 1~32축과 catalog 모델을 선택해 panel을 생성·삭제하고, 중복 축을 막으며 선택
모델과 assignment가 다르면 경고한다. panel 삭제는 IOC record나 asyn axis를 변경하지
않는다. backend는 고정 status PV allowlist만 읽는다.

write allowlist는 Commissioning:EnableRequest와 DisableRequest뿐이다. server는
127.0.0.1 이외 bind를 거부하고, write POST에는 실행마다 새로 생성되는 same-origin
token을 요구한다. raw `_able`, MOVE/JOG/HOME/WRP/recovery/controller write endpoint는
존재하지 않는다.

검증 결과:

- Python/JavaScript 구문 검사와 Python test 17개 통과
- HTTP config에서 5모델과 32축 확인
- 모의 CA axis status 조회 성공
- 잘못된 write token 403, `/move` endpoint 404
- commissioning 미완료 HTTP Enable 요청이 IOC에서 차단
- ARIES write/motion/stop 명령 0건
- production IOC 및 실제 장비 미사용

## 2026-08-04: GUI controller 진단과 guarded recovery

GUI에 마지막 오류/경고의 번호, 설명, 명령, 원문과 전체 EMG/복구 상태를 표시하는
controller 진단 panel을 추가했다. CHAR waveform은 caget `-S`로 읽어 byte 배열이
아니라 사람이 읽을 수 있는 문자열로 JSON에 전달한다.

write API에는 token-protected `release-emg`와 `refresh-axes`만 추가했다. frontend는
두 요청 모두 확인 대화상자를 표시한다. backend는 각각 기존 Recovery:ReleaseEMG와
Recovery:RefreshAxes PV만 쓰며 REM/RAX protocol을 직접 만들지 않는다.

통합시험 결과:

- 비동기 error 5와 warning 52의 번호·설명·명령·원문 조회
- 전체 EMG Active 표시
- 물리 EMG가 남은 mock에서 Release 요청 후 driver 차단 설명 확인
- 위 경우 ARIES REM 전송 0건
- 명시적 RefreshAxes 요청에서만 추가 RAX 1건
- RAX 후 축 map 검토와 재HOME 안내 확인
- 잘못된 token 및 존재하지 않는 move API 기존 차단 유지
- Python/JavaScript 검사와 Python test 17개 통과

## 2026-08-04: GUI OriginMethod 선택과 운용 중 재HOME

축 panel에 `AllowedHomeMethods` 기반 선택 상자와 적용 버튼을 추가했다. backend는 화면
값을 신뢰하지 않고 현재 허용 목록을 다시 읽으며, 선택값이 1~15 및 허용 mask에
포함되는지 확인한다. 적용할 때는 DisableRequest, HomeEstablished=0, OriginMethod
순서로 써서 방법 변경 뒤 이전 원점 확인 상태로 운전할 수 없게 했다. SYS.2는 선택 시
쓰지 않고 실제 HOME 직전 driver의 기존 WSY/RSY preflight에서만 적용한다.

HOME 버튼은 이미 commissioning을 마친 축의 운용 중 재HOME으로 범위를 제한했다.
backend가 요청 시점의 Commissioning:Ready=1과 `_able=0`(Enable)을 모두 확인한 뒤에만
HOMF를 쓴다. 따라서 최초 HOME을 위해 Ready 검사를 우회하지 않으며, 그 절차는 다음
단계의 별도 commissioning 상태 기계로 남겼다.

검증 결과:

- Python test 18개 및 Python/JavaScript 구문 검사 통과
- commissioning 미완료 HOME은 HTTP 502, ORG 전송 0건
- Method 10 선택 시 축 Disable 및 HomeEstablished=0 확인
- 다섯 확인 항목 설정과 guarded Enable 뒤 HOME 성공
- HOME 중 RSY/WSY/RSY 확인 후 `ORG1/0/1` 정확히 1회 전송
- GUI 시험 중 WRP/APS/RPS/FRP/WTB/REM 전송 없음
- production IOC와 실제 장비에는 변경 적용 없음

## 2026-08-04: 최초 HOME commissioning 상태 기계

정상 `Ready`에는 HomeEstablished가 필요하므로 최초 HOME만을 위한 별도 IOC 상태
기계를 추가했다. `InitialHomeReady`는 ConfigApplied, DirectionVerified,
SensorsVerified, LimitsVerified, HomeEstablished=0, DMOV=1, MOVN=0 및 `_able=1`
(Disable)을 요구한다. 요청 시 이 조건을 다시 검사해 통과한 축만 임시 Enable하고
motor record HOMF를 처리한다. 외부 클라이언트는 raw `_able`이나 controller 명령을
직접 쓰지 않는다.

완료는 `MSTA`의 RA_HOMED(bit 14)로 검출하고 자동 Disable한다. driver는 요청 전 cached
homed bit를 0으로 만들며, 움직이는 Method는 ROG=0을 관측한 뒤의 ROG=1만 새 완료로
인정한다. Method 10은 이동하지 않으므로 다음 fresh ROG=1을 인정한다. 완료가
HomeEstablished를 자동 설정하지는 않으므로 사용자가 실제 위치를 확인해야 한다.
취소 요청은 `STP<axis>/0` 정상 감속 정지 후 Disable 및 내부 상태 초기화를 수행한다.

GUI에는 최초 HOME과 취소 버튼, InitialHomeReady/Active/Issued 표시를 추가했다.
통합시험에서 Method 10 최초 HOME과 자동 Disable, HomeEstablished=0 유지, 사용자 확인
후 guarded Enable 및 운용 중 재HOME을 순서대로 검증했다. `ORG1/0/1`은 두 HOME에서
각각 한 번씩 총 2회 전송됐다. C++ 전체 빌드, Python test 18개, JavaScript/Python
구문 검사와 local mock GUI 통합시험이 통과했으며 production IOC와 실제 장비는
사용하지 않았다.

## 2026-08-04: GUI commissioning 사용자 확인

축 panel에 방향, 센서, 리미트, 원점의 확인·취소 UI를 추가했다. ConfigApplied는 사용자
확인에서 제외하여 guarded stage configuration apply가 성공한 경우에만 설정되도록
유지했다. backend는 고정된 네 이름과 boolean 값만 받고, 승인 전에 ConfigApplied=1,
DMOV=1, MOVN=0, `_able=1` 및 InitialHomeActive=0을 다시 확인한다. 취소는 확인값을
지우기 전에 축을 Disable한다.

stale controller homed 상태의 재사용을 막기 위해 `InitialHomeSucceeded` 내부 latch를
추가했다. 최초 HOME 요청 때 이전 값을 지우고 fresh 완료 뒤에만 1로 설정한다.
HomeEstablished 승인은 이 latch와 MSTA.RA_HOMED가 모두 1이어야 한다. Origin Method
변경과 모델 재적용은 `InvalidateHomeRequest`를 통해 HomeEstablished와 이 latch를
함께 지운다.

검증 결과:

- C++ build 및 Python/JavaScript 구문 검사 통과
- Python unit test 20개 통과
- 오래된 MSTA homed bit만 존재할 때 HomeEstablished 승인 HTTP 502
- 최초 Method 10 HOME 완료 뒤 InitialHomeSucceeded=1 및 원점 승인 성공
- 방향 확인 취소 시 `_able=1` Disable 및 DirectionVerified=0 확인
- Origin Method 선택과 모델 재적용에서 HOME 근거 무효화 확인
- GUI mock 통합시험과 guarded stage-apply CA 통합시험 통과
- production IOC와 실제 장비에는 변경 적용 없음

## 2026-08-04: HOME 기능 단순화

앞 단계에서 HOME에 센서 기반 Method mask, 최초 HOME 상태 기계, fresh homed latch와
자동 Disable까지 한꺼번에 결합했으나 프로젝트 초기 범위에 비해 복잡하다고 판단하여
현재 구현에서 제거했다. 앞의 관련 절은 당시 구현 이력이며 이 절의 정책으로
대체되었다.

현재 HOME 정책은 다음과 같다.

- 사용자가 ARIES/LYNX Method 1~15 중 하나를 직접 선택
- 센서 inventory는 참고 정보이며 validator, GUI, driver가 Method를 제한하지 않음
- 선택 시 축 Disable 및 선택적인 HomeEstablished 확인 무효화
- HOME 시 controller SYS.2를 선택값으로 WSY/RSY 확인한 뒤 ORG 전송
- 이동하는 Method는 기존 speed table 0 및 SYS.16 검증 유지
- 축 정지와 물리 EMG 확인 유지
- 별도 InitialHomeRequest/CancelInitialHome 상태 기계 제거
- HomeEstablished는 Enable을 막지 않는 선택적인 사용자 확인

`Commissioning:Ready`는 ConfigApplied, DirectionVerified, SensorsVerified,
LimitsVerified, DMOV=1, MOVN=0으로 단순화했다. GUI는 항상 Method 1~15를 표시하고
단일 HOME 버튼만 제공한다. legacy OriginMethodMaskConfig는 기존 startup 호환을 위해
남지만 driver는 값을 강제 제한에 사용하지 않으며 AllowedHomeMethods는 1~15를
표시한다. stage configuration apply와 production 초기화 명령에서는 mask write를
제거했다.

검증 결과 C++ build, Python unit test 19개, Python/JavaScript 구문 검사, driver TCP
mock, GUI mock 및 guarded stage-apply 통합시험이 모두 통과했다. GUI 시험에서 기존
advisory mask에 없던 Method 1 선택이 수락되고 Method 10 HOME의 ORG가 정확히 한 번
전송됨을 확인했다. production IOC와 실제 장비는 사용하지 않았다.

## 2026-08-04: 실제 controller raw TCP 읽기 확인

사용자가 제공한 `10.1.101.51:12321`에 TCP 연결한 뒤 설정을 변경하지 않는 read
명령만 실행했다. IDN은 `ARIES 1 4 4`, RAX는 device 6, controllable axis 6 및
`11111100`을 반환했다. 이는 Motionnet axis device 1~6을 뜻하며 사용자가 확인한 실제
모터 스테이지 축 1 연결과 구분한다.

축 1은 RDP=56000 pulse, STR=`0,0,0,0,0,0`, ROG=0이었다. 즉 정지, EMG 및 모든 센서
입력 OFF, controller soft-limit 내부, origin return 미완료다. 현재 controller 기본값은
SYS.2 Method 4와 SYS.16 50000 pulse/s로 확인됐다.

production `st.cmd`의 주소 예시는 실제 endpoint로 바꿨지만 controller 및 database
생성 줄은 계속 주석 상태다. Enable, HOME, MOVE, JOG, STOP, WRP, WSY, WTB, REM은
실행하지 않았다. 원문 응답과 다음 제한 범위는 `docs/07-real-controller-commissioning.md`
에 기록했다.

motor record와 write PV를 전혀 로드하지 않는 `readOnlyHardware.cmd`를 추가해 실제
driver 경로도 시험했다. controller는 ARIES 1 4 4, detected axis 6으로 인식됐고 축 1은
position 56000, stopped, not homed, limit/EMG OFF로 raw TCP 결과와 일치했다. 축 2~6은
CW/CCW limit가 동시에 ON이므로 미연결 스테이지의 미사용 입력으로 취급하고 다음 실제
동작 시험을 축 1로 제한한다. read-only IOC는 2.2초 뒤 정상 종료했으며 write 명령과
motor record는 사용하지 않았다.

## 2026-08-11: 이상적 고정점 endpoint 기구 계산

`X -> Y -> Z -> Pitch -> Yaw` 적층 스테이지에서 Yaw 표면 기준 임의의 점을 고정하기
위한 최초 계산 모듈을 추가했다. 실제 장비에서 확인한 `+X=앞`, `+Y=오른쪽`,
`+Z=위`, `+Pitch=앞쪽 상승`, `+Yaw=위에서 시계방향`을 사용한다. 사용자 병진 방향은
왼손 좌표이므로 내부 계산은 `Xc=X`, `Yc=-Y`, `Zc=Z`의 오른손 좌표로 변환한다.

공식 도면에서 얻은 Pitch/Yaw 공통 회전축 교차점과 Yaw 테이블 표면 중심 사이의 명목
거리 `38 mm`를 immutable geometry 기본값으로 사용한다. 적층 순서와 실제 회전 부호를
반영한 회전은 `Ry(-Pitch) * Rz(-Yaw)`다.

새 `kohzu_kinematics` 패키지는 다음 기능을 제공한다.

- Yaw 표면 사용자 좌표와 내부 계산 좌표 사이의 변환
- 현재 5축 pose에서 고정점의 실험실 위치를 구하는 순기구학
- 목표 Pitch/Yaw에서 같은 점을 유지할 X/Y/Z 절대 endpoint 계산
- 계산 전후 residual과 선택적 public EPICS 소프트 리미트 판정
- 유한값, geometry와 limit 입력 검증

이 모듈은 EPICS/Ophyd를 import하지 않고 IOC, controller, Enable, HOME, STOP 및 이동
PV에 접근하지 않는다. 축 부호, Yaw 축상 점, 38 mm Pitch lever arm, 임의 자세 residual,
왕복 복귀, 사용자 Y 방향 limit 판정과 invalid input을 포함한 새 단위시험 15개가
통과했다. 기존 시험을 포함해 `kohzu-bluesky` 환경의 Python 단위시험 38개가 모두
통과했다. 상세 이론과 다음 궤적 sampling 단계는
`docs/10-fixed-point-kinematics.md`에 기록했다.

## 2026-08-11: 고정점 궤적 sampling과 dry-run 보고

endpoint 기구 계산 위에 실제 장비와 분리된 `kohzu_kinematics/trajectory.py`를
추가했다. 현재 Pitch/Yaw에서 목표 Pitch/Yaw까지 joint-space 선형 보간하고, 각
sample에서 같은 실험실 고정점을 유지하는 X/Y/Z 절대 위치를 계산한다. `N`개 구간은
양 끝을 포함한 `N+1`개 sample을 만든다.

경로 전체에서 다음 진단값을 계산한다.

- 모든 sample의 고정점 residual과 최대 residual
- public EPICS 좌표의 축별 LLM/HLM 및 최초 실패 sample/축
- 시작 자세 대비 축별 최대 absolute excursion
- sample 간 유한차분 속도와 가속도의 축별 최대 절대값
- `collision_checked=false`

속도와 가속도는 controller-ready profile이 아닌 sample 유한차분이다. 시작 전과 종료
후의 속도 불연속은 포함하지 않으며 dry-run 보고서에 이를 명시한다. 보고서는
`NO HARDWARE WRITES`, 경로 종류, duration/sample 수, 목표 pose, residual, limit 결과와
충돌 미검사를 사람이 검토할 수 있는 텍스트로 출력한다.

궤적 endpoint, 선형 각도, 모든 sample의 residual, 시작 자세 보존, 속도·가속도,
limit 통과/최초 실패, 빈 limit, 보고서와 invalid duration/interval을 검증하는 새 시험
14개가 통과했다. 단계 A와 B의 기구 시험은 29개이며 기존 시험을 합친 전체 Python
단위시험 52개가 `kohzu-bluesky` 환경에서 통과했다. 실제 IOC와 controller에는
연결하거나 쓰지 않았다.

## 2026-08-12: 5축 read-only snapshot과 dry-run preflight

고정점 계산이 임의 입력값이 아니라 IOC의 현재 5축 상태를 사용할 수 있도록
`kohzu_kinematics/snapshot.py`와 `tools/fixed_point_dry_run.py`를 추가했다. reader는
축 1~5의 `RBV/DMOV/MOVN/HLS/LLS/LVIO/LLM/HLM`과 controller EMG 상태만 고정
allowlist로 읽으며 caput이나 write adapter를 제공하지 않는다.

snapshot은 모든 PV 존재, 유한값, alarm, binary 상태와 freshness를 확인한다. 이후
EMG 해제, 다섯 축 `DMOV=1/MOVN=0`, hardware limit와 LVIO 해제를 모두 만족해야만
단계 B 궤적 dry-run을 계산한다. 실패 조건은 계산 전에 전체 거부한다.

Disable 상태에서 한 번도 process되지 않은 passive motor record는 timestamp가
`<undefined>`일 수 있다. server timestamp가 정의된 PV에는 실제 timestamp age를
적용하고, undefined인 경우 synchronous CA get 완료 시각을 observation timestamp로
사용한다. 결과에는 `server_timestamps_complete=false`를 표시한다. 실제 다축 이동
승인 전에는 driver polling generation 또는 별도 snapshot timestamp를 추가해 이 계약을
강화해야 한다.

전용 `FIXED:` mock IOC와 loopback simulator 통합시험을 추가했다. 실제 축 5 IOC는
사용자 승인에 따라 먼저 Disable, `DMOV=1`, `MOVN=0`을 확인한 뒤 종료했다. mock의
다섯 축은 계속 Disable이었고 dry-run은 전 sample soft limit PASS와 residual 0을
보고했다. simulator 로그에서 WSY/ORG/APS/RPS/FRP/WTB/STP/WRP/REM은 모두 0건이었다.
실제 IOC는 시험 후 재시작하지 않았다.

## 2026-08-12: 32축 통합 IOC를 5축 운전 IOC로 전환

축마다 catalog 모델을 선택하는 기존 32축 IOC를 실제 5축 운전에 사용하도록 production
`st.cmd`의 controller 연결, 32개 motor record, 진단·HOME·commissioning DB와 접근
보안을 활성화했다. 모든 motor record는 IOC 시작 시 `Disable`이고, 모델이 지정된
1~5축만 `stage_config_apply.py`의 적용 대상이다. 이 문단의 최초 구현에서는 적용 후에도
Disable을 유지했으나, 아래에 기록한 기본 end-to-end 프로파일에서 적용 성공 후 Enable로
전환하도록 변경했다.

축 5는 육안으로 확인한 X축 평행 작업 원점을 영구 운전 설정으로 반영했다. assignment의
HOME 선택은 Method 10, 운전 소프트 범위는 `-173.786~+173.134 deg`다. Method 8 기반
`axis5HardwareTest.cmd`는 좌표 상실 시 CCW limit를 다시 찾는 복구 전용으로 남겼다.

이후 기본 end-to-end 프로파일은 더 단순해졌다. commissioning DB, Ready flag와 access
security는 기본 IOC에서 사용하지 않고 코드와 문서에 개발 이력으로만 보존한다.
`stage_config_apply.py --apply`는 할당 축을 Disable 상태에서 설정하고 readback을 검증한
뒤 assignment의 `enabled` 값에 따라 최종 `_able` 상태를 정한다. HOME method 선택과 실행은 사용자 책임이며, Bluesky
고정점 실행의 기본 운전 gate도 `_able` 하나다. 이전 commissioning 검사는
`--development-guards`, 실행 안전 실험은 `--safety-checks`에서만 명시적으로 사용한다.

## 2026-08-13: 고정점 실행 정리와 보정 보류

이상적 고정점 모델에 MRES/OFF/DIR 기반 sample 양자화를 추가하고, 실제 장비에서
임시 고정점 `(20,0,0) mm`, Pitch/Yaw `0 -> +0.1 -> 0 deg` 왕복 실행을 완료했다.
각 방향은 현재 snapshot에서 독립적으로 계산했고 OFF/FOFF는 변경하지 않았다. 양자화
후 같은 pulse가 연속되는 sample은 건너뛰며 달라진 축만 Ophyd/Bluesky로 요청한다.

`kohzu-bluesky` 환경에 pytest를 설치하여 전체 결과 `103 passed, 7 subtests passed`를
확인했다. 기본 실행에서 불필요하던 `EmergencyActive` 연결은 제거하고
`--safety-checks`에만 남겼다. 실제 축 비직교, 회전축 편심, 적층 높이와 케이스 장착
오차는 측정 도구 또는 카메라 기반 측정 방법이 마련될 때까지 보정값을 추정하지 않고
모두 0인 이상적 모델을 유지한다.

## 2026-08-13: GUI 최소 구조 재구현

기존 commissioning, HOME, 진단과 recovery 화면을 제거하고 축 1~32, catalog 모델 선택,
생성 및 패널 삭제만 제공하는 GUI로 다시 시작했다. 생성 API는 공용 stage-config 적용
코드를 사용해 선택한 한 축의 모델 고유 field를 실제 IOC에 적용하고 readback 성공 후
Enable한다. 설치에 종속되는 DIR과 OriginMethod는 보존하며 이동 명령은 제공하지 않는다.
assignment는 패널 상태의 영속 기준이다. 삭제는 축을 Disable하고 모델 할당을 제거하며,
정상 서버 종료는 모든 패널 축을 Disable하고 모델을 보존한다. 다음 시작은 저장된 모델
축을 다시 적용·Enable하고 패널을 자동 복원한다.

Python 전체 시험은 `102 passed, 7 subtests passed`였고 새 GUI loopback 통합시험에서
축 6 RA04A-W01 적용, 삭제, 다른 모델 재생성, 정상 종료 및 assignment 동기화와
controller motion/write 명령 0건을 확인했다.

저장소 최상위에 `start_kohzu_control.sh`를 추가했다. 이 launcher는 production IOC 시작,
PV 준비 대기, persistent assignment 적용과 GUI 시작을 한 명령으로 수행한다. 종료 시
GUI의 assignment/Disable cleanup을 먼저 완료한 뒤 IOC를 종료하며, 중복 IOC/GUI 실행과
시작 timeout을 거부한다.

최초 launcher 시험에서 기존 빌드 산출물의 RUNPATH가 이전 저장소
`/home/changhui1788/Documents/codex-EPICS-control-test`를 가리켜 TOP 불일치 경고가
발생했고, sudo가 현재 shell의 `LD_LIBRARY_PATH`를 제거하면서 `libKohzuAriesLynx.so`를
찾지 못했다. 현재 경로에서 `make clean && make -j2`로 다시 빌드하여 executable RUNPATH와
`envPaths`의 TOP을 `/home/changhui1788/Documents/EPICS-Bluesky-test`로 맞췄다. launcher는
권한이 필요 없는 IOC를 기본적으로 일반 사용자로 실행하고 `--sudo`를 opt-in으로 바꿨다.

GUI 축 패널에 RBV/EGU, Enable, MOVN/DMOV, HLS/LLS/LVIO, LLM/HLM, VELO/VMAX,
DIR/MRES와 OriginMethod의 read-only 표시를 추가했다. 패널 하나당 모든 상태 PV를 한 CA
호출로 읽고 브라우저에서 1초마다 갱신한다. 이동, STOP, 속도 변경과 HOME write는 아직
추가하지 않았다.

GUI 전체에 간편/기본/상세 보기 전환을 추가하고 선택을 browser localStorage에 보존했다.
간편 모드는 모바일에서 5~6축을 한 화면에 배치할 수 있는 축당 한 줄 구조이며
CCW/STOP/CW 자리를 미리 배치했지만 아직 비활성이다. 기본 모드는 일반 상태를, 상세
모드는 VAL/RBV, DVAL/DRBV, RVAL/RRBV, OFF/FOFF, VBAS/ACCL, MSTA와 기존 변환·원점
정보를 표시한다. 확장된 상태도 panel당 단일 CA 호출로 읽는다.

## 2026-08-14: runtime 설정 중앙화

운영 기본값을 `config/runtime.ini`로 모았다. controller host/port, EPICS prefix와 command
경로 및 CA address list, GUI listen/port, Python 실행 파일을 launcher와 GUI,
stage-config 및 fixed-point 도구가 같은 loader로 읽는다. launcher는 값을 IOC 환경
macro에도 전달하여 production `st.cmd`의 controller endpoint, prefix와 DB macro가 같은
설정을 사용한다. 명령행 인자는 특정 실행에 한해 기본값을 덮어쓸 수 있다.

GUI의 loopback 전용 제한은 제거했으며 기본값은 여전히 `127.0.0.1`이다. LAN IP 또는
`0.0.0.0` bind가 가능하지만 현재 사용자 인증과 TLS가 없으므로 non-loopback에서는
신뢰 네트워크 전용이라는 경고를 출력한다. tests의 loopback endpoint와 과거 축별
hardware-test `.cmd`는 운영 설정이 아니라 격리 fixture와 시험 기록이므로 변경하지
않았다.
