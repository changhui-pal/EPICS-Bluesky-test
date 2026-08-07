#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
server_log="$(mktemp)"

# Always terminate the simulator and remove its temporary output, including
# when the IOC or an assertion fails.
cleanup() {
    if [[ -n "${server_pid:-}" ]]; then
        kill "${server_pid}" 2>/dev/null || true
        wait "${server_pid}" 2>/dev/null || true
    fi
    rm -f "${server_log}"
}
trap cleanup EXIT

python3 "${project_dir}/tests/mock_aries_server.py" >"${server_log}" 2>&1 &
server_pid=$!

# The simulator binds immediately; this short delay avoids racing the IOC's
# first connect without probing the single-client port and consuming it.
sleep 0.2
if ! kill -0 "${server_pid}" 2>/dev/null; then
    cat "${server_log}"
    exit 1
fi

cd "${project_dir}/tests"
ioc_output="$("${project_dir}/bin/linux-x86_64/kohzuAriesLynx" mock_ioc.cmd 2>&1)"

# Report the missing expectation and preserve the complete IOC diagnostics on
# failure.  This makes protocol and EPICS record regressions distinguishable.
assert_ioc_output() {
    local expected="$1"
    if ! grep -Fq "${expected}" <<<"${ioc_output}"; then
        printf 'Missing IOC output: %s\n' "${expected}" >&2
        printf '%s\n' "${ioc_output}" >&2
        exit 1
    fi
}

assert_ioc_output "identity: ARIES 1 4 3"
assert_ioc_output "detected axes: 6"
assert_ioc_output "communication: connected"
assert_ioc_output $'last asynchronous event: W\tSYS\t52'
assert_ioc_output "axis 1: position=250 moving=no homed=yes"
assert_ioc_output "axis 6: position=600 moving=no homed=yes"
assert_ioc_output "DBF_DOUBLE:         250"
assert_ioc_output "DBF_DOUBLE:         600"
assert_ioc_output 'DBF_STRING:         "Disable"'
assert_ioc_output "DBF_LONG:           5"
assert_ioc_output "Emergency-stop input detected; remove cause, then REM"
assert_ioc_output $'E\tSYS\t5'
assert_ioc_output "DBF_LONG:           52"
assert_ioc_output "Motionnet device configuration increase detected"
assert_ioc_output "SYS"
assert_ioc_output $'W\tSYS\t52'
assert_ioc_output 'DBF_STRING:         "Active"'
assert_ioc_output "REM blocked: physical EMG input remains active"
assert_ioc_output "RAX completed; axis map refreshed, verify and re-home"
assert_ioc_output "DBF_LONG:           10"
assert_ioc_output "Method 10 accepted: present position set as origin"
assert_ioc_output "HOME blocked: SYS.2 readback did not match selection"
assert_ioc_output "HOME method selected=4; controller SYS.2 will be checked before ORG"
assert_ioc_output "APS accepted: target=1050.000000 pulse"
assert_ioc_output "FRP accepted: direction=CW; release JOG to send STP/0"
assert_ioc_output "WRP verified: position=250 pulse"

if ! grep -Fq "RECEIVED STP1/0" "${server_log}"; then
    printf 'Normal stop command was not observed by mock ARIES.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED WTB1/0/100/1000/20/20/2" "${server_log}"; then
    printf 'Validated speed table 0 command was not observed.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED RSY1/16" "${server_log}"; then
    printf 'SYS.16 top-speed limit was not checked before WTB.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED RSY1/2" "${server_log}"; then
    printf 'SYS.2 was not checked before HOME.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED WSY1/2/10" "${server_log}"; then
    printf 'Selected OriginMethod was not written to SYS.2 before HOME.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if [[ "$(grep -Fc "RECEIVED RSY1/2" "${server_log}")" -ne 2 ]]; then
    printf 'Expected SYS.2 read before and after WSY1.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED ORG1/0/1" "${server_log}"; then
    printf 'Validated Method 10 ORG was not observed.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if grep -Fq "RECEIVED ORG2/0/1" "${server_log}"; then
    printf 'ORG2 was transmitted despite a SYS.2 selection mismatch.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED APS1/0/1000/1" "${server_log}"; then
    printf 'Validated absolute move was not observed.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED APS1/0/1050/1" "${server_log}"; then
    printf 'Motor-record relative request was not resolved to APS target 1050.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if [[ "$(grep -Fc "RECEIVED RSY1/16" "${server_log}")" -lt 3 ]]; then
    printf 'SYS.16 was not checked for both motor-record moves.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED FRP1/0/0" "${server_log}"; then
    printf 'Validated CW free-rotation command was not observed.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if ! grep -Fq "RECEIVED WRP1/250" "${server_log}"; then
    printf 'Validated coordinate-register write was not observed.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if [[ "$(grep -Fc "RECEIVED STP1/0" "${server_log}")" -lt 2 ]]; then
    printf 'JOG release did not send the normal STP/0 command.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if grep -Fq "RECEIVED REM" "${server_log}"; then
    printf 'Unsafe REM was transmitted while physical EMG remained active.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

if [[ "$(grep -Fc "RECEIVED RAX" "${server_log}")" -ne 2 ]]; then
    printf 'Expected discovery RAX and one explicit recovery RAX.\n' >&2
    cat "${server_log}" >&2
    exit 1
fi

echo "Mock ARIES TCP integration test passed"
