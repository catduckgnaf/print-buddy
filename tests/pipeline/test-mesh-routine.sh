#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/bin"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP"
run_case() (
  local case_name="$1" expected="$2"
  local d="$TMP/$case_name"
  rm -rf -- "$d"
  mkdir -p "$d/config"
  printf '[include printer.base.cfg]\n' >"$d/config/printer.cfg"
  tar -czf "$d/backup.tar.gz" -C "$d/config" .
  jq -n '{profiles:{auto:{points:[[1,1,1,1,1],[1,1,1,1,1],[1,1,1,1,1],[1,1,1,1,1],[1,1,1,1,1]]}}}' >"$d/old.json"
  jq -n '{confirmed:true,display_off:0,bed_target:60,hotend_target:150,home:"G28",probe:"BED_MESH_CALIBRATE PROFILE=auto",persist:"SAVE_CONFIG",native_screen_compatible:true,evidence:"TEST FIXTURE ONLY"}' >"$d/interface.json"
  jq -n '{webhooks:{state:"ready"},print_stats:{state:"standby"},virtual_sdcard:{is_active:false},idle_timeout:{state:"Ready"},toolhead:{homed_axes:""},extruder:{target:0,temperature:25},heater_bed:{target:0,temperature:25},bed_mesh:{profile_name:"",probed_matrix:[[]],profiles:{}},configfile:{settings:{bed_mesh:{probe_count:[5,5]}},config:{}},save_variables:{variables:{display_off:0,zcontrol_z:10}}}' >"$d/state.json"
  case "$case_name" in
    busy) jq '.print_stats.state="printing"' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json" ;;
    shutdown) jq '.webhooks.state="shutdown"' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json" ;;
    interrupted) mkdir -p "$d/run"; printf '{"phase":"probe.pending"}\n' >"$d/run/checkpoint.json" ;;
    unconfirmed) jq '.confirmed=false' "$d/interface.json" >"$d/x"; mv "$d/x" "$d/interface.json" ;;
  esac
  case "$case_name" in
    screenless|large_state|large_failure|wrong_mode|wrong_offset|wrong_load|screenless_ack|screenless_save_error)
      cp "$ROOT/config/mesh-interface.json" "$d/interface.json"
      jq '.save_variables.variables += {display_off:1,load_zoffset:1,gcode_offsets:{z:-0.005}}' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json"
      case "$case_name" in
        wrong_mode) jq '.save_variables.variables.display_off=0' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json" ;;
        wrong_offset) jq '.save_variables.variables.gcode_offsets.z=0.025' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json" ;;
        wrong_load) jq '.save_variables.variables.load_zoffset=0' "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json" ;;
      esac ;;
  esac
  if [[ "$case_name" == large_state || "$case_name" == large_failure ]]; then
    # Moonraker configfile exports exceed Linux's per-argument limit.
    jq '.configfile.config.large_fixture=("x" * 262144)' "$d/state.json" >"$d/x"
    mv "$d/x" "$d/state.json"
  fi
  # Fake transport only. There is no curl in this test harness.
  get() {
    if [[ "$case_name" == reconnect_timeout && -f "$d/saved" && ! -f "$d/cooled" ]]; then return 1; fi
    jq '{result:{status:.}}' "$d/state.json"
  }
  # Accelerate only the reconnect wait, keeping authorization clock real.
  date() {
    if [[ "$case_name" == reconnect_timeout && -f "$d/advance-clock" ]]; then
      printf '%s\n' "$(( $(command date +%s)+91 ))"
    else command date "$@"; fi
  }
  sleep() {
    if [[ "$case_name" == reconnect_timeout ]]; then touch "$d/advance-clock"; else command sleep "$@"; fi
  }
  need_jq() { :; }
  gcode() {
    printf '%s\n---\n' "$1" >>"$d/events"
    if [[ "$case_name" == timeout && "$1" == *BED_MESH_CALIBRATE* ]]; then return 28; fi
    if [[ "$case_name" == failure && "$1" == *BED_MESH_CALIBRATE* ]]; then printf '{"error":{"message":"probe failed"}}'; return; fi
    if [[ "$1" == *BED_MESH_CALIBRATE* ]]; then
      case "$case_name" in
        signal_int) kill -INT "$BASHPID" ;;
        signal_term) kill -TERM "$BASHPID" ;;
      esac
    fi
    if [[ "$1" == SAVE_CONFIG ]]; then
      if [[ "$case_name" == large_failure ]]; then printf '{"error":{"message":"save rejected"}}'; return; fi
      if [[ "$case_name" == save_error ]]; then printf '{"error":{"message":"save rejected"}}'; return; fi
      if [[ "$case_name" == reconnect_timeout ]]; then touch "$d/saved"; return 1; fi
    fi
    if [[ -f "$d/saved" && "$1" == *M104\ S0* ]]; then touch "$d/cooled"; fi
    local filter='.'
    case "$1" in
      *M140\ S60*) filter='.extruder.target=150|.extruder.temperature=150|.heater_bed.target=60|.heater_bed.temperature=60' ;;
      *G28*) filter='.toolhead.homed_axes="xyz"' ;;
      *AUTO_FULL_BED_LEVEL*)
        [[ "$1" == *'SAVE=0'* ]] || return 2
        if [[ "$case_name" != screenless_ack ]]; then
          filter='.toolhead.homed_axes="xyz"|.extruder.target=0|.heater_bed.target=0|.bed_mesh.profile_name="auto"|.bed_mesh.probed_matrix=[[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2]]|.bed_mesh.profiles.auto.points=.bed_mesh.probed_matrix'
        fi ;;
      *BED_MESH_CALIBRATE*)
        if [[ "$case_name" != ack_only ]]; then
          filter='.bed_mesh.profile_name="auto"|.bed_mesh.probed_matrix=[[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2]]|.bed_mesh.profiles.auto.points=.bed_mesh.probed_matrix'
        fi ;;
      *M104\ S0*) filter='.extruder.target=0|.heater_bed.target=0' ;;
      SAVE_CONFIG)
        if [[ "$case_name" != lost_save ]]; then filter='.configfile.config["bed_mesh auto"].points="2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2"'; fi ;;
      *BED_MESH_PROFILE*) filter='.bed_mesh.profile_name="auto"' ;;
    esac
    jq "$filter" "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json"
    if [[ "$case_name" == save_disconnect && "$1" == SAVE_CONFIG ]]; then return 1; fi
    printf '{"result":"ok"}\n'
  }
  source "$BIN/mesh-routine.sh"
  local auth
  auth="$(date +%s)"
  [[ "$case_name" != stale ]] || auth=$((auth-121))
  set +e
  (set -e; mesh_run --state-dir "$d/run" --authorized-at "$auth" --bed-clear --hands-clear --present --backup "$d/backup.tar.gz" --old-mesh "$d/old.json" --interface "$d/interface.json") >"$d/output" 2>"$d/error"
  local rc=$?
  set -e
  if [[ "$expected" == pass ]]; then
    [[ "$rc" == 0 ]]
    jq -e '.phase=="completed" and .readback.extruder.target==0 and .readback.heater_bed.target==0' "$d/run/checkpoint.json" >/dev/null
    local before after
    before="$(sha256sum "$d/events")"
    mesh_run --state-dir "$d/run" >"$d/replay"
    after="$(sha256sum "$d/events")"
    [[ "$before" == "$after" ]]
  else
    [[ "$rc" != 0 ]]
    if [[ -f "$d/events" ]]; then
      jq -e '.extruder.target==0 and .heater_bed.target==0' "$d/state.json" >/dev/null
      case "$case_name" in timeout|failure|ack_only|signal_int|signal_term) if bash -c '[[ "$(<"$1")" == *SAVE_CONFIG* ]]' _ "$d/events"; then exit 1; fi ;; esac
      case "$case_name" in
        signal_int|signal_term|save_error|large_failure|reconnect_timeout)
          jq -e '.phase=="failed_cooldown_verified" and (.failure_cause|length)>0 and .readback.extruder.target==0 and .readback.heater_bed.target==0' "$d/run/checkpoint.json" >/dev/null
          [[ "$(<"$d/error")" == *FAILED:* ]]
          case "$case_name" in
            signal_int) [[ "$rc" == 130 ]]; [[ "$(<"$d/error")" == *'interrupted by INT'* ]] ;;
            signal_term) [[ "$rc" == 143 ]]; [[ "$(<"$d/error")" == *'terminated by TERM'* ]] ;;
            save_error) [[ "$(<"$d/error")" == *'save rejected'* ]] ;;
            reconnect_timeout) [[ "$(<"$d/error")" == *'reconnect deadline expired'* ]] ;;
          esac
          if [[ "$case_name" == save_error || "$case_name" == reconnect_timeout ]]; then
            [[ "$(<"$d/events")" != *'BED_MESH_PROFILE LOAD'* ]]
            [[ "$(while IFS= read -r line; do [[ "$line" != SAVE_CONFIG ]] || printf x; done <"$d/events")" == x ]]
          fi
          local before after replay_rc
          before="$(sha256sum "$d/events")"
          set +e
          mesh_run --state-dir "$d/run" >"$d/replay" 2>"$d/replay-error"
          replay_rc=$?
          set -e
          after="$(sha256sum "$d/events")"
          [[ "$replay_rc" != 0 && "$before" == "$after" ]]
          ;;
      esac
    fi
  fi
  printf 'PASS %s\n' "$case_name"
)
preserve_failed_case() (
  local d src dst before
  d="$TMP/preserve_failed"
  src="$TMP/large_failure/run"
  dst="$d/new-run"
  [[ -f "$src/checkpoint.json" ]] || { printf 'MISSING prior failed fixture\n' >&2; exit 1; }
  local before
  before="$(sha256sum "$src/checkpoint.json" "$src/evidence.sha256")"
  mkdir -p "$d"
  cp "$TMP/large_failure/backup.tar.gz" "$d/backup.tar.gz"
  cp "$TMP/large_failure/old.json" "$d/old.json"
  cp "$ROOT/config/mesh-interface.json" "$d/interface.json"
  jq -n '{webhooks:{state:"ready"},print_stats:{state:"standby"},virtual_sdcard:{is_active:false},idle_timeout:{state:"Ready"},toolhead:{homed_axes:""},extruder:{target:0,temperature:25},heater_bed:{target:0,temperature:25},bed_mesh:{profile_name:"",probed_matrix:[[]],profiles:{}},configfile:{settings:{bed_mesh:{probe_count:[5,5]}},config:{}},save_variables:{variables:{display_off:1,load_zoffset:1,gcode_offsets:{z:-0.005},zcontrol_z:10}}}' >"$d/state.json"
  get() { jq '{result:{status:.}}' "$d/state.json"; }
  date() { command date "$@"; }
  sleep() { command sleep "$@"; }
  need_jq() { :; }
  gcode() {
    printf '%s\n---\n' "$1" >>"$d/events"
    local filter='.'
    case "$1" in
      *AUTO_FULL_BED_LEVEL*)
        [[ "$1" == *'SAVE=0'* ]] || return 2
        filter='.toolhead.homed_axes="xyz"|.extruder.target=0|.heater_bed.target=0|.bed_mesh.profile_name="auto"|.bed_mesh.probed_matrix=[[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2],[2,2,2,2,2]]|.bed_mesh.profiles.auto.points=.bed_mesh.probed_matrix' ;;
      *M104\ S0*) filter='.extruder.target=0|.heater_bed.target=0' ;;
      SAVE_CONFIG) filter='.configfile.config["bed_mesh auto"].points="2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2\n2,2,2,2,2"' ;;
      *BED_MESH_PROFILE*) filter='.bed_mesh.profile_name="auto"' ;;
    esac
    jq "$filter" "$d/state.json" >"$d/x"; mv "$d/x" "$d/state.json"
    printf '{"result":"ok"}\n'
  }
  source "$BIN/mesh-routine.sh"
  local auth rc
  auth="$(date +%s)"
  set +e
  mesh_run --state-dir "$src" >"$d/old-replay" 2>"$d/old-replay-error"
  rc=$?
  set -e
  [[ "$rc" != 0 ]]
  [[ "$(sha256sum "$src/checkpoint.json" "$src/evidence.sha256")" == "$before" ]]
  mesh_run --state-dir "$dst" --authorized-at "$auth" --bed-clear --hands-clear --present \
    --backup "$d/backup.tar.gz" --old-mesh "$d/old.json" --interface "$d/interface.json" >"$d/output"
  jq -e '.phase=="completed"' "$dst/checkpoint.json" >/dev/null
  [[ "$(sha256sum "$src/checkpoint.json" "$src/evidence.sha256")" == "$before" ]]
  [[ "$dst" != "$src" && ! -e "$src/new-run" ]]
  printf 'PASS preserve_failed\n'
)
for c in busy shutdown interrupted stale unconfirmed timeout failure ack_only lost_save signal_int signal_term save_error reconnect_timeout wrong_mode wrong_offset wrong_load screenless_ack; do run_case "$c" fail; done
run_case unhomed pass
run_case save_disconnect pass
run_case screenless pass
run_case large_state pass
run_case large_failure fail
preserve_failed_case
printf 'PASS: 23 offline cases; failed evidence stays put and a new directory can complete\n'
