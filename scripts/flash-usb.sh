#!/usr/bin/env bash
#
# AgenticOS USB Flash & Persistence Setup Script
#
# Flashes the live ISO image to a target physical USB drive with a 3-partition GPT layout:
# - Partition 1 (p1): 512MiB EFI System Partition (FAT32, ESP/boot, label "EFI-LIVE")
# - Partition 2 (p2): 4096MiB Live System partition (hybrid ISO written via dd)
# - Partition 3 (p3): Remainder of disk for Ext4 persistence (label "persistence", / union, commit=60)
#
# Safety guards:
# - Strictly rejects system root (/), boot (/boot), and user home (/home) disks
# - Validates that the target is an actual block device
# - Interactive confirmation prompt (bypassable with --yes / -y)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET="${DEVICE:-}"
ISO_PATH=""
PERSISTENCE_LABEL="persistence"
ASSUME_YES=false
DRY_RUN=false

show_help() {
    cat << 'EOF'
Aeth OS USB Flash & Persistence Tool

Usage:
  flash-usb.sh [OPTIONS] <TARGET_DEVICE>
  flash-usb.sh [OPTIONS] --target <TARGET_DEVICE>

Arguments:
  TARGET_DEVICE          Block device path (e.g. /dev/sdX, /dev/nvme0n1)

Options:
  -t, --target DEV       Target block device path
  -i, --iso PATH         Path to live ISO image (auto-detected if omitted)
  -l, --label LABEL      Filesystem label for persistence partition (default: persistence)
  -y, --yes              Assume YES to all safety confirmation prompts
  -n, --dry-run          Preview partition and format commands without writing
  -h, --help             Display this help message and exit

Examples:
  sudo ./scripts/flash-usb.sh /dev/sdb
  sudo ./scripts/flash-usb.sh --iso agentic-os-live-amd64.hybrid.iso /dev/sdc
  ./scripts/flash-usb.sh --dry-run /dev/sdb
EOF
}

