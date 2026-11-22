# AOSP Build Tracking Shell Hooks
# Add "source /path/to/tg_hooks.sh" to your ~/.bashrc or ~/.zshrc

# Guard against multiple wrapping within the same build subshell
if [ "${_TG_IN_WRAPPER:-}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi

# Determine directory of this script, supporting both bash and zsh
if [ -n "${BASH_VERSION:-}" ]; then
    _TG_BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then
    _TG_BOT_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
    _TG_BOT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
    [ -z "${_TG_BOT_DIR:-}" ] && _TG_BOT_DIR="$HOME/bot" # fallback
fi

# Ensure BASH_ENV is exported so non-interactive scripts automatically inherit and source hooks
if [ -n "${BASH_VERSION:-}" ] && [ -n "${_TG_BOT_DIR:-}" ]; then
    export BASH_ENV="$_TG_BOT_DIR/tg_hooks.sh"
fi

_tg_print_build_status() {
    local exit_code=$1
    local start_time=$2
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))

    local hours=$((elapsed / 3600))
    local minutes=$(((elapsed % 3600) / 60))
    local seconds=$((elapsed % 60))
    local elapsed_str=""
    if [ $hours -gt 0 ]; then
        elapsed_str="${hours}h ${minutes}m ${seconds}s"
    elif [ $minutes -gt 0 ]; then
        elapsed_str="${minutes}m ${seconds}s"
    else
        elapsed_str="${seconds}s"
    fi

    if [ $exit_code -eq 0 ]; then
        printf "\n✅ \033[1;32mBuild Completed Successfully!\033[0m\n"
        printf "⏱️ \033[1mElapsed Time:\033[0m %s\n\n" "$elapsed_str"
    else
        printf "\n❌ \033[1;31mBuild Failed!\033[0m\n"
        printf "⏱️ \033[1mElapsed Time:\033[0m %s\n\n" "$elapsed_str"
    fi
}

# --- Shared common build orchestration ---
# Usage: _tg_run_build <build_label> <extra_flags> [target_args...]
#   build_label: "m", "mka", or "make"
#   extra_flags: additional CLI flags (e.g. "-j$(nproc)"), or "" if none
#   target_args: build targets (e.g. bacon)
_tg_run_build() {
    local -x _TG_IN_WRAPPER=1
    local build_type="$1"
    local extra_cmd_flags="${2:-}"
    shift 2
    # Now $@ contains only the build targets

    # 1. Determine build workspace root
    local TOP=""
    if declare -f gettop > /dev/null; then
        TOP=$(gettop)
    fi
    [ -z "$TOP" ] && TOP=$(pwd)

    # 2. Capture target device
    local device="${TARGET_DEVICE:-}"
    [ -z "$device" ] && device="${TARGET_PRODUCT:-}"
    [ -z "$device" ] && device="AOSP Device"

    # 3. Capture build variant & release
    local variant="${TARGET_BUILD_VARIANT:-}"
    [ -z "$variant" ] && variant="Unknown"
    local release="${TARGET_RELEASE:-}"
    [ -z "$release" ] && release="${TARGET_RELEASE_CONFIG:-}"
    [ -z "$release" ] && release="Unknown"

    # 4. Capture additional AOSP environment variables
    local platform_ver="${PLATFORM_VERSION:-}"
    [ -z "$platform_ver" ] && platform_ver="Unknown"
    local target_prod="${TARGET_PRODUCT:-}"
    [ -z "$target_prod" ] && target_prod="Unknown"
    local target_arch="${TARGET_ARCH:-}"
    [ -z "$target_arch" ] && target_arch="Unknown"
    local build_id="${BUILD_ID:-}"
    [ -z "$build_id" ] && build_id="Unknown"

    local cmd="${build_type} $*"

    # 5. Prepare log file
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"

    # 6. Notify daemon about build start
    local builder_user="${USER:-$(whoami 2>/dev/null || echo "Unknown")}"
    local builder_host="${HOSTNAME:-$(hostname 2>/dev/null || uname -n 2>/dev/null || echo "Unknown")}"
    python3 "$_TG_BOT_DIR/cli.py" start \
        --top "$TOP" \
        --command "$cmd" \
        --device "$device" \
        --targets "$*" \
        --variant "$variant" \
        --release "$release" \
        --platform-version "$platform_ver" \
        --target-product "$target_prod" \
        --target-arch "$target_arch" \
        --build-id "$build_id" \
        --user "$builder_user" \
        --host "$builder_host"

    local start_time=$(date +%s)

    # 7. Execute build inside a PTY (preserves TTY for RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e -c "$TOP/build/soong/soong_ui.bash --make-mode ${extra_cmd_flags} $*" "$logfile"
    else
        script -q -e -c "make ${extra_cmd_flags} $*" "$logfile"
    fi
    local exit_code=$?

    # 8. Notify daemon about build stop
    python3 "$_TG_BOT_DIR/cli.py" stop --top "$TOP" --exit-code "$exit_code"

    _tg_print_build_status "$exit_code" "$start_time"

    # Re-export m="" in case envsetup.sh is sourced again before another build step
    export m=""

    return $exit_code
}

