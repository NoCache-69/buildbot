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
    
    # 3. Capture build configuration variables
    local variant=$TARGET_BUILD_VARIANT
    [ -z "$variant" ] && variant="Unknown"
    local release=$TARGET_RELEASE
    [ -z "$release" ] && release=$TARGET_RELEASE_CONFIG
    [ -z "$release" ] && release="Unknown"
    
    local cmd="m $*"
    
    # Capture additional AOSP build variables
    local platform_ver=$PLATFORM_VERSION
    [ -z "$platform_ver" ] && platform_ver="Unknown"
    local target_prod=$TARGET_PRODUCT
    [ -z "$target_prod" ] && target_prod="Unknown"
    local target_arch=$TARGET_ARCH
    [ -z "$target_arch" ] && target_arch="Unknown"
    local build_id=$BUILD_ID
    [ -z "$build_id" ] && build_id="Unknown"
    
    # 4. Create log directory
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    # 5. Notify daemon about starting
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*" --variant "$variant" --release "$release" \
        --platform-version "$platform_ver" --target-product "$target_prod" --target-arch "$target_arch" --build-id "$build_id"
    
    # 6. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e -c "$TOP/build/soong/soong_ui.bash --make-mode $*" "$logfile"
    else
        script -q -e -c "make $*" "$logfile"
    fi
    local exit_code=$?
    
    # 7. Notify daemon about stopping
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
    
    local variant=$TARGET_BUILD_VARIANT
    [ -z "$variant" ] && variant="Unknown"
    local release=$TARGET_RELEASE
    [ -z "$release" ] && release=$TARGET_RELEASE_CONFIG
    [ -z "$release" ] && release="Unknown"
    
    local cmd="mka $*"
    
    # Capture additional AOSP build variables
    local platform_ver=$PLATFORM_VERSION
    [ -z "$platform_ver" ] && platform_ver="Unknown"
    local target_prod=$TARGET_PRODUCT
    [ -z "$target_prod" ] && target_prod="Unknown"
    local target_arch=$TARGET_ARCH
    [ -z "$target_arch" ] && target_arch="Unknown"
    local build_id=$BUILD_ID
    [ -z "$build_id" ] && build_id="Unknown"
    
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*" --variant "$variant" --release "$release" \
        --platform-version "$platform_ver" --target-product "$target_prod" --target-arch "$target_arch" --build-id "$build_id"
    
    local jobs=$(nproc)
    if [ "$USE_RBE" = "1" ]; then
        jobs=${NINJA_REMOTE_NUM_JOBS:-2000}
    fi
    
    # 5. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e -c "$TOP/build/soong/soong_ui.bash --make-mode -j$jobs $*" "$logfile"
    else
        script -q -e -c "make -j$jobs $*" "$logfile"
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
    
    local variant=$TARGET_BUILD_VARIANT
    [ -z "$variant" ] && variant="Unknown"
    local release=$TARGET_RELEASE
    [ -z "$release" ] && release=$TARGET_RELEASE_CONFIG
    [ -z "$release" ] && release="Unknown"
    
    local cmd="make $*"
    
    # Capture additional AOSP build variables
    local platform_ver=$PLATFORM_VERSION
    [ -z "$platform_ver" ] && platform_ver="Unknown"
    local target_prod=$TARGET_PRODUCT
    [ -z "$target_prod" ] && target_prod="Unknown"
    local target_arch=$TARGET_ARCH
    [ -z "$target_arch" ] && target_arch="Unknown"
    local build_id=$BUILD_ID
    [ -z "$build_id" ] && build_id="Unknown"
    
    mkdir -p "$TOP/out"
    local logfile="$TOP/out/tg_build.log"
    rm -f "$logfile"
    
    python3 /home/nocache/bot/cli.py start --top "$TOP" --command "$cmd" --device "$device" --targets "$*" --variant "$variant" --release "$release" \
        --platform-version "$platform_ver" --target-product "$target_prod" --target-arch "$target_arch" --build-id "$build_id"
    
    # 5. Execute build inside a PTY using script to preserve TTY (enabling RBE)
    if [ -f "$TOP/build/soong/soong_ui.bash" ]; then
        script -q -e -c "$TOP/build/soong/soong_ui.bash --make-mode $*" "$logfile"
    else
        script -q -e -c "make $*" "$logfile"
    fi
    local exit_code=$?
    
    python3 /home/nocache/bot/cli.py stop --top "$TOP" --exit-code "$exit_code"
    
    return $exit_code
}

# Apply Shell Aliases
alias m='_tg_m_wrapper'
alias mka='_tg_mka_wrapper'
alias make='_tg_make_wrapper'
