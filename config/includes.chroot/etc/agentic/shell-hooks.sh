#!/usr/bin/env bash
# /etc/agentic/shell-hooks.sh
# AgenticOS Shell Integration & Terminal Companion Hooks
# Compatible with Bash (4.0+) and Zsh (5.0+)
#
# Key Capabilities:
# 1. Captures previous command and exit code via PROMPT_COMMAND / precmd.
# 2. Non-blocking error diagnosis event dispatch to /run/user/$UID/agentic.sock on exit code != 0.
# 3. Dedicated keybindings & helper functions for Zellij companion pane interaction:
#    - Alt+A: Send command line to Pi Agent companion
#    - Alt+B: Capture and send last 50 lines of logs to Pi Agent companion
#    - Alt+C: Call Computer Use Agent on Ghost Workspace (Workspace 2)

# Prevent duplicate sourcing
if [ "${_AGENTIC_SHELL_HOOKS_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || true
fi
_AGENTIC_SHELL_HOOKS_LOADED=1

# Resolve active Agentic IPC socket path
_agentic_get_sock() {
    if [ -n "${AGENTIC_SOCK:-}" ]; then
        echo "$AGENTIC_SOCK"
        return 0
    fi
    local uid
    uid="${UID:-$(id -u 2>/dev/null || echo 1000)}"
    if [ -S "/run/user/$uid/agentic.sock" ]; then
        echo "/run/user/$uid/agentic.sock"
        return 0
    fi
    if [ -S "/tmp/agentic-$uid.sock" ]; then
        echo "/tmp/agentic-$uid.sock"
        return 0
    fi
    if [ -d "/run/user/$uid" ]; then
        echo "/run/user/$uid/agentic.sock"
    else
        echo "/tmp/agentic-$uid.sock"
    fi
}

# Non-blocking event emitter to Agentic IPC socket
_agentic_emit_event() {
    local sock
    sock="$(_agentic_get_sock)"
    [ -S "$sock" ] || return 0

    local event_type="$1"
    shift

    _agentic_do_dispatch() {
        if command -v python3 >/dev/null 2>&1; then
            python3 -c '
import socket, sys, json, os, time

sock_path = sys.argv[1]
event_type = sys.argv[2]
fields = {
    "event": event_type,
    "cwd": os.getcwd(),
    "timestamp": int(time.time()),
    "shell": os.path.basename(os.environ.get("SHELL", "sh"))
}

for item in sys.argv[3:]:
    if "=" in item:
        k, v = item.split("=", 1)
        if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
            fields[k] = int(v)
        else:
            fields[k] = v

try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.3)
    s.connect(sock_path)
    s.sendall(json.dumps(fields).encode("utf-8") + b"\n")
    s.close()
except Exception:
    pass
' "$sock" "$event_type" "$@" 2>/dev/null
        elif command -v nc >/dev/null 2>&1; then
            printf '{"event":"%s","cwd":"%s","timestamp":%s}\n' \
                "$event_type" "${PWD:-}" "$(date +%s 2>/dev/null || echo 0)" | nc -U -w 1 "$sock" 2>/dev/null || true
        fi
    }

    if [ "${AGENTIC_SYNC_SEND:-0}" = "1" ]; then
        _agentic_do_dispatch "$@"
    else
        ( _agentic_do_dispatch "$@" ) &
        disown $! 2>/dev/null || true
    fi
}

# Handles command termination, evaluating exit code
_agentic_on_command_complete() {
    local exit_code="$1"
    local cmd="$2"

    # Ignore empty commands or blank lines
    [ -z "$cmd" ] && return 0

    # Only fire failure diagnostics on non-zero exit code
    if [ "$exit_code" -ne 0 ]; then
        _agentic_emit_event "command_failed" \
            "type=error_diagnosis" \
            "command=$cmd" \
            "exit_code=$exit_code"
    fi
}