# --- Per-command wrappers (thin wrappers around _tg_run_build) ---

_tg_m_wrapper() {
    _tg_run_build "m" "" "$@"
}

_tg_mka_wrapper() {
    local jobs=$(nproc)
    if [ "${USE_RBE:-}" = "1" ]; then
        jobs=${NINJA_REMOTE_NUM_JOBS:-2000}
    fi
    _tg_run_build "mka" "-j${jobs}" "$@"
}

_tg_make_wrapper() {
    _tg_run_build "make" "" "$@"
}

# Export the wrapper functions so they are available in subshells
if [ -n "${BASH_VERSION:-}" ]; then
    export -f _tg_print_build_status
    export -f _tg_run_build
    export -f _tg_m_wrapper
    export -f _tg_mka_wrapper
    export -f _tg_make_wrapper
fi

# Define and export fallback functions
m() {
    _tg_m_wrapper "$@"
}
mka() {
    _tg_mka_wrapper "$@"
}
make() {
    if [ "${_TG_IN_WRAPPER:-}" = "1" ]; then
        command make "$@"
    else
        _tg_make_wrapper "$@"
    fi
}

# Safe no-op and auto-cleanup in case any subshell still evaluates _tg_reassert_hooks
_tg_reassert_hooks() {
    if [[ "${PROMPT_COMMAND:-}" == *"_tg_reassert_hooks"* ]]; then
        PROMPT_COMMAND="${PROMPT_COMMAND//_tg_reassert_hooks;/}"
        PROMPT_COMMAND="${PROMPT_COMMAND//_tg_reassert_hooks/}"
        if [ -z "$PROMPT_COMMAND" ]; then
            unset PROMPT_COMMAND
        fi
    fi
    return 0
}

# Export fallback functions for scripts and subshells
if [ -n "${BASH_VERSION:-}" ]; then
    export -f m
    export -f mka
    export -f make
    export -f _tg_reassert_hooks 2>/dev/null || true

    # Clean up lingering _tg_reassert_hooks from PROMPT_COMMAND immediately
    if [[ "${PROMPT_COMMAND:-}" == *"_tg_reassert_hooks"* ]]; then
        PROMPT_COMMAND="${PROMPT_COMMAND//_tg_reassert_hooks;/}"
        PROMPT_COMMAND="${PROMPT_COMMAND//_tg_reassert_hooks/}"
        if [ -z "$PROMPT_COMMAND" ]; then
            unset PROMPT_COMMAND
        else
            export PROMPT_COMMAND
        fi
    fi
fi

# Apply Shell Aliases (taking precedence over functions in interactive shells)
alias m='_tg_m_wrapper'
alias mka='_tg_mka_wrapper'
alias make='_tg_make_wrapper'
