"""Retain the externally installed StarPilot AGNOS on the C3 test branch."""
import argparse
from pathlib import Path

DEVICE_MODEL = Path('/sys/firmware/devicetree/base/model')
OS_VERSION = Path('/VERSION')
REQUIRED_MODEL = 'comma tici'
REQUIRED_VERSION = '20.5.5'
UPDATE_BRANCH = 'test/lrmaster-SP-tici-wip'
POLICY_FILES = (
  'launch_openpilot.sh',
  'launch_env.sh',
  'launch_chffrplus.sh',
  'tools/op.sh',
  'openpilot/common/hardware/comma/starpilot_agnos.py',
  'openpilot/common/hardware/comma/agnos.py',
  'openpilot/system/updated/updated.py',
)


def require_supported_device() -> None:
  model = DEVICE_MODEL.read_text().rstrip('\x00\r\n')
  if model != REQUIRED_MODEL:
    raise RuntimeError(f'This branch requires {REQUIRED_MODEL}; detected {model!r}')
  version = OS_VERSION.read_text().strip()
  if version != REQUIRED_VERSION:
    raise RuntimeError(f'This branch requires preinstalled StarPilot C3 AGNOS {REQUIRED_VERSION}; detected {version!r}')


def supports_tici_onroad(channel: str, channel_type: str) -> bool:
  if channel != UPDATE_BRANCH:
    return channel_type == 'tici'
  try:
    require_supported_device()
  except (OSError, RuntimeError):
    return False
  return True


def require_app_update(current: Path, candidate: Path) -> None:
  for path in POLICY_FILES:
    old, new = current / path, candidate / path
    if (not new.is_file() or new.is_symlink() or old.read_bytes() != new.read_bytes()
        or (old.stat().st_mode & 0o111) != (new.stat().st_mode & 0o111)):
      raise RuntimeError(f'App update changes AGNOS retention policy: {path}')


def refuse_firmware_change() -> None:
  raise PermissionError('This branch retains StarPilot AGNOS and does not modify firmware or boot slots')


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--app-update', nargs=2, type=Path, metavar=('CURRENT', 'CANDIDATE'))
  args = parser.parse_args()
  try:
    require_supported_device()
    if args.app_update:
      require_app_update(*args.app_update)
  except (OSError, RuntimeError) as exc:
    parser.exit(1, f'{exc}\n')
