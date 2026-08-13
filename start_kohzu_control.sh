#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ioc_dir="${project_dir}/iocBoot/iockohzuAriesLynx"
ioc_command="${ioc_dir}/st.cmd"
python_command="/home/changhui1788/.conda/envs/kohzu-bluesky/bin/python"
epics_bin="/usr/local/epics/base-7.0.7/bin/linux-x86_64"
prefix="KOHZU:"
gui_port=8080
use_sudo=0

usage() {
    cat <<'EOF'
Usage: ./start_kohzu_control.sh [--sudo] [--port PORT]

Starts the production IOC, applies axis-assignments.ini, and starts the local
GUI. Press Ctrl-C once to disable GUI panel axes, stop the web server, and then
stop the IOC.

Options:
  --sudo       Start the IOC through sudo (normally unnecessary).
  --port PORT  GUI port (default: 8080).
  -h, --help   Show this help.
EOF
}

while (($#)); do
    case "$1" in
        --sudo)
            use_sudo=1
            shift
            ;;
        --port)
            if (($# < 2)); then
                printf '%s\n' '--port requires a value' >&2
                exit 2
            fi
            gui_port="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "${gui_port}" =~ ^[0-9]+$ ]] || ((gui_port < 1 || gui_port > 65535)); then
    printf 'Invalid GUI port: %s\n' "${gui_port}" >&2
    exit 2
fi

for required in "${ioc_command}" "${python_command}" \
                "${epics_bin}/caget" "${project_dir}/tools/stage_config_apply.py"; do
    if [[ ! -e "${required}" ]]; then
        printf 'Required file not found: %s\n' "${required}" >&2
        exit 1
    fi
done

if pgrep -f '[k]ohzuAriesLynx.*st\.cmd' >/dev/null; then
    printf '%s\n' 'A KOHZU IOC process is already running.' >&2
    exit 1
fi
if pgrep -f '[k]ohzu_gui_server\.py' >/dev/null; then
    printf '%s\n' 'A KOHZU GUI server process is already running.' >&2
    exit 1
fi

run_dir="$(mktemp -d /tmp/kohzu-control.XXXXXX)"
ioc_log="${run_dir}/ioc.log"
gui_log="${run_dir}/gui.log"
ioc_input="${run_dir}/ioc.stdin"
ioc_pid=""
gui_pid=""
cleaning=0
mkfifo "${ioc_input}"
# Open both ends in the launcher so the IOC shell never observes EOF while it
# runs in the background. The same descriptor sends a normal `exit` at cleanup.
exec {ioc_input_fd}<>"${ioc_input}"

cleanup() {
    local status=$?
    if ((cleaning)); then
        return
    fi
    cleaning=1
    trap - INT TERM EXIT

    if [[ -n "${gui_pid}" ]] && kill -0 "${gui_pid}" 2>/dev/null; then
        printf '%s\n' 'Stopping GUI and disabling its panel axes...'
        kill -TERM "${gui_pid}" 2>/dev/null || true
        wait "${gui_pid}" 2>/dev/null || true
    fi
    if [[ -n "${ioc_pid}" ]] && kill -0 "${ioc_pid}" 2>/dev/null; then
        printf '%s\n' 'Stopping IOC...'
        printf 'exit\n' >&"${ioc_input_fd}" 2>/dev/null || true
        for _ in {1..20}; do
            if ! kill -0 "${ioc_pid}" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        if kill -0 "${ioc_pid}" 2>/dev/null; then
            kill -TERM "${ioc_pid}" 2>/dev/null || true
        fi
        wait "${ioc_pid}" 2>/dev/null || true
    fi
    exec {ioc_input_fd}>&-

    if ((status == 0)); then
        rm -f -- "${ioc_log}" "${gui_log}" "${ioc_input}"
        rmdir -- "${run_dir}" 2>/dev/null || true
    else
        printf 'Startup/runtime logs retained in %s\n' "${run_dir}" >&2
    fi
    exit "${status}"
}
trap cleanup INT TERM EXIT

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1

if ((use_sudo)); then
    printf '%s\n' 'Authenticating sudo for IOC startup...'
    sudo -v
    (
        cd "${ioc_dir}"
        exec sudo --preserve-env=LD_LIBRARY_PATH ./st.cmd
    ) <&"${ioc_input_fd}" >"${ioc_log}" 2>&1 &
else
    (
        cd "${ioc_dir}"
        exec ./st.cmd
    ) <&"${ioc_input_fd}" >"${ioc_log}" 2>&1 &
fi
ioc_pid=$!
printf 'IOC starting (PID %s, log %s)\n' "${ioc_pid}" "${ioc_log}"

ioc_ready=0
for _ in {1..100}; do
    if ! kill -0 "${ioc_pid}" 2>/dev/null; then
        printf '%s\n' 'IOC exited during startup.' >&2
        tail -n 80 "${ioc_log}" >&2 || true
        exit 1
    fi
    if "${epics_bin}/caget" -t "${prefix}m1.DMOV" >/dev/null 2>&1; then
        ioc_ready=1
        break
    fi
    sleep 0.1
done
if ((ioc_ready == 0)); then
    printf '%s\n' 'IOC PVs did not become available within 10 seconds.' >&2
    tail -n 80 "${ioc_log}" >&2 || true
    exit 1
fi

printf '%s\n' 'Applying persistent axis assignments...'
"${python_command}" "${project_dir}/tools/stage_config_apply.py" \
    --prefix "${prefix}" --epics-bin "${epics_bin}" --apply

"${python_command}" "${project_dir}/gui/kohzu_gui_server.py" \
    --prefix "${prefix}" --port "${gui_port}" >"${gui_log}" 2>&1 &
gui_pid=$!

gui_ready=0
for _ in {1..100}; do
    if ! kill -0 "${gui_pid}" 2>/dev/null; then
        printf '%s\n' 'GUI server exited during startup.' >&2
        cat "${gui_log}" >&2 || true
        exit 1
    fi
    if curl --silent --fail "http://127.0.0.1:${gui_port}/api/config" \
            >/dev/null 2>&1; then
        gui_ready=1
        break
    fi
    sleep 0.1
done
if ((gui_ready == 0)); then
    printf '%s\n' 'GUI did not become available within 10 seconds.' >&2
    cat "${gui_log}" >&2 || true
    exit 1
fi

printf '\nKOHZU control session is running.\n'
printf 'GUI: http://127.0.0.1:%s\n' "${gui_port}"
printf 'Press Ctrl-C to stop GUI first and IOC second.\n\n'

wait "${gui_pid}"
