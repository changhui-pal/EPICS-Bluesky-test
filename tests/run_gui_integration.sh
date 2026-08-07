#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
server_log="$(mktemp)"
ioc_log="$(mktemp)"
gui_log="$(mktemp)"

cleanup() {
    for gui_test_pid in "${gui_pid:-}" "${gui_ioc_pid:-}" "${gui_server_pid:-}"; do
        if [[ -n "${gui_test_pid}" ]]; then
            kill "${gui_test_pid}" 2>/dev/null || true
            wait "${gui_test_pid}" 2>/dev/null || true
        fi
    done
    rm -f "${server_log}" "${ioc_log}" "${gui_log}"
}
trap cleanup EXIT

python3 "${project_dir}/tests/mock_aries_server.py" \
    --port 22322 >"${server_log}" 2>&1 &
gui_server_pid=$!
sleep 0.2

cd "${project_dir}/tests"
"${project_dir}/bin/linux-x86_64/kohzuAriesLynx" \
    mock_stage_apply_ioc.cmd >"${ioc_log}" 2>&1 &
gui_ioc_pid=$!

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
ready=0
for _ in {1..50}; do
    if [[ "$("${epics_bin}/caget" -t -n MOCK:m1_able 2>/dev/null || true)" == "1" ]]; then
        ready=1
        break
    fi
    sleep 0.1
done
if [[ "${ready}" -ne 1 ]]; then
    cat "${ioc_log}" >&2
    exit 1
fi

cd "${project_dir}"
python3 gui/kohzu_gui_server.py --prefix MOCK: --port 18080 \
    >"${gui_log}" 2>&1 &
gui_pid=$!

gui_ready=0
for _ in {1..50}; do
    if curl --silent --fail http://127.0.0.1:18080/api/config >/dev/null; then
        gui_ready=1
        break
    fi
    sleep 0.1
done
if [[ "${gui_ready}" -ne 1 ]]; then
    cat "${gui_log}" >&2
    exit 1
fi

config_json="$(curl --silent --fail http://127.0.0.1:18080/api/config)"
python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v["models"])==5; assert len(v["axes"])==32; assert v["prefix"]=="MOCK:"' \
    <<<"${config_json}"
token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"${config_json}")"

status_json="$(curl --silent --fail http://127.0.0.1:18080/api/axis/1/status)"
python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["axis"]==1; assert ".RBV" in v["values"]; assert ":Commissioning:Ready" in v["values"]' \
    <<<"${status_json}"

diagnostic_json="$(curl --silent --fail http://127.0.0.1:18080/api/diagnostics)"
python3 -c 'import json,sys; v=json.load(sys.stdin)["values"]; assert v["Diag:LastErrorCode"]=="5"; assert "Emergency-stop" in v["Diag:LastErrorText"]; assert v["Recovery:EmergencyActive"]=="Active"' \
    <<<"${diagnostic_json}"

bad_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'X-Kohzu-Token: invalid' \
    http://127.0.0.1:18080/api/axis/1/enable)"
[[ "${bad_code}" == "403" ]]

move_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/axis/1/move)"
[[ "${move_code}" == "404" ]]

