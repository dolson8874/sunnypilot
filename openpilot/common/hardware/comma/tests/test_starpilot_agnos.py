import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpilot.common.hardware.comma import agnos, starpilot_agnos


class TestStarPilotAgnos(unittest.TestCase):
  def test_device_and_version_gate(self):
    with tempfile.TemporaryDirectory() as folder:
      model = Path(folder) / 'model'
      version = Path(folder) / 'version'
      with patch.multiple(starpilot_agnos, DEVICE_MODEL=model, OS_VERSION=version):
        with self.assertRaises(FileNotFoundError):
          starpilot_agnos.require_supported_device()
        for name, os_version, accepted in (
          ('comma tici\x00', '20.5.5\n', True),
          ('comma tici\x00', '12.8\n', False),
          ('comma tici\x00', '20.6\n', False),
          ('comma tizi\x00', '20.5.5\n', False),
          ('comma mici\x00', '20.5.5\n', False),
        ):
          with self.subTest(model=name, version=os_version):
            model.write_text(name)
            version.write_text(os_version)
            if accepted:
              starpilot_agnos.require_supported_device()
            else:
              with self.assertRaises(RuntimeError):
                starpilot_agnos.require_supported_device()

  def test_app_only_update(self):
    with tempfile.TemporaryDirectory() as folder:
      current = Path(folder) / 'current'
      candidate = Path(folder) / 'candidate'
      root = Path(__file__).resolve().parents[5]
      for relative_path in starpilot_agnos.POLICY_FILES:
        for target in (current, candidate):
          (target / relative_path).parent.mkdir(parents=True, exist_ok=True)
          shutil.copy2(root / relative_path, target / relative_path)

      starpilot_agnos.require_app_update(current, candidate)
      entry_point = candidate / 'launch_chffrplus.sh'
      entry_point.chmod(0o644)
      with self.assertRaisesRegex(RuntimeError, 'launch_chffrplus'):
        starpilot_agnos.require_app_update(current, candidate)
      shutil.copy2(current / 'launch_chffrplus.sh', entry_point)
      entry_point.write_text('# changed policy\n')
      with self.assertRaisesRegex(RuntimeError, 'launch_chffrplus'):
        starpilot_agnos.require_app_update(current, candidate)
      entry_point.unlink()
      entry_point.symlink_to(current / 'launch_chffrplus.sh')
      with self.assertRaisesRegex(RuntimeError, 'launch_chffrplus'):
        starpilot_agnos.require_app_update(current, candidate)

  def test_firmware_entry_points_refuse_before_io(self):
    calls = (
      (agnos.clear_partition_hash, (1, {})),
      (agnos.extract_compressed_image, (1, {}, None)),
      (agnos.flash_partition, (1, {}, None)),
      (agnos.swap, ('missing.json', 1, None)),
      (agnos.flash_agnos_update, ('missing.json', 1, None)),
    )
    with patch('builtins.open', side_effect=AssertionError('file access')), \
         patch.object(agnos.subprocess, 'run', side_effect=AssertionError('process spawned')), \
         patch.object(agnos.subprocess, 'check_output', side_effect=AssertionError('process spawned')):
      for function, args in calls:
        with self.subTest(function=function.__name__), self.assertRaises(PermissionError):
          function(*args)

  def test_cli_modes_refuse_even_with_missing_manifest(self):
    for mode in ([], ['--verify'], ['--swap']):
      with self.subTest(mode=mode):
        result = subprocess.run([sys.executable, agnos.__file__, *mode, '/missing.json'],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('does not modify firmware or boot slots', result.stderr)
