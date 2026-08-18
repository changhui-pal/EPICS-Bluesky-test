#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ioc_dir="${project_dir}/iocBoot/iockohzuAriesLynx"
ioc_command="${ioc_dir}/st.cmd"
runtime_config="${project_dir}/config/runtime.ini"
use_sudo=0

# Locate an alternate configuration before deriving the remaining defaults.
previous=""
for argument in "$@"; do
    if [[ "${previous}" == "--config" ]]; then
        runtime_config="${argument}"
        break
    fi
    previous="${argument}"
done

# Keep machine/controller state out of Git. Missing local files are initialized
# once from safe tracked examples and are never overwritten by the launcher.
python3 "${project_dir}/tools/initialize_local_config.py" \
    --runtime-target "${runtime_config}" \
    --assignments-target "${project_dir}/config/axis-assignments.ini"

runtime_get() {
    python3 "${project_dir}/tools/runtime_config.py" \
        --config "${runtime_config}" --get "$1"
}

controller_host="$(runtime_get controller.host)"
controller_port="$(runtime_get controller.port)"
python_command="$(runtime_get python.executable)"
epics_bin="$(runtime_get epics.bin)"
prefix="$(runtime_get epics.prefix)"
ca_addr_list="$(runtime_get epics.ca_addr_list)"
gui_listen="$(runtime_get gui.listen)"
gui_port="$(runtime_get gui.port)"

usage() {
    cat <<'EOF'
Usage: ./start_kohzu_control.sh [OPTIONS]

Starts the production IOC, applies axis-assignments.ini, and starts the GUI.
Defaults come from config/runtime.ini; command-line options override them.

Options:
  --config FILE             Alternate runtime configuration file.
  --controller-host HOST    Controller address override.
  --controller-port PORT    Controller TCP port override.
  --prefix PREFIX           EPICS PV prefix override.
  --epics-bin DIRECTORY     EPICS command directory override.
  --ca-addr-list ADDRESSES  EPICS Channel Access address list override.
  --python EXECUTABLE       Python environment override.
  --listen ADDRESS          GUI bind address override.
  --port PORT               GUI port override.
  --sudo                    Start the IOC through sudo (normally unnecessary).
  -h, --help                Show this help.
EOF
}

while (($#)); do
    case "$1" in
        --config|--controller-host|--controller-port|--prefix|--epics-bin|\
        --ca-addr-list|--python|--listen|--port)
            if (($# < 2)); then
                printf '%s requires a value\n' "$1" >&2
                exit 2
            fi
            ;;
    esac
    case "$1" in
        --sudo)
            use_sudo=1
            shift
            ;;
        --config)
            shift 2
            ;;
        --controller-host)
            controller_host="$2"
            shift 2
            ;;
        --controller-port)
            controller_port="$2"
            shift 2
            ;;
        --prefix)
            prefix="$2"
            shift 2
            ;;
        --epics-bin)
            epics_bin="$2"
            shift 2
            ;;
        --ca-addr-list)
            ca_addr_list="$2"
            shift 2
            ;;
        --python)
            python_command="$2"
            shift 2
            ;;
        --listen)
            gui_listen="$2"
            shift 2
            ;;
        --port)
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

for port_spec in "GUI:${gui_port}" "controller:${controller_port}"; do
    port_name="${port_spec%%:*}"
    port_value="${port_spec#*:}"
    if ! [[ "${port_value}" =~ ^[0-9]+$ ]] || \
            ((port_value < 1 || port_value > 65535)); then
        printf 'Invalid %s port: %s\n' "${port_name}" "${port_value}" >&2
        exit 2
    fi
done

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

log_root="${project_dir}/logs/kohzu-control"
session_name="$(date '+%Y%m%d-%H%M%S')-$$"
log_dir="${log_root}/${session_name}"
runtime_dir="$(mktemp -d /tmp/kohzu-control-runtime.XXXXXX)"
ioc_log="${log_dir}/ioc.log"
gui_log="${log_dir}/gui.log"
apply_log="${log_dir}/apply.log"
launcher_log_file="${log_dir}/launcher.log"
session_log="${log_dir}/session.log"
ioc_input="${runtime_dir}/ioc.stdin"
ioc_pid=""
gui_pid=""
follower_pid=""
cleaning=0
mkdir -p "${log_dir}"
touch "${ioc_log}" "${gui_log}" "${apply_log}" \
      "${launcher_log_file}" "${session_log}"
ln -sfn "${session_name}" "${log_root}/latest"
mkfifo "${ioc_input}"
# Open both ends in the launcher so the IOC shell never observes EOF while it
# runs in the background. The same descriptor sends a normal `exit` at cleanup.
exec {ioc_input_fd}<>"${ioc_input}"

python3 "${project_dir}/tools/follow_control_logs.py" \
    --session "${session_log}" \
    --source "IOC=${ioc_log}" \
    --source "APPLY=${apply_log}" \
    --source "GUI=${gui_log}" &
