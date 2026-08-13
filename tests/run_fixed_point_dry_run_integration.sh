#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
server_log="$(mktemp)"
ioc_log="$(mktemp)"
report_log="$(mktemp)"

cleanup() {
    for test_pid in "${fixed_ioc_pid:-}" "${fixed_server_pid:-}"; do
        if [[ -n "${test_pid}" ]]; then
            kill "${test_pid}" 2>/dev/null || true
            wait "${test_pid}" 2>/dev/null || true
        fi
    done
    rm -f "${server_log}" "${ioc_log}" "${report_log}"
}
trap cleanup EXIT

python3 "${project_dir}/tests/mock_aries_server.py" \
    --port 22324 --emergency-axis 0 >"${server_log}" 2>&1 &
fixed_server_pid=$!
sleep 0.2

cd "${project_dir}/tests"
"${project_dir}/bin/linux-x86_64/kohzuAriesLynx" \
    mock_fixed_point_ioc.cmd >"${ioc_log}" 2>&1 &
fixed_ioc_pid=$!

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
ready=0
for _ in {1..80}; do
    if [[ "$("${epics_bin}/caget" -t -n FIXED:m5.DMOV 2>/dev/null || true)" == "1" ]]; then
        ready=1
        break
    fi
    sleep 0.1
done
if [[ "${ready}" -ne 1 ]]; then
    cat "${ioc_log}" >&2
    exit 1
fi

# Allow one additional polling cycle so every dynamic field has a fresh
# server timestamp before the strict snapshot age check.
sleep 0.3
cd "${project_dir}"
python3 tools/fixed_point_dry_run.py \
    --prefix FIXED: --fixed-x 2 --fixed-y 1 --fixed-z 0 \
    --target-pitch 0.2 --target-yaw 0.5 --duration 5 --intervals 10 \
    --maximum-age 5 >"${report_log}"

grep -Fq "NO HARDWARE WRITES" "${report_log}"
grep -Fq "Software limits: PASS at every sample" "${report_log}"
grep -Fq "Collision checked: false" "${report_log}"

# Startup discovery and polling reads are expected. No controller setting,
# motion, stop, coordinate, HOME, recovery or speed-table write is allowed.
if grep -Eq "RECEIVED (WSY|ORG|APS|RPS|FRP|WTB|STP|WRP|REM)" "${server_log}"; then
    cat "${server_log}" >&2
    exit 1
fi

for axis in {1..5}; do
    [[ "$("${epics_bin}/caget" -t -n "FIXED:m${axis}_able")" == "1" ]]
done

cat "${report_log}"
echo "Fixed-point read-only snapshot integration test passed"
