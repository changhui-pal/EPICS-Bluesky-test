#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
server_log="$(mktemp)"
ioc_log="$(mktemp)"

cleanup() {
    if [[ -n "${apply_ioc_pid:-}" ]]; then
        kill "${apply_ioc_pid}" 2>/dev/null || true
        wait "${apply_ioc_pid}" 2>/dev/null || true
    fi
    if [[ -n "${apply_server_pid:-}" ]]; then
        kill "${apply_server_pid}" 2>/dev/null || true
        wait "${apply_server_pid}" 2>/dev/null || true
    fi
    rm -f "${server_log}" "${ioc_log}"
}
trap cleanup EXIT

python3 "${project_dir}/tests/mock_aries_server.py" \
    --port 22322 >"${server_log}" 2>&1 &
apply_server_pid=$!
sleep 0.2

if ! kill -0 "${apply_server_pid}" 2>/dev/null; then
    cat "${server_log}" >&2
    exit 1
fi

cd "${project_dir}/tests"
"${project_dir}/bin/linux-x86_64/kohzuAriesLynx" \
    mock_stage_apply_ioc.cmd >"${ioc_log}" 2>&1 &
apply_ioc_pid=$!

# Restrict CA discovery to this host and wait until iocInit plus the explicit
# disable command file have completed for all records.
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
ready=0
for _ in {1..50}; do
    if [[ "$("${epics_bin}/caget" -t -n MOCK:m5_able 2>/dev/null || true)" == "1" ]]; then
        ready=1
        break
    fi
    sleep 0.1
done
if [[ "${ready}" -ne 1 ]]; then
    printf 'Mock apply IOC did not reach the disabled state.\n' >&2
    cat "${ioc_log}" >&2
    exit 1
fi

cd "${project_dir}"
apply_output="$(python3 tools/stage_config_apply.py \
    --prefix MOCK: --epics-bin "${epics_bin}" --apply 2>&1)"
if ! grep -Fq "Applied 5 axis configurations; all remain DISABLED" \
        <<<"${apply_output}"; then
    printf '%s\n' "${apply_output}" >&2
    exit 1
fi

assert_pv() {
    local pv="$1"
    local expected="$2"
    local actual
    actual="$("${epics_bin}/caget" -t "${pv}")"
    if [[ "${actual}" != "${expected}" ]]; then
        printf '%s expected %s, got %s\n' "${pv}" "${expected}" "${actual}" >&2
        exit 1
    fi
}

# Representative linear, failed-sensor and rotation fields prove that the
# real CA writes used the reviewed five-axis plan rather than test fixtures.
assert_pv MOCK:m1.MRES 0.0005
assert_pv MOCK:m1.LLM -24.5
assert_pv MOCK:m2.HLM 7.35
assert_pv MOCK:m3.MRES 0.00025
assert_pv MOCK:m3:OriginMethodSelectedRBV 10
assert_pv MOCK:m4.EGU deg
assert_pv MOCK:m5.HLM 352.134
assert_pv MOCK:m5:OriginMethodSelectedRBV 8
assert_pv MOCK:m1:Commissioning:ConfigApplied Applied
assert_pv MOCK:m1:Commissioning:DirectionVerified Unverified
assert_pv MOCK:m1:Commissioning:Ready 0

# Direct CA write is the bypass being closed by access security. Read access
# remains available, but caput must fail and leave the record disabled.
if "${epics_bin}/caput" -t MOCK:m1_able 0 >/dev/null 2>&1; then
    printf 'Access security unexpectedly allowed direct _able write.\n' >&2
    exit 1
fi
if [[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" != "1" ]]; then
    printf 'Denied direct _able write changed the record value.\n' >&2
    exit 1
fi

# Simplified Enable requires only a stopped axis; commissioning flags remain
# informational and do not gate normal motor operation.
"${epics_bin}/caput" -t MOCK:m1:Commissioning:EnableRequest 1 >/dev/null
sleep 0.1
if [[ "$("${epics_bin}/caget" -t -n MOCK:m1_able)" != "0" ]]; then
    printf 'Stopped-axis EnableRequest did not enable the motor record.\n' >&2
    exit 1
fi
assert_pv MOCK:m1.DISP 0
assert_pv MOCK:m1:Commissioning:EnableRequest Idle

# Disable is intentionally unconditional. DISP is no longer coupled to the
# software enable state.
"${epics_bin}/caput" -t MOCK:m1:Commissioning:DisableRequest 1 >/dev/null
sleep 0.1
assert_pv MOCK:m1:Commissioning:DisableRequest Idle

for axis in {1..5}; do
    assert_pv "MOCK:m${axis}.DISP" 0
    if [[ "$("${epics_bin}/caget" -t -n "MOCK:m${axis}_able")" != "1" ]]; then
        printf 'Axis %s was unexpectedly enabled.\n' "${axis}" >&2
        exit 1
    fi
done

# Model configuration must remain a record-only operation. Polling commands
# are expected, but no command that writes coordinates/settings or moves/stops
# an ARIES axis may appear.
if grep -Eq "RECEIVED (WRP|APS|RPS|FRP|ORG|WTB|WSY|STP|REM)" "${server_log}"; then
    printf 'Guarded model apply emitted an ARIES write or motion command.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

echo "Guarded stage configuration CA integration test passed"
