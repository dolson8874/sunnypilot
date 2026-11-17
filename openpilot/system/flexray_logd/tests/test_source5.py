"""Selected DADC originals stay distinct through mapping, buffering and health."""
from types import SimpleNamespace

import pytest

from openpilot.cereal import messaging
from openpilot.system.flexray_logd.flexrayd import frame_message, unpack_frames
from openpilot.system.flexray_logd.startup import LoggerStartup
from openpilot.system.flexray_logd.status import CaptureStatus, display_state
from openpilot.system.flexray_logd.tests.test_flexrayd import envelope


@pytest.mark.parametrize('frame_id', [0x1f, 0x31, 0x0d])
def test_original_maximum_body_every_socket_split(frame_id):
  payload = b'\xca\x80\xca\x90\xca\xa0' + bytes(range(248))
  raw = envelope(frame_id=frame_id, flags=31, cycle=63, bus=1, payload=payload)
  expected = [{'address': frame_id, 'src': 5, 'dat': b'\x1f\x3f' + payload + b'\x12\x34\x56'}]
  for split in range(len(raw) + 1):
    pending = bytearray(raw[:split])
    frames = unpack_frames(pending)
    pending.extend(raw[split:])
    frames += unpack_frames(pending)
    assert not pending and frames == expected
    with messaging.log.Event.from_bytes(frame_message(frames).to_bytes()) as event:
      assert event.can[0].src == 5 and event.can[0].dat == expected[0]['dat']


def test_original_only_buffer_freshness_retry_recovery_and_shutdown_loss():
  clock, values, sent = [10.0], {}, []
  pm = SimpleNamespace(send=lambda channel, data: sent.append((channel, data)))
  status = CaptureStatus(pm, clock=lambda: clock[0])
  gate = LoggerStartup(pm, SimpleNamespace(get=lambda key: values.get(key)), status, clock=lambda: clock[0], capacity=512)
  original = unpack_frames(bytearray(envelope(frame_id=0x1f, cycle=1, bus=1)))
  gate.submit(original)
  gate.poll()
  assert status.arrival_counts == {4: 0, 5: 1, 6: 0}
  assert gate.queue[0][1] == {4: 0, 5: 1, 6: 0}
  assert status.snapshot()['state'] == 'buffering'
  values['FlexrayLoggerAck'] = str(gate.probes[-1])
  clock[0] += 0.1
  gate.poll()
  assert status.counts == {4: 0, 5: 1, 6: 0}
  assert status.snapshot()['state'] == 'receiving'
  clock[0] += 1
  status.publish()
  view = status.snapshot()
  assert view['src4Rate'] == view['src6Rate'] == view['src4Frames'] == view['src6Frames'] == 0
  message = messaging.new_message('flexrayStatus')
  message.flexrayStatus = view
  assert display_state(message.flexrayStatus, clock[0], received_at=clock[0]) == 'receiving'
  clock[0] += 2
  assert status.snapshot()['state'] == 'waiting'
  status.retrying('test native exit')
  assert status.snapshot()['state'] == 'retrying'
  status.starting(12)
  assert status.last_frame == 0
  gate.submit(original)
  assert status.snapshot()['state'] == 'receiving' and status.counts[5] == 2
  with messaging.log.Event.from_bytes(next(data for channel, data in sent if channel == 'flexray' and isinstance(data, bytes))) as event:
    assert event.can[0].src == 5 and event.can[0].address == 0x1f
  gate.ready = False
  for _ in range(50):
    gate.submit(original)
  assert gate.buffered_frames + gate.dropped_frames == 50
  gate.close()
  assert gate.dropped_frames == 50 and not gate.queue


def test_original_is_not_used_as_cruise_output_or_vehicle_can():
  from openpilot.system.cruise_analysis.observer import Observer

  observer = Observer(epoch='source5-isolation')
  output = {'address': 0x1f, 'src': 6, 'dat': b'\x04\x01' + bytes(range(29))}
  observer.consume(frame_message([output]), 10_000_000_000, transport='flexray')
  before = observer.frames.copy()
  original = dict(output, src=5, dat=b'\x04\x01' + bytes(reversed(range(29))))
  observer.consume(frame_message([original]), 11_000_000_000, transport='flexray')
  assert observer.frames == before and observer.counts['frames'] == 1
  observer.consume(frame_message([original]), 12_000_000_000, transport='can')
  assert observer.frames == before and observer.counts['frames'] == 1
