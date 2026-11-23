#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

POLICY="$DIR/openpilot/common/hardware/comma/starpilot_agnos.py"

function launch {
  python3 "$POLICY" || return 1

  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f "$DIR/.git/index.lock"

  # Only apply a consistent app update whose AGNOS policy matches this checkout.
  local finalized="$STAGING_ROOT/finalized"
  local backup="$STAGING_ROOT/old_openpilot"
  if [ -f "$DIR/.overlay_init" ] && [ -f "$finalized/.overlay_consistent" ]; then
    if find "$DIR/.git" -newer "$DIR/.overlay_init" | grep -q .; then
      echo "$DIR has been modified, skipping overlay update installation"
    elif [ -e "$backup" ] || [ -L "$backup" ]; then
      echo "openpilot backup found, not updating"
    elif python3 "$POLICY" --app-update "$DIR" "$finalized"; then
      echo "Installing verified sunnypilot app update"
      mv -- "$DIR" "$backup" || return 1
      if ! mv -- "$finalized" "$DIR"; then
        mv -- "$backup" "$DIR"
        return 1
      fi
      cd "$DIR" || return 1
      exec "$DIR/launch_chffrplus.sh"
    fi
  fi

  cd "$DIR" || return 1

  # handle pythonpath
  ln -sfn "$(pwd)" /data/pythonpath
  export PYTHONPATH="$PWD"

  # submodule package symlinks for PYTHONPATH imports on device.
  # on PC these come from editable installs via pyproject.toml / uv.
  ln -sfn msgq_repo/msgq msgq
  ln -sfn opendbc_repo/opendbc opendbc
  ln -sfn rednose_repo/rednose rednose
  ln -sfn teleoprtc_repo/teleoprtc teleoprtc
  ln -sfn tinygrad_repo/tinygrad tinygrad

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd openpilot/system/manager
  if [ ! -f "$DIR/prebuilt" ]; then
    ./build.py
  fi
  ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
