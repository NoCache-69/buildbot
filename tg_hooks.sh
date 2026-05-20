# AOSP Build Tracking Shell Hooks
# Add "source /home/nocache/bot/tg_hooks.sh" to your ~/.bashrc or ~/.zshrc

_tg_m_wrapper() {
    # 1. Determine build workspace root
    local TOP=""
    if declare -f gettop > /dev/null; then
        TOP=$(gettop)
    fi
    [ -z "$TOP" ] && TOP=$(pwd)
    
    # 2. Extract target device information
    local device=$TARGET_DEVICE
    [ -z "$device" ] && device=$TARGET_PRODUCT
    [ -z "$device" ] && device="AOSP Device"
    
    local cmd="m $*"
    
    # 3. Create log directory
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    # 4. Notify daemon about starting
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*"
    
    # 5. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e "$logfile" -- "$TOP/build/soong/soong_ui.bash" --make-mode "$@"
    else
        script -q -e "$logfile" -- make "$@"
    fi
    local exit_code=$?
    
    # 6. Notify daemon about stopping
    python3 /home/nocache/bot/cli.py stop --top "$TOP" --exit-code "$exit_code"
    
    return $exit_code
}

_tg_mka_wrapper() {
    local TOP=""
    if declare -f gettop > /dev/null; then
        TOP=$(gettop)
    fi
    [ -z "$TOP" ] && TOP=$(pwd)
    
    local device=$TARGET_DEVICE
    [ -z "$device" ] && device=$TARGET_PRODUCT
    [ -z "$device" ] && device="AOSP Device"
    
    local cmd="mka $*"
    
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*"
    
    # 5. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e "$logfile" -- "$TOP/build/soong/soong_ui.bash" --make-mode -j$(nproc) "$@"
    else
        script -q -e "$logfile" -- make -j$(nproc) "$@"
    fi
    local exit_code=$?
    
    python3 /home/nocache/bot/cli.py stop --top "$TOP" --exit-code "$exit_code"
    
    return $exit_code
}

_tg_make_wrapper() {
    local TOP=""
    if declare -f gettop > /dev/null; then
        TOP=$(gettop)
    fi
    [ -z "$TOP" ] && TOP=$(pwd)
    
    local device=$TARGET_DEVICE
    [ -z "$device" ] && device=$TARGET_PRODUCT
    [ -z "$device" ] && device="AOSP Device"
    
    local cmd="make $*"
    
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*"
    
    # 5. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e "$logfile" -- "$TOP/build/soong/soong_ui.bash" --make-mode "$@"
    else
        script -q -e "$logfile" -- make "$@"
    fi
    local exit_code=$?
    
    python3 /home/nocache/bot/cli.py stop --top "$TOP" --exit-code "$exit_code"
    
    return $exit_code
}

# Apply Shell Aliases
alias m='_tg_m_wrapper'
alias mka='_tg_mka_wrapper'
alias make='_tg_make_wrapper'

# Print a nice status on loading
echo "🚀 [Telegram Bot] Shell aliases loaded successfully! ('m', 'mka', 'make')"
echo "💡 Commands will automatically broadcast live progress to your Telegram channels."
