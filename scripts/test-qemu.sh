#!/usr/bin/env bash
#
# AgenticOS Local QEMU Live ISO Testing Suite
#
# Launches QEMU with optimal virtualization options for AgenticOS:
# - KVM hardware acceleration (auto-detected with graceful fallback)
# - UEFI firmware auto-detection (OVMF/EDK2) with legacy SeaBIOS support
# - VirtIO display (-vga virtio) and absolute pointer (-device virtio-tablet-pci)
# - VirtIO networking (-net nic,model=virtio -net user)
# - Configurable memory, CPU cores, snapshot mode, and ISO selection

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration defaults
ISO_PATH=""
MEMORY="4096M"
SMP_CORES="2"
BOOT_MODE="auto"     # auto, uefi, bios
KVM_MODE="auto"      # auto, on, off
SNAPSHOT=false
DRY_RUN=false
DUAL_MONITOR=false

# Standard OVMF / EDK2 UEFI firmware search paths
OVMF_SEARCH_PATHS=(
    "/usr/share/OVMF/OVMF_CODE.fd"
    "/usr/share/OVMF/OVMF_CODE_4M.fd"
    "/usr/share/ovmf/OVMF.fd"
    "/usr/share/qemu/OVMF.fd"
    "/usr/share/OVMF/OVMF.fd"
    "/usr/share/edk2/x64/OVMF_CODE.fd"
    "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd"
    "/usr/share/edk2/ovmf/OVMF_CODE.fd"
)

show_help() {
    cat << 'EOF'
AgenticOS QEMU Live Test Runner

Usage:
  test-qemu.sh [OPTIONS] [ISO_PATH]

Options:
  -i, --iso PATH         Path to live ISO image (auto-detected if not specified)
  -m, --mem SIZE         Guest RAM size (default: 4096M, e.g. 2048M, 4G, 8192M)
  -c, --cpus NUM         Number of virtual CPU cores (default: 2)
      --uefi             Force UEFI firmware boot (OVMF)
      --bios             Force legacy SeaBIOS boot
      --kvm              Force enable KVM acceleration
      --no-kvm           Disable KVM (force software TCG emulation)
  -s, --snapshot         Enable snapshot mode (prevent modifying media)
      --dual-monitor     Attach secondary virtio display for multi-head testing
  -n, --dry-run          Print the assembled QEMU command line without executing
  -h, --help             Display this help message and exit

Examples:
  ./scripts/test-qemu.sh --dry-run
  ./scripts/test-qemu.sh --uefi --mem 8192M
  ./scripts/test-qemu.sh --iso live-image-amd64.hybrid.iso
  ./scripts/test-qemu.sh /path/to/custom-agentic-os.iso
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -i|--iso)
            ISO_PATH="$2"
            shift 2
            ;;
        --iso=*)
            ISO_PATH="${1#*=}"
            shift
            ;;
        -m|--mem)
            MEMORY="$2"
            shift 2
            ;;
        --mem=*)
            MEMORY="${1#*=}"
            shift
            ;;
        -c|--cpus|--smp)
            SMP_CORES="$2"
            shift 2
            ;;
        --cpus=*|--smp=*)
            SMP_CORES="${1#*=}"
            shift
            ;;
        --uefi)
            BOOT_MODE="uefi"
            shift
            ;;
        --bios)
            BOOT_MODE="bios"
            shift
            ;;
        --kvm)
            KVM_MODE="on"
            shift
            ;;
        --no-kvm)
            KVM_MODE="off"
            shift
            ;;
        -s|--snapshot)
            SNAPSHOT=true
            shift
            ;;
        --dual-monitor)
            DUAL_MONITOR=true
            shift
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -*)
            echo "Error: Unknown option '$1'. Use --help for usage." >&2
            exit 1
            ;;
        *)
            if [ -z "$ISO_PATH" ]; then
                ISO_PATH="$1"
            else
                echo "Error: Unexpected argument '$1'." >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# Normalize memory string (e.g. 4096 -> 4096M)
if [[ "$MEMORY" =~ ^[0-9]+$ ]]; then
    MEMORY="${MEMORY}M"
fi

