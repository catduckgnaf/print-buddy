#!/usr/bin/env bash
# Sourced by moonrakerctl. No printer contact at load time.
mesh_run() (
  set -Eeuo pipefail
  local dir='' auth='' backup='' old='' interface='' inspect=no
  local bed_clear=no hands_clear=no present=no phase=new armed=no s='' deadline=0 failure_cause=''
  local query='/printer/objects/query?webhooks&print_stats&virtual_sdcard&idle_timeout&toolhead&extruder&heater_bed&bed_mesh&configfile&save_variables'
  while (($#)); do
    case "$1" in
      --state-dir) dir="${2:?}"; shift 2 ;;
      --authorized-at) auth="${2:?}"; shift 2 ;;
      --backup) backup="${2:?}"; shift 2 ;;
      --old-mesh) old="${2:?}"; shift 2 ;;
      --interface) interface="${2:?}"; shift 2 ;;
      --bed-clear) bed_clear=yes; shift ;;
      --hands-clear) hands_clear=yes; shift ;;
      --present) present=yes; shift ;;
      --inspect) inspect=yes; shift ;;
      *) printf 'REFUSED: unknown mesh-run argument %s\n' "$1" >&2; exit 2 ;;
    esac
  done
  [[ -n "$dir" ]] || { printf 'REFUSED: --state-dir required\n' >&2; exit 2; }
  if [[ "$inspect" == yes ]]; then jq . "$dir/checkpoint.json"; exit; fi
  need_jq
  mkdir -p "$dir"
  exec 9>"$dir/lock"
  flock -n 9 || { printf 'REFUSED: routine already owned\n' >&2; exit 2; }
  checkpoint() {
    # Stream the full readback; argv has a per-string size limit on Linux.
    jq -c --arg phase "$phase" --argjson deadline "$deadline" --arg backup "$backup" --arg old "$old" --arg interface "$interface" --arg failure_cause "$failure_cause" '{phase:$phase,deadline:$deadline,backup:$backup,old_mesh:$old,interface:$interface,readback:.,failure_cause:$failure_cause}' <<<"${s:-null}" >"$dir/checkpoint.tmp"
    mv "$dir/checkpoint.tmp" "$dir/checkpoint.json"
    sync -f "$dir/checkpoint.json"
  }
  refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
  read_state() { s="$(get "$query" | jq -e '.result.status')"; }
  idle() {
    jq -e '.webhooks.state=="ready" and (.print_stats.state=="standby" or .print_stats.state=="complete" or .print_stats.state=="cancelled") and .virtual_sdcard.is_active==false and (.idle_timeout.state=="Ready" or .idle_timeout.state=="Idle")' <<<"$s" >/dev/null
  }
  thermal_off() {
    local GCODE_TIMEOUT=15
    gcode $'M104 S0\nM140 S0\nM400' >"$dir/cooldown-response.json" || return 1
    jq -e '.result=="ok" and .error==null' "$dir/cooldown-response.json" >/dev/null || return 1
    read_state || return 1
    jq -e '.extruder.target==0 and .heater_bed.target==0' <<<"$s" >/dev/null
  }
  failed() {
    local rc="${1:?failure status required}" cooldown=failed
    failure_cause="${2:-command failed during $phase}"
    ((rc!=0)) || rc=1
    trap - ERR INT TERM
    if [[ "$armed" == yes ]]; then
      if thermal_off; then cooldown=verified; fi
      phase="failed_cooldown_$cooldown"
      if ! checkpoint; then printf 'ERROR: checkpoint write failed\n' >&2; fi
    fi
    printf 'FAILED: %s; status=%s; cooldown=%s; inspect %s/checkpoint.json; no automatic replay\n' "$failure_cause" "$rc" "$cooldown" "$dir" >&2
    exit "$rc"
  }
  if [[ -f "$dir/checkpoint.json" ]]; then
    phase="$(jq -er '.phase' "$dir/checkpoint.json")"
    if [[ "$phase" == completed ]]; then jq . "$dir/checkpoint.json"; exit; fi
    if [[ "$phase" != prepared ]]; then
      # Pending actuation is ambiguous after a crash. Never automatically replay.
      refuse "checkpoint $phase requires operator reconciliation; --inspect performs no actuation"
    fi
    backup="$(jq -er '.backup' "$dir/checkpoint.json")"
    old="$(jq -er '.old_mesh' "$dir/checkpoint.json")"
    interface="$(jq -er '.interface' "$dir/checkpoint.json")"
    sha256sum -c "$dir/evidence.sha256" >/dev/null || refuse 'preserved evidence changed'
  fi
  [[ "$bed_clear" == yes && "$hands_clear" == yes && "$present" == yes ]] || refuse 'fresh bed-clear, hands-clear and presence confirmations required'
  [[ "$auth" =~ ^[0-9]{10}$ ]] || refuse '--authorized-at must be current epoch seconds'
  local now age
  now="$(date +%s)"; age=$((now-auth))
  ((age>=0 && age<=120)) || refuse 'authorization expired or future dated'
  deadline=$((auth+1200))
  [[ -s "$backup" && -s "$old" && -s "$interface" ]] || refuse 'preserved config archive, old mesh and confirmed interface packet required'
  tar -tzf "$backup" >"$dir/backup-inventory.txt"
  jq -e '.profiles.auto.points | length==5 and all(.[];length==5)' "$old" >/dev/null
  # This packet must come from a reviewed installed-version export, never inferred
  # from generic Klipper docs or the old -0.25 probe reference.
  jq -e '.confirmed==true and .bed_target==60 and .persist=="SAVE_CONFIG" and (.evidence|type=="string" and length>0) and
    ((.display_off==0 and .hotend_target==150 and .home=="G28" and .probe=="BED_MESH_CALIBRATE PROFILE=auto" and .native_screen_compatible==true) or
     (.display_off==1 and .hotend_target==220 and .probe=="AUTO_FULL_BED_LEVEL EXTRUDER_TEMP=220 BED_TEMP=60 PROFILE=auto SAVE=0" and .native_screen_compatible==false and .load_zoffset==1 and (.z_offset|type=="number") and .source_commit=="75bcec539196aa022243c56397eba9a17e0577cc"))' "$interface" >/dev/null || refuse 'unconfirmed installed calibration semantics'
  local display_mode
  display_mode="$(jq -r '.display_off' "$interface")"
  authority_ok() {
    jq -e --argjson mode "$display_mode" --slurpfile pkt "$interface" '.save_variables.variables.display_off==$mode and .save_variables.variables.zcontrol_z==10 and (.configfile.settings.bed_mesh.probe_count==[5,5]) and
      ($mode==0 or (.save_variables.variables.load_zoffset==1 and (.save_variables.variables.gcode_offsets.z|type=="number") and .save_variables.variables.gcode_offsets.z==$pkt[0].z_offset))' <<<"$s" >/dev/null
  }
  read_state
  idle || refuse 'printer busy, paused, shutdown or state unknown'
  authority_ok || refuse 'screen mode, offset authority, force-control or mesh configuration changed'
  # No new backup on resume. Preserve paths and checksums of the supplied evidence.
  sha256sum "$backup" "$old" "$interface" >"$dir/evidence.sha256"
  phase=prepared; checkpoint
  armed=yes
  trap 'failed "$?"' ERR
  trap 'failed 130 "interrupted by INT during $phase"' INT
  trap 'failed 143 "terminated by TERM during $phase"' TERM
  remaining() {
    now="$(date +%s)"
    ((now<deadline)) || return 1
    GCODE_TIMEOUT=$((deadline-now))
    ((GCODE_TIMEOUT>300)) && GCODE_TIMEOUT=300
    return 0
  }
  wait_idle() {
    local end=$(( $(date +%s)+300 ))
    while :; do
      read_state
      [[ "$(jq -r '.webhooks.state' <<<"$s")" == ready ]] || return 1
      if idle; then return; fi
      remaining
      (( $(date +%s)<end )) || return 1
      sleep 2
    done
  }
  command_step() {
    phase="$1.pending"; checkpoint
    remaining
    gcode "$2" >"$dir/command-response.json"
    jq -e '.result=="ok" and .error==null' "$dir/command-response.json" >/dev/null
    wait_idle
    phase="$1.done"; checkpoint
  }
  printf 'Running bed mesh probe, about 3 to 8 min (typical, not measured on this printer).\n' >&2
  if [[ "$display_mode" == 1 ]]; then
    # ZMod performs nozzle cleaning, homing and load-cell preparation itself.
    # SAVE=0 leaves persistence to our verified readback stage, never auto-save.
    command_step probe "$(jq -r '.probe' "$interface")"$'\nM400'
  else
    command_step heat $'M140 S60\nM104 S150\nM190 S60\nM109 S150\nM400'
    jq -e '.heater_bed.target==60 and .extruder.target==150 and ((.heater_bed.temperature-60)|fabs)<=2 and ((.extruder.temperature-150)|fabs)<=2' <<<"$s" >/dev/null
    if [[ "$(jq -r '.toolhead.homed_axes' <<<"$s")" != xyz ]]; then
      command_step home $'G28\nM400'
    fi
    command_step probe $'BED_MESH_CLEAR\nBED_MESH_CALIBRATE PROFILE=auto\nM400'
  fi
  jq -e '.toolhead.homed_axes=="xyz"' <<<"$s" >/dev/null
  authority_ok
  jq -e '.bed_mesh.profile_name=="auto" and (.bed_mesh.probed_matrix|length==5 and all(.[];length==5 and all(.[];type=="number"))) and .bed_mesh.profiles.auto.points==.bed_mesh.probed_matrix' <<<"$s" >/dev/null
  jq -c '.bed_mesh.probed_matrix' <<<"$s" >"$dir/expected-points.json"
  phase=cooldown.pending; checkpoint
  thermal_off
  phase=cooldown.done; checkpoint
  # Only a verified full mesh reaches SAVE_CONFIG. It restarts Klipper.
  command_step save_profile $'BED_MESH_PROFILE SAVE=auto\nM400'
  phase=save.pending; checkpoint
  remaining
  local save_transport=ok
  if ! gcode SAVE_CONFIG >"$dir/save-response.json" 2>"$dir/save-error.txt"; then
    # Installed trace shows SAVE_CONFIG disconnects Klippy with HTTP 503.
    # This is neither success nor a reason to resend. Persistence below decides.
    save_transport=disconnected
  elif ! jq -e '.result=="ok" and .error==null' "$dir/save-response.json" >/dev/null; then
    failed 1 "SAVE_CONFIG rejected: $(jq -r '.error.message // "invalid response"' "$dir/save-response.json" 2>/dev/null || printf 'invalid JSON response')"
  fi
  printf '%s\n' "$save_transport" >"$dir/save-transport.txt"
  local end=$(( $(date +%s)+90 ))
  while :; do
    if read_state && [[ "$(jq -r '.webhooks.state' <<<"$s")" == ready ]]; then break; fi
    remaining || failed 1 'overall deadline expired awaiting SAVE_CONFIG reconnect'
    (( $(date +%s)<end )) || failed 1 'SAVE_CONFIG reconnect deadline expired'
    sleep 2
  done
  idle
  jq -e --slurpfile points "$dir/expected-points.json" '
    (.configfile.config["bed_mesh auto"].points | split("\n") | map(gsub("^ +| +$";"")) | map(select(length>0)) | map(split(",") | map(tonumber))) as $saved
    | $saved==$points[0] and .bed_mesh.profiles.auto.points==$points[0] and .extruder.target==0 and .heater_bed.target==0' <<<"$s" >/dev/null
  command_step load $'BED_MESH_PROFILE LOAD=auto\nM400'
  authority_ok
  jq -e --slurpfile p "$dir/expected-points.json" '.bed_mesh.profile_name=="auto" and .bed_mesh.probed_matrix==$p[0] and .extruder.target==0 and .heater_bed.target==0' <<<"$s" >/dev/null
  phase=completed; checkpoint
  armed=no; trap - ERR INT TERM
  jq . "$dir/checkpoint.json"
)