# Parse command-line options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -t|--target)
            TARGET="$2"
            shift 2
            ;;
        --target=*)
            TARGET="${1#*=}"
            shift
            ;;
        -i|--iso)
            ISO_PATH="$2"
            shift 2
            ;;
        --iso=*)
            ISO_PATH="${1#*=}"
            shift
            ;;
        -l|--label)
            PERSISTENCE_LABEL="$2"
            shift 2
            ;;
        --label=*)
            PERSISTENCE_LABEL="${1#*=}"
            shift
            ;;
        -y|--yes)
            ASSUME_YES=true
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
            if [ -z "$TARGET" ]; then
                TARGET="$1"
            elif [ -z "$ISO_PATH" ] && [[ "$1" == *.iso ]]; then
                ISO_PATH="$1"
            else
                echo "Error: Unexpected argument '$1'." >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "Error: Target block device is required." >&2
    echo "Usage: $0 [OPTIONS] <TARGET_DEVICE>" >&2
    echo "Run '$0 --help' for details." >&2
    exit 1
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
        "aeth-os-live-amd64.hybrid.iso"
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
        for f in "${dir}"/*.hybrid.iso "${dir}"/*.iso; do
            if [ -f "$f" ]; then
                echo "$f"
                return 0
            fi
        done
    done

    if [ "$DRY_RUN" = true ]; then
        echo "aeth-os-live-amd64.hybrid.iso"
        return 0
    fi

    echo "Error: No ISO image found in '$PWD' or '$REPO_ROOT'." >&2
    echo "Please build the live image using 'make build' or specify '--iso <path>'." >&2
    return 1
}

# Calculate partition node path based on device naming conventions
get_part_dev() {
    local disk="$1"
    local num="$2"
    if [[ "$disk" =~ [0-9]$ ]]; then
        echo "${disk}p${num}"
    else
        echo "${disk}${num}"
    fi
}

PART1=$(get_part_dev "$TARGET" 1)
PART2=$(get_part_dev "$TARGET" 2)
PART3=$(get_part_dev "$TARGET" 3)

# Safety Validation
verify_safety() {
    local target="$1"

    # 1. Block device check
    if [ -e "$target" ]; then
        if [ ! -b "$target" ]; then
            echo "Error: Target '$target' is not a valid block device." >&2
            return 1
        fi
    else
        # Device node doesn't exist
        if [ "$DRY_RUN" = true ]; then
            if [[ "$target" =~ ^/dev/ ]]; then
                echo "Notice: Target '$target' does not currently exist. Proceeding in dry-run mode." >&2
            else
                echo "Error: Target '$target' is not a valid block device." >&2
                return 1
            fi
        else
            echo "Error: Target '$target' is not a valid block device (does not exist)." >&2
            return 1
        fi
    fi

    # 2. Critical System Disk Protection
    # Determine the target base disk name (e.g. sda from /dev/sda or /dev/sda1)
    local target_real
    target_real=$(readlink -f "$target" 2>/dev/null || echo "$target")
    local target_parent
    target_parent=$(lsblk -dno PKNAME "$target_real" 2>/dev/null || true)
    local target_name
    target_name=$(lsblk -dno NAME "$target_real" 2>/dev/null || basename "$target_real")
    local target_base="${target_parent:-$target_name}"

    local critical_mounts=("/" "/boot" "/boot/efi" "/home" "/root" "/usr" "/var" "/etc")

    # Scan lsblk for active mounts across all block devices
    if command -v lsblk >/dev/null 2>&1; then
        while read -r pkname name mnts; do
            [ -z "$mnts" ] && continue
            local expanded
            expanded=$(echo -e "${mnts//\\x/\\x}")
            local dev_base="${pkname:-$name}"

            for m in $expanded; do
                for crit in "${critical_mounts[@]}"; do
                    if [ "$m" = "$crit" ]; then
                        if [ "$dev_base" = "$target_base" ] || [ "$name" = "$target_name" ] || [ "$dev_base" = "$target_name" ]; then
                            echo "Error: Target device '$target' (disk: $target_base) contains active critical system mount '$crit' on '/dev/$name'!" >&2
                            echo "Refusing to overwrite active system disk." >&2
                            return 1
                        fi
                    fi
                done
            done
        done < <(lsblk -rn -o PKNAME,NAME,MOUNTPOINTS 2>/dev/null || true)
    fi

    # Also check /proc/mounts / df for active critical mounts
    if [ -f /proc/mounts ]; then
        while read -r fs mnt _; do
            for crit in "${critical_mounts[@]}"; do
                if [ "$mnt" = "$crit" ]; then
                    local fs_real
                    fs_real=$(readlink -f "$fs" 2>/dev/null || echo "$fs")
                    if [ "$fs_real" = "$target_real" ] || [[ "$fs_real" == "${target_real}"* ]]; then
                        echo "Error: Target device '$target' is mounted at critical mountpoint '$crit'! Refusing to overwrite." >&2
                        return 1
                    fi
                fi
            done
        done < /proc/mounts
    fi

    return 0
}

# Run safety verification before attempting to search/load ISO or check root
if ! verify_safety "$TARGET"; then
    exit 1
fi

# Handle Dry-Run Mode (does not require root privileges or existing ISO file)
if [ "$DRY_RUN" = true ]; then
    RESOLVED_ISO=$(find_iso)
    echo "======================================================================"
    echo " [DRY-RUN] AgenticOS USB Flash Execution Plan"
    echo "======================================================================"
    echo " Target Device:       $TARGET"
    echo " Source ISO Image:    $RESOLVED_ISO"
    echo " Persistence Label:   $PERSISTENCE_LABEL"
    echo " Partition Layout:"
    echo "   - $PART1: 512MiB EFI System Partition (FAT32, label: EFI-LIVE, flags: boot,esp)"
    echo "   - $PART2: 4096MiB Live System Partition (raw ISO copy)"
    echo "   - $PART3: Remaining space Ext4 Persistence (label: $PERSISTENCE_LABEL, commit=60)"
    echo "======================================================================"
    echo "[DRY-RUN] Planned Commands:"
    echo "  umount ${TARGET}* 2>/dev/null || true"
    echo "  wipefs --all --force $TARGET"
    echo "  parted -s $TARGET mklabel gpt"
    echo "  parted -s $TARGET mkpart \"EFI-LIVE\" fat32 1MiB 513MiB"
    echo "  parted -s $TARGET set 1 esp on"
    echo "  parted -s $TARGET set 1 boot on"
    echo "  parted -s $TARGET mkpart \"AgenticOS-Live\" 513MiB 4609MiB"
    echo "  parted -s $TARGET mkpart \"$PERSISTENCE_LABEL\" ext4 4609MiB 100%"
    echo "  partprobe $TARGET"
    echo "  udevadm settle"
    echo "  mkfs.vfat -F 32 -n \"EFI-LIVE\" $PART1"
    echo "  dd if=$RESOLVED_ISO of=$PART2 bs=4M status=progress conv=fsync"
    echo "  mkfs.ext4 -F -L $PERSISTENCE_LABEL -E lazy_itable_init=0,lazy_journal_init=0 $PART3"
    echo "  tune2fs -o journal_data_writeback $PART3"
    echo "  TMP_MNT=\$(mktemp -d /tmp/agentic-persist-XXXXXX)"
    echo "  mount -o commit=60 $PART3 \$TMP_MNT"
    echo "  echo \"/ union\" > \$TMP_MNT/persistence.conf"
    echo "  sync"
    echo "  umount \$TMP_MNT"
    echo "  rmdir \$TMP_MNT"
    echo "======================================================================"
    exit 0
fi

# Privilege verification for real execution
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: Root privileges required to partition and write to block devices." >&2
    echo "Please re-run with sudo: sudo $0 $*" >&2
    exit 1
fi

RESOLVED_ISO=$(find_iso)

# User Confirmation Prompt
if [ "$ASSUME_YES" = false ]; then
    echo "======================================================================"
    echo " WARNING: ALL DATA ON $TARGET WILL BE PERMANENTLY DESTROYED!"
    echo "======================================================================"
    if command -v lsblk >/dev/null 2>&1; then
        lsblk "$TARGET" 2>/dev/null || true
    fi
    echo "======================================================================"

    if [ ! -t 0 ]; then
        echo "Error: Interactive confirmation required. Pass --yes / -y to confirm in non-interactive environments." >&2
        exit 1
    fi

    read -r -p "Are you sure you want to completely erase and flash $TARGET? Type 'YES' to continue: " confirm
    if [ "$confirm" != "YES" ] && [ "$confirm" != "yes" ] && [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Operation cancelled by user."
        exit 1
    fi
fi

# Check required binaries
for cmd in parted mkfs.vfat mkfs.ext4 tune2fs dd wipefs udevadm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: Required command '$cmd' is not installed or not in PATH." >&2
        exit 1
    fi
done

echo "==> Step 1: Unmounting active partitions on $TARGET..."
umount "${TARGET}"* 2>/dev/null || true

echo "==> Step 2: Wiping existing partition signatures..."
wipefs --all --force "$TARGET" || dd if=/dev/zero of="$TARGET" bs=1M count=10 conv=fsync

echo "==> Step 3: Creating GPT partition table..."
parted -s "$TARGET" mklabel gpt

echo "==> Step 4: Creating EFI System Partition (512MiB)..."
parted -s "$TARGET" mkpart "EFI-LIVE" fat32 1MiB 513MiB
parted -s "$TARGET" set 1 esp on
parted -s "$TARGET" set 1 boot on

echo "==> Step 5: Creating Live OS Partition (4096MiB)..."
parted -s "$TARGET" mkpart "AgenticOS-Live" 513MiB 4609MiB

echo "==> Step 6: Creating Persistence Partition (Remainder of drive)..."
parted -s "$TARGET" mkpart "$PERSISTENCE_LABEL" ext4 4609MiB 100%

echo "==> Step 7: Notifying kernel of partition changes..."
partprobe "$TARGET" 2>/dev/null || true
udevadm settle || sleep 1

echo "==> Step 8: Formatting EFI System Partition as FAT32 (EFI-LIVE)..."
mkfs.vfat -F 32 -n "EFI-LIVE" "$PART1"

echo "==> Step 9: Writing Live ISO to Live OS Partition ($PART2)..."
dd if="$RESOLVED_ISO" of="$PART2" bs=4M status=progress conv=fsync

echo "==> Step 10: Formatting Persistence Partition as Ext4 ($PERSISTENCE_LABEL)..."
mkfs.ext4 -F -L "$PERSISTENCE_LABEL" -E lazy_itable_init=0,lazy_journal_init=0 "$PART3"

echo "==> Step 11: Applying flash longevity optimizations..."
tune2fs -o journal_data_writeback "$PART3"

echo "==> Step 12: Initializing persistence.conf (/ union)..."
TMP_MNT=$(mktemp -d /tmp/agentic-persist-XXXXXX)
mount -o commit=60 "$PART3" "$TMP_MNT"
echo "/ union" > "$TMP_MNT/persistence.conf"
sync
umount "$TMP_MNT"
rmdir "$TMP_MNT"

echo "======================================================================"
echo " SUCCESS: AgenticOS USB flash completed successfully on $TARGET!"
echo " Bootable EFI: $PART1 (EFI-LIVE)"
echo " Live System:  $PART2"
echo " Persistence:  $PART3 ($PERSISTENCE_LABEL, / union)"
echo "======================================================================"