follower_pid=$!

launcher_log() {
    local rendered
    rendered="$(date '+%Y-%m-%dT%H:%M:%S.%3N%:z') [LAUNCHER] $*"
    printf '%s\n' "${rendered}" | tee -a \
        "${launcher_log_file}" "${session_log}"
}

cleanup() {
    local status="${1:-$?}"
    if ((cleaning)); then
        return
    fi
    cleaning=1
    trap - INT TERM EXIT

    if [[ -n "${gui_pid}" ]] && kill -0 "${gui_pid}" 2>/dev/null; then
        launcher_log 'Stopping GUI and disabling its panel axes...'
        kill -TERM "${gui_pid}" 2>/dev/null || true
        wait "${gui_pid}" 2>/dev/null || true
    fi
    if [[ -n "${ioc_pid}" ]] && kill -0 "${ioc_pid}" 2>/dev/null; then
        launcher_log 'Stopping IOC...'
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
    rm -f -- "${ioc_input}"
    rmdir -- "${runtime_dir}" 2>/dev/null || true

    if ((status == 0)); then
        launcher_log "Session completed; logs retained in ${log_dir}"
    else
        launcher_log "Session failed with status ${status}; logs retained in ${log_dir}"
    fi
    if [[ -n "${follower_pid}" ]] && kill -0 "${follower_pid}" 2>/dev/null; then
        kill -TERM "${follower_pid}" 2>/dev/null || true
        wait "${follower_pid}" 2>/dev/null || true
    fi
    exit "${status}"
}
trap 'cleanup 0' INT TERM
trap cleanup EXIT

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST="${ca_addr_list}"
export KOHZU_CONTROLLER_HOST="${controller_host}"
export KOHZU_CONTROLLER_PORT="${controller_port}"
export KOHZU_PREFIX="${prefix}"

if ((use_sudo)); then
    launcher_log 'Authenticating sudo for IOC startup...'
    sudo -v
    (
        trap '' INT
        cd "${ioc_dir}"
        exec sudo --preserve-env=LD_LIBRARY_PATH,KOHZU_CONTROLLER_HOST,KOHZU_CONTROLLER_PORT,KOHZU_PREFIX ./st.cmd
    ) <&"${ioc_input_fd}" >"${ioc_log}" 2>&1 &
else
    (
        trap '' INT
        cd "${ioc_dir}"
        exec ./st.cmd
    ) <&"${ioc_input_fd}" >"${ioc_log}" 2>&1 &
fi
ioc_pid=$!
launcher_log "IOC starting (PID ${ioc_pid})"

ioc_ready=0
for _ in {1..100}; do
    if ! kill -0 "${ioc_pid}" 2>/dev/null; then
        launcher_log 'IOC exited during startup.'
        exit 1
    fi
    if "${epics_bin}/caget" -t "${prefix}m1.DMOV" >/dev/null 2>&1; then
        ioc_ready=1
        break
    fi
    sleep 0.1
done
if ((ioc_ready == 0)); then
    launcher_log 'IOC PVs did not become available within 10 seconds.'
    exit 1
fi

launcher_log 'Applying persistent axis assignments...'
"${python_command}" "${project_dir}/tools/stage_config_apply.py" \
    --runtime-config "${runtime_config}" --prefix "${prefix}" \
    --epics-bin "${epics_bin}" --apply >"${apply_log}" 2>&1

(
    trap '' INT
    exec "${python_command}" "${project_dir}/gui/kohzu_gui_server.py" \
        --runtime-config "${runtime_config}" --prefix "${prefix}" \
        --listen "${gui_listen}" --port "${gui_port}" \
        --epics-bin "${epics_bin}"
) >"${gui_log}" 2>&1 &
gui_pid=$!

gui_probe_host="${gui_listen}"
if [[ "${gui_probe_host}" == "0.0.0.0" ]]; then
    gui_probe_host="127.0.0.1"
elif [[ "${gui_probe_host}" == "::" || "${gui_probe_host}" == "::0" ]]; then
    gui_probe_host="[::1]"
fi

gui_ready=0
for _ in {1..100}; do
    if ! kill -0 "${gui_pid}" 2>/dev/null; then
        launcher_log 'GUI server exited during startup.'
        exit 1
    fi
    if curl --silent --fail "http://${gui_probe_host}:${gui_port}/api/config" \
            >/dev/null 2>&1; then
        gui_ready=1
        break
    fi
    sleep 0.1
done
if ((gui_ready == 0)); then
    launcher_log 'GUI did not become available within 10 seconds.'
    exit 1
fi

launcher_log 'KOHZU control session is running.'
launcher_log "GUI bind: http://${gui_listen}:${gui_port}"
launcher_log "Live session log: ${session_log}"
launcher_log 'Press Ctrl-C to stop GUI first and IOC second.'

wait "${gui_pid}"
