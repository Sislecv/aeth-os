# AgenticOS 实现计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 Debian 的随身 U 盘 AI 原生操作系统工程（`agentic-os/`），集成 Material 3 风格的精简版 GNOME、幽灵桌面 Computer Use、无障碍树 Browser Use、Zellij 伴生 Pi Agent（带 5 大专属技能）、以及 F5 本地离线语音识别输入法。

**Architecture:** 基于 Debian `live-build` 工具链打造混合 UEFI/BIOS 双引导的只读 SquashFS 系统镜像，配合 Ext4/LUKS OverlayFS 持久化数据层；桌面端集成原生 AT-SPI2 辅助功能总线与 Mutter 虚拟显示网关；终端采用 Zellij 65:35 双向伴生分屏，右侧常驻 Pi Agent（`@earendil-works/pi-coding-agent`）；语音端集成 `whisper.cpp` 与 `Blurt` GNOME 原生扩展。

**Tech Stack:** Debian 12/13 (live-build, systemd, OverlayFS, zram-tools), GNOME Shell (Mutter, Wayland, AT-SPI2, libei), Material Design 3, FiraCode/JetBrainsMono Nerd Fonts, Zellij, agent-browser (CDP, a11y tree), whisper.cpp (Blurt, PipeWire), Pi Agent (@earendil-works/pi-coding-agent), Python 3, Bash.