# Helper to send text into the Zellij companion pane (Pi)
_agentic_zellij_forward() {
    local text="$1"
    if command -v zellij >/dev/null 2>&1 && [ -n "${ZELLIJ:-}" ]; then
        zellij action move-focus right 2>/dev/null || zellij action focus-next-pane 2>/dev/null || true
        zellij action write-chars "$text" 2>/dev/null || true
        zellij action write 10 2>/dev/null || true
        zellij action move-focus left 2>/dev/null || zellij action focus-previous-pane 2>/dev/null || true
    fi
}

# Alt+A: Send command line to Pi Agent companion
agentic_send_command() {
    local cmd="${1:-}"

    if [ -z "$cmd" ]; then
        if [ -n "${READLINE_LINE:-}" ]; then
            cmd="$READLINE_LINE"
        elif [ -n "${BUFFER:-}" ]; then
            cmd="$BUFFER"
        elif [ -n "${_AGENTIC_LAST_COMMAND:-}" ]; then
            cmd="$_AGENTIC_LAST_COMMAND"
        else
            cmd="$(fc -ln -1 2>/dev/null | sed -e 's/^[[:space:]]*//')"
        fi
    fi

    [ -z "$cmd" ] && return 0

    _agentic_emit_event "user_command_submit" \
        "action=send_command" \
        "command=$cmd"

    _agentic_zellij_forward "$cmd"

    # Clear interactive readline buffer if invoked via keybind
    if [ -n "${READLINE_LINE:-}" ]; then
        READLINE_LINE=""
        READLINE_POINT=0
    fi
}

# Alt+B: Capture and send last 50 lines of logs to Pi Agent companion
agentic_send_logs() {
    local lines="${1:-50}"
    local logs=""

    if command -v zellij >/dev/null 2>&1 && [ -n "${ZELLIJ:-}" ]; then
        local tmp_dump="/tmp/agentic-screen-$$.txt"
        zellij action dump-screen "$tmp_dump" 2>/dev/null || true
        if [ -f "$tmp_dump" ]; then
            logs="$(tail -n "$lines" "$tmp_dump" 2>/dev/null || true)"
            rm -f "$tmp_dump" 2>/dev/null || true
        fi
    fi

    if [ -z "$logs" ]; then
        logs="$(fc -ln -"$lines" 2>/dev/null || tail -n "$lines" "${HISTFILE:-$HOME/.bash_history}" 2>/dev/null || true)"
    fi

    _agentic_emit_event "terminal_logs" \
        "action=send_logs" \
        "lines=$lines" \
        "logs=$logs"

    local prompt_msg="Analyze recent terminal output (last $lines lines):"
    if [ -n "$logs" ]; then
        _agentic_zellij_forward "$prompt_msg"$'\n'"$logs"
    else
        _agentic_zellij_forward "$prompt_msg"
    fi

    if [ -t 1 ]; then
        printf "\033[1;32m[Agentic OS]\033[0m Forwarded last %s lines of logs to Pi companion.\n" "$lines" >&2
    fi
}

# Alt+C: Call Computer Use Agent on Ghost Workspace (Workspace 2)
agentic_call_computer_use() {
    local task="${1:-Perform requested task on Ghost Workspace}"

    _agentic_emit_event "ghost_computer_use" \
        "action=call_computer_use" \
        "task=$task"

    _agentic_zellij_forward "Activate Ghost Computer Use on Workspace 2: $task"

    if command -v ghost-workspace-helper >/dev/null 2>&1; then
        ghost-workspace-helper switch 1 2>/dev/null || true
    fi

    if [ -t 1 ]; then
        printf "\033[1;35m[Agentic OS]\033[0m Ghost Computer Use triggered on Workspace 2.\n" >&2
    fi
}

# Status and inspection helper
agentic_status() {
    local sock
    sock="$(_agentic_get_sock)"
    printf "Agentic Shell Integration Status:\n"
    printf "  Shell:           %s\n" "${SHELL:-sh}"
    printf "  IPC Socket:      %s " "$sock"
    if [ -S "$sock" ]; then
        printf "(\033[1;32mCONNECTED\033[0m)\n"
    else
        printf "(\033[1;33mNOT LISTENING\033[0m)\n"
    fi
    printf "  Zellij Active:   %s\n" "${ZELLIJ:-no}"
    printf "  Keybindings:     Alt+A (Send Command), Alt+B (Send Logs), Alt+C (Computer Use)\n"
}