# The HTTP write endpoint can only request the IOC's guarded action. Since
# commissioning is incomplete, this request must leave the motor disabled.
curl --silent --fail --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/axis/1/enable >/dev/null
sleep 0.1
[[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" == "1" ]]

# Operational HOME is unavailable before commissioning and Enable.
home_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/axis/1/home)"
[[ "${home_code}" == "502" ]]

# Every documented method is selectable even if the legacy sensor-derived
# advisory mask omitted it. Method 10 is finally used because it sets the
# present position as origin without a search motion.
curl --silent --fail --request POST \
    --header "X-Kohzu-Token: ${token}" --header 'Content-Type: application/json' \
    --data '{"method":1}' \
    http://127.0.0.1:18080/api/axis/1/origin-method >/dev/null
sleep 0.1
[[ "$("${epics_bin}/caget" -t MOCK:m1:OriginMethodSelectedRBV)" == "1" ]]
curl --silent --fail --request POST \
    --header "X-Kohzu-Token: ${token}" --header 'Content-Type: application/json' \
    --data '{"method":10}' \
    http://127.0.0.1:18080/api/axis/1/origin-method >/dev/null
sleep 0.1
[[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" == "1" ]]
[[ "$("${epics_bin}/caget" -t -n MOCK:m1:Commissioning:HomeEstablished)" == "0" ]]

# ConfigApplied remains owned by the configuration tool. The user records the
# other checks; HomeEstablished is optional and does not gate Enable or HOME.
"${epics_bin}/caput" -t MOCK:m1:Commissioning:ConfigApplied 1 >/dev/null
for confirmation in direction sensors limits; do
    curl --silent --fail --request POST \
        --header "X-Kohzu-Token: ${token}" --header 'Content-Type: application/json' \
        --data "{\"name\":\"${confirmation}\",\"verified\":true}" \
        http://127.0.0.1:18080/api/axis/1/confirmation >/dev/null
done
sleep 0.1
[[ "$("${epics_bin}/caget" -t MOCK:m1:Commissioning:Ready)" == "1" ]]
# HOME confirmation remains zero, proving it is not part of the Enable gate.
[[ "$("${epics_bin}/caget" -t -n MOCK:m1:Commissioning:HomeEstablished)" == "0" ]]

curl --silent --fail --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/axis/1/enable >/dev/null
sleep 0.1
[[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" == "0" ]]
curl --silent --fail --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/axis/1/home >/dev/null
sleep 0.3
# Revoking any confirmation is safety-decreasing: it first Disables the axis.
curl --silent --fail --request POST \
    --header "X-Kohzu-Token: ${token}" --header 'Content-Type: application/json' \
    --data '{"name":"direction","verified":false}' \
    http://127.0.0.1:18080/api/axis/1/confirmation >/dev/null
sleep 0.1
[[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" == "1" ]]
[[ "$("${epics_bin}/caget" -t -n MOCK:m1:Commissioning:DirectionVerified)" == "0" ]]

# The mock keeps axis 6 EMG active. HTTP can request release, but the driver
# must reject it locally without transmitting REM to ARIES.
curl --silent --fail --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/recovery/release-emg >/dev/null
sleep 0.2
recovery_json="$(curl --silent --fail http://127.0.0.1:18080/api/diagnostics)"
python3 -c 'import json,sys; assert "physical EMG input remains active" in json.load(sys.stdin)["values"]["Recovery:Status"]' \
    <<<"${recovery_json}"

# RAX is an explicit, token-protected request. It reads the Motionnet map and
# records the re-home warning; it is not part of the forbidden motion writes.
curl --silent --fail --request POST --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/recovery/refresh-axes >/dev/null
sleep 0.2
recovery_json="$(curl --silent --fail http://127.0.0.1:18080/api/diagnostics)"
python3 -c 'import json,sys; assert "verify and re-home" in json.load(sys.stdin)["values"]["Recovery:Status"]' \
    <<<"${recovery_json}"

if grep -Fq "RECEIVED REM" "${server_log}"; then
    printf 'GUI recovery bypassed the driver EMG guard.\n' >&2
    exit 1
fi
if [[ "$(grep -Fc "RECEIVED RAX" "${server_log}")" -ne 2 ]]; then
    printf 'Expected startup RAX and one explicit GUI refresh RAX.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if [[ "$(grep -Fc "RECEIVED ORG1/0/1" "${server_log}")" -ne 1 ]]; then
    printf 'Expected exactly one user-selected HOME.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if grep -Eq "RECEIVED (WRP|APS|RPS|FRP|WTB|STP|REM)" "${server_log}"; then
    cat "${server_log}" >&2
    exit 1
fi

echo "Dynamic local GUI API integration test passed"