**Spec:** [`docs/superpowers/specs/2026-09-19-agentic-os-design.md`](file:///home/sislecv2/docs/superpowers/specs/2026-09-19-agentic-os-design.md)

## Global Constraints
- Target architecture: x86_64 PC compatible (UEFI + Legacy BIOS hybrid boot).
- Storage layout: ESP (FAT32, 512MB) + SquashFS RO root (4GB) + persistence (Ext4, `noatime,commit=60`).
- Memory baseline: Direct-Stream on-demand paging (cold boot RAM ≤ 750MB, leaving 85%+ RAM for local LLMs/dev).
- Desktop UX: Material Design 3 theme, Papirus-Material icons, FiraCode Nerd Font with ligatures, inactive window dimming, Zen mode (`Super+F11`).
- Computer Use: Ghost Workspace 2 isolation (zero focus stealing from Workspace 1), AT-SPI2 event-driven IPC.
- Browser Use: Chromium + `agent-browser` a11y snapshot (`@eN` refs) + session persistence.
- Voice Input: `whisper.cpp` + `Blurt` GNOME extension, `F5` toggle with VAD 1.0s auto-stop, `Super+F5` direct Pi prompt.
- Pi Agent: `@earendil-works/pi-coding-agent`, 5 custom skills (`computer-use`, `browser-use`, `agent-memory`, `os-admin`, `terminal-sync`), direct user model configuration without menus.

---

### Task 1: 工程骨架与构建自动化 (Repository Scaffolding & Live-Build Core)

**Files:**
- Create: `agentic-os/Makefile`
- Create: `agentic-os/auto/config`
- Create: `agentic-os/auto/build`
- Create: `agentic-os/auto/clean`

**Interfaces:**
- Consumes: Linux host package manager (`live-build`, `debootstrap`).
- Produces: `agentic-os-live-amd64.hybrid.iso` 构建流水线与基本自动化命令（`make build`, `make clean`）。

- [ ] **Step 1: 编写 Makefile 自动化驱动**
  实现一键 build、clean、test-qemu、flash-usb 目标。
- [ ] **Step 2: 编写 auto/config 预设**
  配置 `lb config --mode debian --distribution bookworm --architectures amd64 --archive-areas "main contrib non-free non-free-firmware" --bootloader grub-efi`。
- [ ] **Step 3: 编写 auto/build 与 auto/clean**
  标准调用 `lb build` 与 `lb clean --purge`。
- [ ] **Step 4: 验证构建脚本语法与权限**
  赋权 `chmod +x auto/*` 并执行 `make -n` 校验流程。

---

### Task 2: 声明式软件包清单配置 (Debian Package Lists)

**Files:**
- Create: `agentic-os/config/package-lists/00-base.list.chroot`
- Create: `agentic-os/config/package-lists/01-firmware.list.chroot`
- Create: `agentic-os/config/package-lists/02-desktop.list.chroot`
- Create: `agentic-os/config/package-lists/03-terminal.list.chroot`
- Create: `agentic-os/config/package-lists/04-browser.list.chroot`
- Create: `agentic-os/config/package-lists/05-voice.list.chroot`
- Create: `agentic-os/config/package-lists/06-agentic.list.chroot`

**Interfaces:**
- Consumes: Debian 官方源与 non-free-firmware。
- Produces: 目标 Live 镜像所需的全部二进制包依赖清单。

- [ ] **Step 1: 编写 00-base.list.chroot 与 01-firmware.list.chroot**
  包含 `linux-image-amd64`, `systemd-sysv`, `live-boot`, `live-config`, `zram-tools`, `btrfs-progs`, `firmware-linux`, `firmware-iwlwifi`, `firmware-realtek`, `mesa-vulkan-drivers` 等。
- [ ] **Step 2: 编写 02-desktop.list.chroot 与 03-terminal.list.chroot**
  包含精简版 `gnome-core`, `mutter`, `gdm3`, `at-spi2-core`, `papirus-icon-theme`, `fonts-firacode`, `ptyxis`, `zellij`, `zsh`, `git`, `ripgrep`, `jq` 等。
- [ ] **Step 3: 编写 04-browser.list.chroot、05-voice.list.chroot、06-agentic.list.chroot**
  包含 `chromium`, `pipewire`, `pipewire-audio-client-libraries`, `libcanberra-gtk3-module`, `wtype`, `python3-pyatspi`, `python3-pip`, `nodejs`, `npm`, `libei1` 等。
- [ ] **Step 4: 运行包清单格式检查脚本**
  确保每个清单无重复包名且行尾无多余空白。

---

### Task 3: Material Design 3、Nerd Fonts 与 GNOME 专注体验预设 (Desktop Theming & Focus)

**Files:**
- Create: `agentic-os/config/includes.chroot/etc/dconf/db/local.d/01-material-theme`
- Create: `agentic-os/config/includes.chroot/etc/dconf/db/local.d/02-zen-focus`
- Create: `agentic-os/config/hooks/live/0050-install-nerd-fonts.hook.chroot`

**Interfaces:**
- Consumes: GNOME GSettings / dconf 架构。
- Produces: 开机即生效的 Material 3 深色主题、FiraCode 编程连字、非活动窗口微压暗与 `Super+F11` 禅模式快捷键。

- [ ] **Step 1: 编写 01-material-theme dconf 配置文件**
  设置 GTK 主题、Papirus 图标、Roboto/Inter 界面字体、FiraCode Nerd Font 终端字体，启用全局 toolkit-accessibility。
- [ ] **Step 2: 编写 02-zen-focus 快捷键与视线聚焦预设**
  绑定 `Super+F11` 禅模式动作，配置非活动窗口暗化参数与 Material 标准动画时长。
- [ ] **Step 3: 编写 0050-install-nerd-fonts.hook.chroot 脚本**
  自动下载并安装完整带 Devicons 图标字形的 `FiraCode Nerd Font` 与 `JetBrainsMono Nerd Font` 到 `/usr/share/fonts/truetype/nerd-fonts/` 并更新字体缓存 (`fc-cache -fv`)。
- [ ] **Step 4: 校验 dconf update 与字体配置指令**
  在宿主机测试脚本解析无误。

---

### Task 4: 幽灵桌面 (Ghost Workspace) 与 Computer Use 网关服务 (Computer Use Gateway)

**Files:**
- Create: `agentic-os/config/includes.chroot/usr/local/bin/computer-use-gateway`
- Create: `agentic-os/config/includes.chroot/etc/systemd/user/computer-use-gateway.service`
- Create: `agentic-os/config/includes.chroot/usr/local/bin/ghost-workspace-helper`

**Interfaces:**
- Consumes: AT-SPI2 D-Bus (`org.a11y.Bus`), Mutter ScreenCast, libei / wtype 虚拟输入。
- Produces: 本地 Unix Socket / HTTP RPC 接口，为 Pi Agent 提供 `inspect_tree`, `click_element`, `click_coords`, `type_text`, `screenshot`。

- [ ] **Step 1: 实现 ghost-workspace-helper 脚本**
  利用 GNOME Shell D-Bus 接口或 Mutter 协议，在后台初始化/管理 Workspace 2（幽灵工作区），支持在不夺取 Workspace 1 焦点的前提下启动与绑定目标窗口。
- [ ] **Step 2: 编写 computer-use-gateway 守护服务 (Python)**
  基于 `pyatspi` 实现毫秒级 UI 控件树遍历与绝对坐标计算；基于 PipeWire/ScreenCast 实现全高清截图；基于 `libei`/`wtype` 注入物理按键与鼠标。
- [ ] **Step 3: 配置 systemd user service**
  配置 `computer-use-gateway.service` 用户级自启与异常重启策略。
- [ ] **Step 4: 编写独立测试脚本 test-gateway.py**
  本地模拟调用 `--dump-tree` 和 `--screenshot` 验证功能闭环。

---

### Task 5: 优化版 Browser Use 栈与会话持久化集成 (Browser Use Stack)

**Files:**
- Create: `agentic-os/config/includes.chroot/usr/local/bin/agentic-browser-launcher`
- Create: `agentic-os/config/hooks/live/0060-install-agent-browser.hook.chroot`

**Interfaces:**
- Consumes: Chromium, CDP (`--remote-debugging-port`), `@agent-browser` CLI。
- Produces: 紧凑无障碍树快照（`@eN` 引用）与持久化 Cookie/Session 目录。

- [ ] **Step 1: 编写 0060-install-agent-browser.hook.chroot**
  全局安装 `npm install -g agent-browser` 并执行 `agent-browser install --with-deps`。
- [ ] **Step 2: 编写 agentic-browser-launcher 脚本**
  自动挂载持久化分区下的用户数据目录（`~/.config/agentic/browser/`），配置 CDP 端口 9222，支持 `--headless` 后台模式与 `--headed` 幽灵工作区投屏。
- [ ] **Step 3: 测试 agent-browser 命令链**
  验证 `agent-browser open`, `snapshot -i`, `click @eN` 的执行逻辑。

---

### Task 6: Zellij 65:35 终端伴生布局与 Shell Hooks (Terminal Companion)

**Files:**
- Create: `agentic-os/config/includes.chroot/etc/zellij/agentic.kdl`
- Create: `agentic-os/config/includes.chroot/etc/agentic/shell-hooks.sh`
- Create: `agentic-os/config/includes.chroot/usr/local/bin/agentic-terminal`

**Interfaces:**
- Consumes: Zellij, Bash / Zsh 语法。
- Produces: 打开终端自动分屏：左侧 Shell (65%) + 右侧 Pi Agent (35%)，支持命令退出码异常通知与快捷键 (`Alt+A`, `Alt+B`, `Alt+C`)。

- [ ] **Step 1: 编写 agentic.kdl 布局**
  配置默认 Tab，左侧主 Pane 运行默认交互 Shell，右侧 Pane 启动 `pi` 交互式环境，底栏配置快捷键提示。
- [ ] **Step 2: 编写 shell-hooks.sh**
  使用 `preexec` 和 `PROMPT_COMMAND`（Bash）与 `precmd`（Zsh）检测命令退出码，失败时向 `/run/user/$UID/agentic.sock` 发送诊断事件。
- [ ] **Step 3: 编写快捷键绑定与投递机制**
  实现 `Alt+A`（提交当前命令行）、`Alt+B`（捕获最后 50 行输出）、`Alt+C`（呼叫 Computer Use）。
- [ ] **Step 4: 编写 agentic-terminal 启动包装器**
  检查并连接现有会话或以 `agentic.kdl` 启动新 Zellij 会话。

---

### Task 7: Pi Agent 专属 5 大 Skills 体系与模型配置 (Pi Agent & Skills)

**Files:**
- Create: `agentic-os/config/hooks/live/0070-install-pi-agent.hook.chroot`
- Create: `agentic-os/config/includes.chroot/etc/pi/skills/skill-computer-use/index.ts`
- Create: `agentic-os/config/includes.chroot/etc/pi/skills/skill-browser-use/index.ts`
- Create: `agentic-os/config/includes.chroot/etc/pi/skills/skill-agent-memory/index.ts`
- Create: `agentic-os/config/includes.chroot/etc/pi/skills/skill-os-admin/index.ts`
- Create: `agentic-os/config/includes.chroot/etc/pi/skills/skill-terminal-sync/index.ts`

**Interfaces:**
- Consumes: `@earendil-works/pi-coding-agent`, `computer-use-gateway`, `agent-browser`。
- Produces: Pi 专属的 5 个可调用的 Skills 工具包，支持自由通过环境变量或 `~/.config/pi/` 配置模型。

- [ ] **Step 1: 编写 0070-install-pi-agent.hook.chroot**
  全局安装 `@earendil-works/pi-coding-agent`，将 `/etc/pi/skills/` 链接到默认用户目录。
- [ ] **Step 2: 编写 skill-computer-use**
  实现 `desktop_inspect_tree`, `desktop_click_element`, `desktop_screenshot` 工具定义与 RPC 调用。
- [ ] **Step 3: 编写 skill-browser-use**
  封装调用 `agent-browser snapshot -i`, `click @eN`, `fill @eN` 的交互工具。
- [ ] **Step 4: 编写 skill-agent-memory 与 skill-os-admin**
  实现 SQLite 记忆存储与 `pi-doctor` 硬件检测调度。
- [ ] **Step 5: 编写 skill-terminal-sync**
  实现通过 Zellij CLI 读取左侧 Pane 视口与写入确认命令。

---

### Task 8: 本地离线语音识别输入法与 GNOME 原生 UI (Local Voice Engine)

**Files:**
- Create: `agentic-os/config/hooks/live/0080-setup-blurt-voice.hook.chroot`
- Create: `agentic-os/config/includes.chroot/etc/dconf/db/local.d/03-blurt-voice`
- Create: `agentic-os/config/includes.chroot/usr/local/bin/agentic-voice-agent`

**Interfaces:**
- Consumes: `whisper.cpp`, `Blurt` GNOME Shell Extension, PipeWire。
- Produces: 按 `F5` 启动录音，VAD 停顿 1.0s 自动上屏；按 `Super+F5` 直接向 Pi Agent 发送语音 Prompt。

- [ ] **Step 1: 编写 0080-setup-blurt-voice.hook.chroot**
  自动编译/安装 `whisper.cpp` 运行时，下载并预置 `ggml-base.bin` (~140MB) 中英双语离线模型至 `/usr/share/agentic/models/whisper/`，预解压部署 `Blurt` GNOME 扩展。
- [ ] **Step 2: 编写 03-blurt-voice dconf 配置**
  强制配置快捷键为 `F5`，开启 VAD 1.0s 停顿自动断句与 `auto-paste=true`。
- [ ] **Step 3: 编写 agentic-voice-agent 脚本与 Super+F5 映射**
  监听 `Super+F5` 全局组合键，截获语音转录后通过 IPC Socket 直接输入右侧 Pi Agent 提示符。
- [ ] **Step 4: 验证 whisper.cpp 本地转录与按键触发逻辑**
  在本地环境验证测试音频输入与文字输出。

---

### Task 9: 系统级运维工具与用户环境初始化 (System Tools & Live Hook)

**Files:**
- Create: `agentic-os/config/includes.chroot/usr/local/bin/pi-doctor`
- Create: `agentic-os/config/includes.chroot/usr/local/bin/pi-net`
- Create: `agentic-os/config/hooks/live/0099-setup-agentic-user.hook.chroot`

**Interfaces:**
- Consumes: NetworkManager CLI, systemd, udev, procfs。
- Produces: `pi doctor` 硬件体检与 WiFi 配网工具，完成默认用户 `user` 权限配置（`sudo`, `input`, `video`, `audio` 免密）。

- [ ] **Step 1: 编写 pi-doctor CLI 脚本**
  输出 CPU 状态、物理 RAM 剩余容量、GPU 硬件加速（Vulkan/VA-API）、电池、U 盘持久化分区读写健康度。
- [ ] **Step 2: 编写 pi-net 智能配网脚本**
  基于 `nmcli` 提供交互式或自动化 WiFi 扫描与连接。
- [ ] **Step 3: 编写 0099-setup-agentic-user.hook.chroot**
  配置默认用户免密 sudo，添加进关键设备组，启用 zramswap（zstd），配置持久化目录权限。
- [ ] **Step 4: 校验脚本运行权限与语法**
  执行 `bash -n` 确保无语法缺陷。

---

### Task 10: 自动化物理 U 盘烧录与本地 QEMU 测试套件 (Flash & Test Tooling)

**Files:**
- Create: `agentic-os/scripts/flash-usb.sh`
- Create: `agentic-os/scripts/test-qemu.sh`

**Interfaces:**
- Consumes: `agentic-os-live-amd64.hybrid.iso`, QEMU / KVM, `parted`, `mkfs.ext4`。
- Produces: 一键在物理 U 盘上创建 EFI + ISO + Persistence 分区，或在本地虚拟机中秒级启动验证。

- [ ] **Step 1: 编写 test-qemu.sh 快速验证脚本**
  支持启动 KVM 硬件加速，模拟 UEFI 固件与双显示器/鼠标设备，测试 Wayland 桌面与无障碍启动。
- [ ] **Step 2: 编写 flash-usb.sh 自动化烧录脚本**
  安全检查目标盘设备号（防误格式化本机硬盘），执行 GPT 分区：
  1. p1: 512MB EFI (FAT32)
  2. p2: 4GB LIVE (ISO 镜像写入)
  3. p3: 剩余空间 (Ext4，卷标 `persistence`，写入 `/ union` 与 `commit=60` 参数)
- [ ] **Step 3: 运行完整端到端测试与语法静态检查**
  确保所有脚本与工具链就绪。

---