# ---------------------------------------------------------
# Shell Specific Hooks: Bash
# ---------------------------------------------------------
if [ -n "${BASH_VERSION:-}" ]; then
    _agentic_bash_prompt_command() {
        local exit_code=$?
        _AGENTIC_IN_PROMPT=1
        local cmd="${_AGENTIC_LAST_COMMAND:-}"
        if [ -z "$cmd" ]; then
            cmd="$(fc -ln -1 2>/dev/null | sed -e 's/^[[:space:]]*//')"
        fi
        _agentic_on_command_complete "$exit_code" "$cmd"
        _AGENTIC_LAST_COMMAND=""
        _AGENTIC_IN_PROMPT=0
        return $exit_code
    }

    _agentic_bash_debug_trap() {
        if [ "${_AGENTIC_IN_PROMPT:-0}" -eq 0 ]; then
            _AGENTIC_LAST_COMMAND="${BASH_COMMAND:-}"
        fi
    }

    trap '_agentic_bash_debug_trap' DEBUG

    if [[ ! "${PROMPT_COMMAND:-}" =~ _agentic_bash_prompt_command ]]; then
        if [ -z "${PROMPT_COMMAND:-}" ]; then
            PROMPT_COMMAND="_agentic_bash_prompt_command"
        else
            PROMPT_COMMAND="_agentic_bash_prompt_command; ${PROMPT_COMMAND}"
        fi
    fi

    # Readline Keybindings for Bash in interactive mode
    if [[ $- == *i* ]]; then
        bind -x '"\ea": agentic_send_command' 2>/dev/null || true
        bind -x '"\eA": agentic_send_command' 2>/dev/null || true
        bind -x '"\eb": agentic_send_logs' 2>/dev/null || true
        bind -x '"\eB": agentic_send_logs' 2>/dev/null || true
        bind -x '"\ec": agentic_call_computer_use' 2>/dev/null || true
        bind -x '"\eC": agentic_call_computer_use' 2>/dev/null || true
    fi
fi

# ---------------------------------------------------------
# Shell Specific Hooks: Zsh
# ---------------------------------------------------------
if [ -n "${ZSH_VERSION:-}" ]; then
    _agentic_zsh_preexec() {
        _AGENTIC_LAST_COMMAND="$1"
    }

    _agentic_zsh_precmd() {
        local exit_code=$?
        _agentic_on_command_complete "$exit_code" "${_AGENTIC_LAST_COMMAND:-}"
        _AGENTIC_LAST_COMMAND=""
        return $exit_code
    }

    autoload -Uz add-zsh-hook 2>/dev/null || true
    if typeset -f add-zsh-hook >/dev/null 2>&1; then
        add-zsh-hook preexec _agentic_zsh_preexec 2>/dev/null || true
        add-zsh-hook precmd _agentic_zsh_precmd 2>/dev/null || true
    else
        preexec_functions+=(_agentic_zsh_preexec)
        precmd_functions+=(_agentic_zsh_precmd)
    fi

    # ZLE Keybindings for Zsh in interactive mode
    zle -N agentic_send_command 2>/dev/null || true
    zle -N agentic_send_logs 2>/dev/null || true
    zle -N agentic_call_computer_use 2>/dev/null || true

    bindkey '^[a' agentic_send_command 2>/dev/null || true
    bindkey '^[A' agentic_send_command 2>/dev/null || true
    bindkey '^[b' agentic_send_logs 2>/dev/null || true
    bindkey '^[B' agentic_send_logs 2>/dev/null || true
    bindkey '^[c' agentic_call_computer_use 2>/dev/null || true
    bindkey '^[C' agentic_call_computer_use 2>/dev/null || true
fi
