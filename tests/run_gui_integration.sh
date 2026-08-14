#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
python_command="$(python3 "${project_dir}/tools/runtime_config.py" --get python.executable)"
server_log="$(mktemp)"; ioc_log="$(mktemp)"; gui_log="$(mktemp)"; axes_file="$(mktemp)"
cleanup() {
    for test_pid in "${gui_pid:-}" "${ioc_pid:-}" "${server_pid:-}"; do
        [[ -z "${test_pid}" ]] || kill "${test_pid}" 2>/dev/null || true
        [[ -z "${test_pid}" ]] || wait "${test_pid}" 2>/dev/null || true
    done
    rm -f "${server_log}" "${ioc_log}" "${gui_log}" "${axes_file}"
}
trap cleanup EXIT
for axis in {1..32}; do printf '[axis:%s]\nenabled = false\n' "${axis}" >>"${axes_file}"; done

python3 "${project_dir}/tests/mock_aries_server.py" --port 22322 >"${server_log}" 2>&1 & server_pid=$!
sleep 0.2
cd "${project_dir}/tests"
"${project_dir}/bin/linux-x86_64/kohzuAriesLynx" mock_stage_apply_ioc.cmd >"${ioc_log}" 2>&1 & ioc_pid=$!
export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
for _ in {1..50}; do
    [[ "$("${epics_bin}/caget" -t -n MOCK:m6_able 2>/dev/null || true)" == "1" ]] && break
    sleep 0.1
done

cd "${project_dir}"
"${python_command}" gui/kohzu_gui_server.py --prefix MOCK: --port 18080 \
    --move-timeout 8 --axes "${axes_file}" >"${gui_log}" 2>&1 & gui_pid=$!
for _ in {1..80}; do curl --silent --fail http://127.0.0.1:18080/api/config >/dev/null && break; sleep 0.1; done
config_json="$(curl --silent --fail http://127.0.0.1:18080/api/config)"
token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"${config_json}")"

# Lifecycle stays REST; all motor operation endpoints from the legacy server
# must be absent.
bad_code="$(curl --silent --output /dev/null --write-out '%{http_code}' --request POST \
    --header 'X-Kohzu-Token: invalid' --header 'Content-Type: application/json' \
    --data '{"axis":1,"model":"XA05A-L202"}' http://127.0.0.1:18080/api/panels)"
[[ "${bad_code}" == "403" ]]
create_response="$(curl --silent --request POST --header "X-Kohzu-Token: ${token}" \
    --header 'Content-Type: application/json' --data '{"axis":1,"model":"XA05A-L202"}' \
    http://127.0.0.1:18080/api/panels)"
if ! python3 -c 'import json,sys; assert json.load(sys.stdin).get("enabled") is True' <<<"${create_response}"; then
    printf 'Panel create failed: %s\n' "${create_response}" >&2
    cat "${gui_log}" >&2
    exit 1
fi
for endpoint in status move stop jog/start field; do
    code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
        "http://127.0.0.1:18080/api/panels/1/${endpoint}")"
    [[ "${code}" == "404" ]]
done

coordinate_before="$("${epics_bin}/caget" -t -g 12 MOCK:m1.OFF MOCK:m1.LLM MOCK:m1.HLM)"
"${python_command}" tests/gui_ws_client.py -- ws://127.0.0.1:18080/ws "${token}"
coordinate_after="$("${epics_bin}/caget" -t -g 12 MOCK:m1.OFF MOCK:m1.LLM MOCK:m1.HLM)"
[[ "${coordinate_before}" == "${coordinate_after}" ]]
[[ "$("${epics_bin}/caget" -t -g 12 MOCK:m1.VELO)" == "0.25" ]]

curl --silent --fail --request DELETE --header "X-Kohzu-Token: ${token}" \
    http://127.0.0.1:18080/api/panels/1 >/dev/null
[[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" == "1" ]]
python3 -c 'import configparser,sys; p=configparser.ConfigParser(); p.read(sys.argv[1]); assert not p["axis:1"].get("model", ""); assert not p["axis:1"].getboolean("enabled")' "${axes_file}"

kill -TERM "${gui_pid}"
wait "${gui_pid}" || true
gui_pid=""
[[ "$(grep -c '^RECEIVED FRP1/0/0$' "${server_log}" || true)" == "1" ]]
if grep -Eq 'GET /api/panels/.+/(status|move|jog|field)' "${gui_log}"; then exit 1; fi
echo "Persistent Ophyd/WebSocket GUI integration test passed"
