#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
server_log="$(mktemp)"
ioc_log="$(mktemp)"
gui_log="$(mktemp)"
axes_file="$(mktemp)"

cleanup() {
    for test_pid in "${gui_pid:-}" "${ioc_pid:-}" "${server_pid:-}"; do
        if [[ -n "${test_pid}" ]]; then
            kill "${test_pid}" 2>/dev/null || true
            wait "${test_pid}" 2>/dev/null || true
        fi
    done
    rm -f "${server_log}" "${ioc_log}" "${gui_log}" "${axes_file}"
}
trap cleanup EXIT

for axis in {1..32}; do
    printf '[axis:%s]\nenabled = false\n' "${axis}" >>"${axes_file}"
done

python3 "${project_dir}/tests/mock_aries_server.py" \
    --port 22322 >"${server_log}" 2>&1 &
server_pid=$!
sleep 0.2

cd "${project_dir}/tests"
"${project_dir}/bin/linux-x86_64/kohzuAriesLynx" \
    mock_stage_apply_ioc.cmd >"${ioc_log}" 2>&1 &
ioc_pid=$!

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
ready=0
for _ in {1..50}; do
    if [[ "$("${epics_bin}/caget" -t -n MOCK:m6_able 2>/dev/null || true)" == "1" ]]; then
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
python3 gui/kohzu_gui_server.py --prefix MOCK: --port 18080 --axes "${axes_file}" \
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
python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v["models"])==5; assert v["axes"]==list(range(1,33)); assert v["prefix"]=="MOCK:"; assert v["panels"]==[]' \
    <<<"${config_json}"
token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"${config_json}")"

bad_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'X-Kohzu-Token: invalid' \
    --header 'Content-Type: application/json' \
    --data '{"axis":6,"model":"RA04A-W01"}' \
    http://127.0.0.1:18080/api/panels)"
[[ "${bad_code}" == "403" ]]

result_file="$(mktemp)"
create_code="$(curl --silent --output "${result_file}" --write-out '%{http_code}' --request POST \
    --header "X-Kohzu-Token: ${token}" \
    --header 'Content-Type: application/json' \
    --data '{"axis":6,"model":"RA04A-W01"}' \
    http://127.0.0.1:18080/api/panels)"
result_json="$(<"${result_file}")"
rm -f "${result_file}"
if [[ "${create_code}" != "200" ]]; then
    printf 'GUI create returned HTTP %s: %s\n' "${create_code}" "${result_json}" >&2
    cat "${gui_log}" >&2
    exit 1
fi
python3 -c 'import json,sys; v=json.load(sys.stdin); assert v=={"axis":6,"model":"RA04A-W01","record":"MOCK:m6","enabled":True}' \
    <<<"${result_json}"

[[ "$("${epics_bin}/caget" -t MOCK:m6.DESC)" == "KOHZU RA04A-W01 Yaw; X-parallel origin" ]]
[[ "$("${epics_bin}/caget" -t MOCK:m6.EGU)" == "deg" ]]
[[ "$("${epics_bin}/caget" -t -g 12 MOCK:m6.MRES)" == "0.002" ]]
[[ "$("${epics_bin}/caget" -t -g 12 MOCK:m6.LLM)" == "-173.786" ]]
[[ "$("${epics_bin}/caget" -t -g 12 MOCK:m6.HLM)" == "173.134" ]]
[[ "$("${epics_bin}/caget" -t -n MOCK:m6_able)" == "0" ]]

status_json="$(curl --silent --fail http://127.0.0.1:18080/api/panels/6/status)"
python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["axis"]==6; s=v["values"]; required=[".RBV",".VAL",".EGU","_able",".MOVN",".DMOV",".HLS",".LLS",".LVIO",".LLM",".HLM",".VELO",".VMAX",".VBAS",".ACCL",".DIR",".MRES",".OFF",".FOFF",".DVAL",".DRBV",".RVAL",".RRBV",".MSTA",":OriginMethodSelectedRBV"]; assert all(k in s for k in required)' \
    <<<"${status_json}"

# A duplicate active panel is rejected.
repeat_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header "X-Kohzu-Token: ${token}" \
    --header 'Content-Type: application/json' \
    --data '{"axis":6,"model":"XA05A-L202"}' \
    http://127.0.0.1:18080/api/panels)"
[[ "${repeat_code}" == "502" ]]

# Delete disables the axis and removes the persistent model assignment.
curl --silent --fail --request DELETE \
    --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/panels/6 >/dev/null
[[ "$("${epics_bin}/caget" -t -n MOCK:m6_able)" == "1" ]]
python3 -c 'import configparser,sys; p=configparser.ConfigParser(); p.read(sys.argv[1]); s=p["axis:6"]; assert s.getboolean("enabled") is False; assert not s.get("model", "")' "${axes_file}"

# The same axis can now be created again with another model.
curl --silent --fail --request POST \
    --header "X-Kohzu-Token: ${token}" \
    --header 'Content-Type: application/json' \
    --data '{"axis":6,"model":"XA05A-L202"}' \
    http://127.0.0.1:18080/api/panels >/dev/null
[[ "$("${epics_bin}/caget" -t -n MOCK:m6_able)" == "0" ]]
python3 -c 'import configparser,sys; p=configparser.ConfigParser(); p.read(sys.argv[1]); s=p["axis:6"]; assert s.getboolean("enabled") is True; assert s["model"]=="XA05A-L202"' "${axes_file}"

# Normal web-server shutdown disables the axis, records enabled=false, and
# preserves the model so the panel can be restored at the next startup.
kill -TERM "${gui_pid}"
wait "${gui_pid}"
gui_pid=""
[[ "$("${epics_bin}/caget" -t -n MOCK:m6_able)" == "1" ]]
python3 -c 'import configparser,sys; p=configparser.ConfigParser(); p.read(sys.argv[1]); s=p["axis:6"]; assert s.getboolean("enabled") is False; assert s["model"]=="XA05A-L202"' "${axes_file}"

if grep -Eq "RECEIVED (WRP|APS|RPS|FRP|ORG|WTB|WSY|STP|REM)" "${server_log}"; then
    cat "${server_log}" >&2
    exit 1
fi

echo "Minimal axis/model GUI integration test passed"