# Locate ISO image if not explicitly provided
find_iso() {
    if [ -n "$ISO_PATH" ]; then
        if [ -f "$ISO_PATH" ]; then
            echo "$ISO_PATH"
            return 0
        elif [ "$DRY_RUN" = true ]; then
            echo "$ISO_PATH"
            return 0
        else
            echo "Error: Specified ISO image not found at '$ISO_PATH'." >&2
            return 1
        fi
    fi

    # Search candidates in current directory and repo root
    local search_dirs=("$PWD" "$REPO_ROOT")
    local candidates=(
        "agentic-os-live-amd64.hybrid.iso"
        "live-image-amd64.hybrid.iso"
    )

    for dir in "${search_dirs[@]}"; do
        for name in "${candidates[@]}"; do
            if [ -f "${dir}/${name}" ]; then
                echo "${dir}/${name}"
                return 0
            fi
        done
        # Wildcard fallback
        for f in "${dir}"/*.hybrid.iso "${dir}"/*.iso; do
            if [ -f "$f" ]; then
                echo "$f"
                return 0
            fi
        done
    done

    if [ "$DRY_RUN" = true ]; then
        # In dry run mode, return a plausible default if none exists on disk
        echo "agentic-os-live-amd64.hybrid.iso"
        return 0
    fi

    echo "Error: No ISO image found in '$PWD' or '$REPO_ROOT'." >&2
    echo "Please build the live image using 'make build' or specify '--iso <path>'." >&2
    return 1
}

RESOLVED_ISO=$(find_iso)

# Find UEFI OVMF firmware
find_ovmf() {
    for path in "${OVMF_SEARCH_PATHS[@]}"; do
        if [ -f "$path" ]; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# Resolve Boot Mode and Firmware
OVMF_PATH=""
if [ "$BOOT_MODE" = "uefi" ]; then
    if OVMF_PATH=$(find_ovmf); then
        :
    elif [ "$DRY_RUN" = true ]; then
        OVMF_PATH="/usr/share/OVMF/OVMF_CODE.fd"
    else
        echo "Error: UEFI mode requested (--uefi), but no OVMF firmware file found." >&2
        echo "Please install ovmf: sudo apt-get install ovmf" >&2
        exit 1
    fi
elif [ "$BOOT_MODE" = "auto" ]; then
    if OVMF_PATH=$(find_ovmf); then
        BOOT_MODE="uefi"
    else
        BOOT_MODE="bios"
        echo "Notice: No OVMF firmware detected; falling back to SeaBIOS legacy mode." >&2
    fi
fi

# Resolve KVM hardware acceleration
USE_KVM=false
if [ "$KVM_MODE" = "on" ]; then
    USE_KVM=true
    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
        echo "Warning: /dev/kvm is not accessible with read/write permissions. KVM may fail." >&2
    fi
elif [ "$KVM_MODE" = "auto" ]; then
    if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        USE_KVM=true
    else
        echo "Warning: /dev/kvm not accessible; falling back to TCG software emulation mode." >&2
    fi
fi

# Construct QEMU Command Line Arguments
QEMU_BIN="qemu-system-x86_64"
CMD_ARGS=()

# Acceleration & CPU
if [ "$USE_KVM" = true ]; then
    CMD_ARGS+=("-enable-kvm" "-cpu" "host")
else
    CMD_ARGS+=("-cpu" "qemu64")
fi

# Memory & Virtual Cores
CMD_ARGS+=("-m" "$MEMORY")
CMD_ARGS+=("-smp" "$SMP_CORES")

# UEFI Firmware if enabled
if [ "$BOOT_MODE" = "uefi" ] && [ -n "$OVMF_PATH" ]; then
    CMD_ARGS+=("-bios" "$OVMF_PATH")
fi

# Display & Input Devices (Optimized for Wayland & Computer Use)
CMD_ARGS+=("-vga" "virtio")
CMD_ARGS+=("-device" "virtio-tablet-pci")

if [ "$DUAL_MONITOR" = true ]; then
    CMD_ARGS+=("-device" "secondary-vga")
fi

# VirtIO Network
CMD_ARGS+=("-net" "nic,model=virtio" "-net" "user")

# CD-ROM ISO & Boot Preference
CMD_ARGS+=("-cdrom" "$RESOLVED_ISO")
CMD_ARGS+=("-boot" "d")

# Snapshot mode
if [ "$SNAPSHOT" = true ]; then
    CMD_ARGS+=("-snapshot")
fi

# Handle Dry-Run
if [ "$DRY_RUN" = true ]; then
    echo "======================================================================"
    echo " [DRY-RUN] AgenticOS QEMU Test Runner Preview"
    echo "======================================================================"
    echo " Target ISO:   $RESOLVED_ISO"
    echo " Boot Mode:    $BOOT_MODE ${OVMF_PATH:+(Firmware: $OVMF_PATH)}"
    echo " KVM Accel:    $USE_KVM"
    echo " Memory:       $MEMORY"
    echo " CPU Cores:    $SMP_CORES"
    echo " Display:      virtio (-vga virtio) with virtio-tablet-pci pointer"
    echo " Network:      VirtIO NAT (-net nic,model=virtio -net user)"
    echo " Snapshot:     $SNAPSHOT"
    echo "======================================================================"
    echo "[DRY-RUN] Command:"
    echo "$QEMU_BIN" "${CMD_ARGS[@]}"
    exit 0
fi

# Verify QEMU binary is available before execution
if ! command -v "$QEMU_BIN" >/dev/null 2>&1; then
    echo "Error: '$QEMU_BIN' is not installed or not in PATH." >&2
    echo "Please install it with: sudo apt-get install qemu-system-x86" >&2
    exit 1
fi

echo "==> Launching AgenticOS Live in QEMU..."
exec "$QEMU_BIN" "${CMD_ARGS[@]}"
