import json
import sys
import time
from types import SimpleNamespace

from cereal import messaging
from openpilot.system.flexray_logd.status import CaptureStatus, display_state
from openpilot.system.flexray_logd.usb_inventory import capture_usb_inventory, start_usb_inventory


def tracker():
  clock = [10.0]
  sent = []
  status = CaptureStatus(SimpleNamespace(send=lambda service, message: sent.append((service, message.to_bytes()))), clock=lambda: clock[0])
  return status, clock, sent


def reader(status):
  message = messaging.new_message('flexrayStatus')
  message.flexrayStatus = status.snapshot()
  return message.flexrayStatus


def test_only_valid_frames_mean_receiving():
  status, now, sent = tracker()
  status.starting(123)
  status.native({'last_successful_read_monotonic': 10.0, 'delivered_bytes': 32768})
  status.received([])  # Empty heartbeat, padding or only invalid frames.
  assert display_state(reader(status), 10.0, received_at=10.0) == 'waiting'
  status.received([{'src': 4}, {'src': 6}, {'src': 6}, {'src': 1}])
  now[0] = 11.0
  status.publish()
  result = reader(status)
  assert result.src4Frames == 1 and result.src6Frames == 2
  assert result.src4Rate == 1 and result.src6Rate == 2
  assert display_state(result, 11.0, received_at=11.0) == 'receiving'
  now[0] = 12.0
  assert display_state(result, 12.0, received_at=12.0) == 'waiting'
  assert display_state(result, 12.0, enabled=False, received_at=12.0) == 'disabled'
  assert display_state(result, 15.0, received_at=11.0) == 'unavailable'
  assert display_state(None, 12.0) == 'unavailable'
  assert display_state(result, 9.0, received_at=11.0) == 'unavailable'
  # Dedicated standard service/union; no status messages on can or flexray.
  assert all(service == 'flexrayStatus' for service, raw in sent)
  with messaging.log.Event.from_bytes(sent[-1][1]) as message:
    assert message.which() == 'flexrayStatus' and message.valid
    assert message.flexrayStatus.usbDeliveredBytes == 32768


def test_retry_and_restart_invalidate_old_receiving():
  status, now, sent = tracker()
  status.starting(1)
  status.received([{'src': 4}])
  status.native({'first_actual_error': 'stage=gpio failed', 'last_actual_error': 'input error'})
  status.retrying('status 1')
  assert display_state(reader(status), 10.1, received_at=10.1) == 'retrying'
  assert status.snapshot()['lastError'] == 'input error'
  assert status.snapshot()['retryCount'] == 1
  now[0] = 11
  status.starting(2)
  assert status.last_frame == 0 and status.last_error == ''
  assert display_state(reader(status), 11, received_at=11) == 'starting'
  assert status.snapshot()['src4Rate'] == 0
  status.phase = 'stopped'
  assert display_state(reader(status), 11, received_at=11) == 'stopped'
  count = len(sent)
  status.publish()
  assert len(sent) == count  # No telemetry flood.


def test_usb_inventory_success_error_timeout_and_flood():
  result = capture_usb_inventory((sys.executable, '-c', 'print("bcdDevice 08.00")'))
  assert result['returncode'] == 0 and 'bcdDevice 08.00' in result['output']
  assert not result['timed_out'] and not result['truncated']
  result = capture_usb_inventory(('/nonexistent/flexray-lsusb',))
  assert 'error' in result and result['returncode'] is None
  result = capture_usb_inventory((sys.executable, '-c', 'import sys;sys.stderr.write("permission denied");sys.exit(1)'))
  assert result['returncode'] == 1 and 'permission denied' in result['output']
  start = time.monotonic()
  result = capture_usb_inventory((sys.executable, '-c', 'import time;time.sleep(5)'), timeout=0.1)
  assert result['timed_out'] and time.monotonic() - start < 1.5
  result = capture_usb_inventory((sys.executable, '-c', 'import os;os.write(1,b"x"*1000000)'), limit=1024)
  assert result['returncode'] == 0 and len(result['output']) == 1024
  assert result['truncated'] and result['bytes'] == 1000000


def test_usb_inventory_worker_logs_without_blocking_capture(monkeypatch):
  from openpilot.system.flexray_logd import usb_inventory

  observed = []
  monkeypatch.setattr(usb_inventory, 'capture_usb_inventory', lambda: {'returncode': 0, 'output': 'bcdDevice 08.00'})
  monkeypatch.setattr(usb_inventory.cloudlog, 'info', observed.append)
  inventory = start_usb_inventory()
  inventory.thread.join(timeout=1)
  assert not inventory.thread.is_alive()
  inventory.report()
  inventory.report()
  assert len(observed) == 1
  assert json.loads(observed[0].removeprefix('FlexRay USB descriptor: '))['output'] == 'bcdDevice 08.00'


def test_logger_wait_state_is_not_receiving():
  status, now, sent = tracker()
  status.received([{'src': 4}])
  status.logger_state(False, 10, 1000, 0, 0)
  assert status.snapshot()['state'] == 'buffering'
  assert display_state(reader(status), now[0], received_at=now[0]) == 'buffering'


def test_latest_native_error_replaces_earliest_error():
  status, now, sent = tracker()
  status.native({'first_actual_error': 'initial setup failure', 'last_actual_error': 'later read failure'})
  assert status.snapshot()['lastError'] == 'later read failure'
  status.last_error = 'newer recorder transport failure'
  status.native({'first_actual_error': 'initial setup failure', 'last_actual_error': 'later read failure'})
  assert status.snapshot()['lastError'] == 'newer recorder transport failure'
  status.native({'first_actual_error': None, 'last_actual_error': None})
  assert status.snapshot()['lastError'] == 'newer recorder transport failure'
