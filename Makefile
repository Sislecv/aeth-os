.DEFAULT_GOAL := help

SUDO ?= $(shell if [ "$$(id -u)" != "0" ]; then echo "sudo"; fi)
DEVICE ?=

.PHONY: all config build clean test-qemu flash-usb help

all: config build

config:
	@echo "==> Configuring live-build environment..."
	./auto/config

build:
	@echo "==> Building Aeth OS Live ISO..."
	$(SUDO) ./auto/build

clean:
	@echo "==> Cleaning live-build artifacts..."
	$(SUDO) ./auto/clean

test-qemu:
	@if [ -f scripts/test-qemu.sh ]; then \
		./scripts/test-qemu.sh; \
	else \
		echo "scripts/test-qemu.sh not found."; \
		exit 1; \
	fi

flash-usb:
	@if [ -z "$(DEVICE)" ]; then \
		echo "Error: DEVICE variable is required. Example: make flash-usb DEVICE=/dev/sdX"; \
		exit 1; \
	fi
	@if [ -f scripts/flash-usb.sh ]; then \
		$(SUDO) ./scripts/flash-usb.sh $(DEVICE); \
	else \
		echo "scripts/flash-usb.sh not found."; \
		exit 1; \
	fi

help:
	@echo "Aeth OS Build System"
	@echo ""
	@echo "Usage:"
	@echo "  make [target] [DEVICE=/dev/sdX]"
	@echo ""
	@echo "Targets:"
	@echo "  help        Display this help message (default)"
	@echo "  all         Configure and build the ISO image"
	@echo "  config      Run live-build configuration (auto/config)"
	@echo "  build       Build the live ISO image (auto/build, requires root)"
	@echo "  clean       Purge live-build cache and artifacts (auto/clean, requires root)"
	@echo "  test-qemu   Launch local QEMU virtual machine for testing"
	@echo "  flash-usb   Flash ISO and setup persistence on USB drive (requires DEVICE=/dev/sdX)"
	@echo ""
