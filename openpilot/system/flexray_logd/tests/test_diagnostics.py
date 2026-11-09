import itertools
import json
import struct
import subprocess
import sys
import time

import pytest

from openpilot.cereal import messaging
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.system.flexray_logd.diagnostics import DiagnosticAssembler, DiagnosticReceiver, Snapshot, decode_page, snapshot_rates

VALUES = [0x12345678, 0x23456789, 0x1020304, 0x2030405, 32 | (32 << 16), 12345, 131072, 0x123, 0xF0E0D0C0, 0x11223344, 0xA1B2C3D4, 0x55667788]


def payload(page, seq=0, values=VALUES):
  snapshot = struct.pack('<12I', *values)
  return bytes([0x20 | page, seq]) + snapshot[page * 6 : page * 6 + 6]


def feed(assembler, seq, start, values=VALUES, order=range(8)):
  return [assembler.accept(0x1FA, assembler.bus, payload(page, seq, values), start + i * 0.01) for i, page in enumerate(order)]


def test_packed_pages_and_version_validation():
  packed = struct.pack('<12I', *VALUES)
  for page in range(8):
    result = decode_page(0x1FA, 1, payload(page, 255), 1)
    assert (result.page, result.sequence, result.chunk) == (page, 255, packed[page * 6 : page * 6 + 6])
  assert payload(0)[6:] != b'\0\0'  # These bytes belong to item 1, not reservations.
  data = payload(0)
  for address, bus, body in [
    (0x1F9, 1, data),
    (0x800001FA, 1, data),
    (0x1FA, 0, data),
    (0x1FA, 4, data),
    (0x1FA, 6, data),
    (0x1FA, 1, data[:-1]),
    (0x1FA, 1, data + b'\0'),
    (0x1FA, 1, b'\x10' + data[1:]),
    (0x1FA, 1, b'\x28' + data[1:]),
    (0x1FA, 1, b'\x30' + data[1:]),
  ]:
    assert decode_page(address, bus, body, 1) is None
  assembler = DiagnosticAssembler(1)
  feed(assembler, 0, 1)
  assert assembler.last_complete.words() == tuple(VALUES)
  # uint32 item 1 crosses page 0/1; item 4 crosses page 2/3.
  assert assembler.last_complete.words()[1] == 0x23456789
  assert assembler.last_complete.words()[4] == (32 | (32 << 16))
  deeper = list(VALUES)
  deeper[4] = 512 | (1024 << 16)
  feed(assembler, 1, 2, deeper)
  assert assembler.status(2.1)['last_complete']['dadc_queue_peak'] == 512
  for value in (131073, 0xFFFFFFFF):
    bad = list(VALUES)
    bad[6] = value
    target = DiagnosticAssembler(1)
    assert not any(feed(target, 0, 1, bad))
    assert target.last_complete is None


@pytest.mark.parametrize('order', [list(range(8)), list(reversed(range(8))), [4, 0, 7, 2, 5, 1, 6, 3]])
def test_complete_reordered_and_partial_status(order):
  assembler = DiagnosticAssembler(1)
  assert sum(feed(assembler, 0, 10, order=order)) == 1
  result = assembler.status(10.1)
  assert result['last_complete_sequence'] == 0
  assert result['page_mask'] == 255 and result['complete_fresh']
  values = result['last_complete']
  assert values['dadc_received'] == VALUES[0]
  assert values['bcm_dropped'] == VALUES[3]
  assert values['dadc_queue_peak'] == 32 and values['bcm_queue_peak'] == 32
  assert values['fifo_bytes'] == 12345 and values['fifo_peak_bytes'] == 131072
  assembler.accept(0x1FA, 1, payload(0, 1), 11)
  partial = assembler.status(11.1)
  assert partial['page_mask'] == 1 and partial['last_complete_sequence'] == 0
  assert not partial['latest_state_complete']
  assert partial['last_complete_age'] > 1
  expired_partial = assembler.status(12.51)
  assert not expired_partial['latest_state_complete']
  assert expired_partial['page_mask'] == 0
  assert not assembler.status(14)['complete_fresh']
  assert assembler.status(14)['pending'] == {}


def test_missing_duplicate_conflict_and_expired_reuse():
  assembler = DiagnosticAssembler(0, timeout=1)
  assert not any(feed(assembler, 7, 1, order=range(7)))
  assert not assembler.accept(0x1FA, 0, payload(0, 7), 1.1)
  assert assembler.stats['duplicates'] == 1
  changed = list(VALUES)
  changed[0] += 1
  assert not assembler.accept(0x1FA, 0, payload(0, 7, changed), 1.2)
  assert assembler.stats['conflicts'] == 1
  assert not assembler.accept(0x1FA, 0, payload(7, 7), 1.3)
  assert assembler.status(1.3)['last_complete'] is None
  assembler.expire(2.1)
  assert not assembler.accept(0x1FA, 0, payload(7, 7), 2.2)
  assert not assembler.accept(0x1FA, 0, payload(0, 7), 1, now=3.3)
  # Reused sequence cannot combine with the retired old pages.
  assert not any(feed(assembler, 7, 3.3, order=[7, 6, 5, 4, 3, 2, 1]))
  assert assembler.status(3.4)['last_complete'] is None
  assert assembler.accept(0x1FA, 0, payload(0, 7), 3.5)
  assert assembler.status(3.5)['last_complete_sequence'] == 7


def test_sequence_wrap_and_old_snapshot_does_not_replace_new():
  assembler = DiagnosticAssembler(2)
  for seq, stamp in [(254, 1), (255, 2), (0, 3), (1, 4)]:
    assert sum(feed(assembler, seq, stamp)) == 1
  assert assembler.last_complete.sequence == 1
  assert assembler.sequence_discontinuities == 0
  # Assemble old sequence pages interleaved with a newer complete sequence.
  assembler = DiagnosticAssembler(2)
  feed(assembler, 10, 10, order=range(4))
  feed(assembler, 11, 10.2)
  assert not any(feed(assembler, 10, 10.4, order=range(4, 8)))
  assert assembler.last_complete.sequence == 11
  assert assembler.reset_candidate is None


def test_reset_requires_confirmation_for_backward_sequence_and_reports_saturation():
  assembler = DiagnosticAssembler(1)
  feed(assembler, 40, 1)
  values = [0] * 12
  assert not any(feed(assembler, 0, 2, values))
  status = assembler.status(2.1)
  assert status['possible_reset_or_reordering']
  assert status['last_complete_sequence'] == 40 and not status['complete_fresh']
  assert sum(feed(assembler, 1, 3, values)) == 1
  status = assembler.status(3.1)
  assert status['counter_decrease'] and status['counter_reset_observations'] == 1
  assert status['sequence_discontinuities'] == 1
  assert status['sequence_alone_cannot_identify_reset']
  saturated = list(VALUES)
  for page in (0, 1, 2, 3, 7):
    saturated[page] = 0xFFFFFFFF
  feed(assembler, 2, 4, saturated)
  assert len(assembler.status(4.1)['saturated']) == 5


def test_all_sequences_reuse_after_256_seconds_and_timestamp_isolation():
  assembler = DiagnosticAssembler(0)
  for index in range(260):
    assert sum(feed(assembler, index % 256, index + 1)) == 1
  assert assembler.last_complete.sequence == 3
  # Timestamp reversal and stale payloads cannot join the latest partial snapshot.
  assembler.accept(0x1FA, 0, payload(0, 4), 261)
  assert not assembler.accept(0x1FA, 0, payload(1, 4), 260.9, now=261.1)
  assert not assembler.accept(0x1FA, 0, payload(1, 4), 250, now=261.1)
  assert assembler.status(261.1)['page_mask'] == 1


def test_counter_drop_with_forward_sequence_and_invalid_fifo_snapshot():
  assembler = DiagnosticAssembler(0)
  feed(assembler, 255, 1)
  lower = [0] * 12
  feed(assembler, 0, 2, lower)
  assert assembler.status(2.1)['counter_decrease']
  invalid = list(VALUES)
  invalid[5], invalid[6] = 10, 9
  assert not any(feed(assembler, 1, 3, invalid))
  assert assembler.last_complete.sequence == 0


def test_live_can_subscriber_preserves_publisher_and_selected_bus():
  with OpenpilotPrefix():
    publisher = messaging.PubMaster(['can'])
    receiver = DiagnosticReceiver(1)
    receiver.poll(time.monotonic())
    assert publisher.wait_for_readers_to_update('can', timeout=2)
    message = messaging.new_message('can', 13)
    message.valid = True
    frames = [{'address': 0x1FA, 'src': 1, 'dat': payload(page, 12)} for page in range(8)]
    frames += [
      {'address': 0x1FA, 'src': 0, 'dat': payload(0)},
      {'address': 0x123, 'src': 1, 'dat': b'vehicle'},
      {'address': 0x1FA, 'src': 6, 'dat': payload(0)},
      {'address': 0x1FA, 'src': 1, 'dat': firmware_payload()},
      {'address': 0x1FA, 'src': 0, 'dat': firmware_payload(99)},
    ]
    message.can = frames
    publisher.send('can', message)
    deadline = time.monotonic() + 2
    while receiver.assembler.last_complete is None and time.monotonic() < deadline:
      receiver.poll(time.monotonic())
      time.sleep(0.01)
    assert receiver.assembler.last_complete.sequence == 12
    assert receiver.assembler.stats['bus_frames'] == 10
    assert receiver.assembler.stats['valid_pages'] == 8
    assert receiver.assembler.stats['firmware_records'] == 1
    assert receiver.assembler.status(time.monotonic())['firmware']['version'] == '1.0.0'
    # The existing publisher still owns and can send on can.
    message.clear_write_flag()
    publisher.send('can', message)


@pytest.mark.parametrize('include_firmware', [False, True])
def test_rlog_diagnostic_cli(tmp_path, include_firmware):
  from openpilot.tools.lib.logreader import save_log

  path = tmp_path / 'rlog'
  events = []
  next_values = list(VALUES)
  next_values[0] += 11
  next_values[1] += 22
  for item, delta in zip(range(8, 12), (100, 200, 250, 300), strict=True):
    next_values[item] += delta
  for seq, stamp, values in [(9, 10, VALUES), (10, 11, next_values)]:
    for page in range(8):
      if include_firmware and page == 4:
        identity = messaging.new_message('can', 1, logMonoTime=int(stamp * 1e9) + 35_000_000)
        identity.valid = True
        identity.can = [{'address': 0x1FA, 'src': 2, 'dat': firmware_payload()}]
        events.append(identity.as_reader())
      message = messaging.new_message('can', 1, logMonoTime=int(stamp * 1e9) + page * 10_000_000)
      message.valid = True
      message.can = [{'address': 0x1FA, 'src': 2, 'dat': payload(page, seq, values)}]
      events.append(message.as_reader())
  save_log(str(path), events, compress=False)
  result = subprocess.run(
    [sys.executable, '-m', 'openpilot.system.flexray_logd.diagnostics', '--bus', '2', '--rlog', str(path)], capture_output=True, text=True, check=True
  )
  status = json.loads(result.stdout.splitlines()[-1])
  assert status['last_complete_sequence'] == 10 and status['page_mask'] == 255
  assert status['last_complete']['dadc_received'] == next_values[0]
  assert status['rates']['valid'] and status['rates']['dadc_frames_per_s'] == 11
  assert status['rates']['spi_service_bytes_per_s'] == 300
  assert status['stats']['valid_pages'] == 16 and status['stats']['completed'] == 2
  assert status['stats']['firmware_records'] == (2 if include_firmware else 0)
  assert status['firmware']['description'] == ('FPGA firmware 1.0.0 / build 1' if include_firmware else 'unknown')


@pytest.mark.parametrize('bus,timeout', list(itertools.product([-1, 4, 6], [0, 1.5])))
def test_configuration_rejects_unselected_or_spi_buses(bus, timeout):
  with pytest.raises(ValueError):
    DiagnosticAssembler(bus, timeout)


def test_partial_backward_sequence_and_expiry_stay_uncertain():
  assembler = DiagnosticAssembler(1)
  feed(assembler, 40, 1)
  assembler.accept(0x1FA, 1, payload(0, 0), 1.2)
  status = assembler.status(1.3)
  assert status['possible_reset_or_reordering']
  assert not status['latest_state_complete']
  assert status['assembling_sequence'] == 0 and status['page_mask'] == 1
  # Expiry cannot make the older pre-reset state suddenly become the latest again.
  status = assembler.status(2.8)
  assert not status['latest_state_complete'] and status['page_mask'] == 0
  assert status['possible_reset_or_reordering']
  feed(assembler, 41, 3)
  assert assembler.status(3.1)['latest_state_complete']
  assert not assembler.status(3.1)['possible_reset_or_reordering']
  assert not assembler.status(3.1)['rates']['valid']  # Interval crossed an unresolved reset/reorder observation.


def snapshot(seq, stamp, values):
  return Snapshot(seq, seq, stamp, stamp + 0.07, {p: payload(p, seq, values)[2:] for p in range(8)})


def test_rates_use_snapshot_clock_and_preserve_negative_margin():
  old = [100, 200, 0, 0, 32 | (32 << 16), 1000, 2000, 0, 10000, 20000, 30000, 40000]
  new = [200, 250, 1, 2, old[4], 1200, 2000, 1, 11200, 20800, 31500, 41500]
  result = snapshot_rates(snapshot(10, 10, old), snapshot(11, 11, new))
  assert result['valid'] and result['snapshot_dt_s'] == 1
  assert result['dadc_frames_per_s'] == 100 and result['bcm_frames_per_s'] == 50
  assert result['input_demand_bytes_per_s'] == 2000
  assert result['valid_output_bytes_per_s'] == result['spi_service_bytes_per_s'] == 1500
  assert result['observed_headroom_fraction'] == pytest.approx(-1 / 3)
  assert result['input_exceeds_service'] and result['fifo_growing'] and result['loss_observed']
  assert result['fifo_delta_bytes'] == 200
  assert result['nominal_spi_ceiling_bytes_per_s'] == 937500
  assert result['spi_service_bytes_per_s'] != result['nominal_spi_ceiling_bytes_per_s']
  assert not result['nominal_ceiling_is_measurement']
  # Sparse CAN pages can have sub-second inter-arrival jitter. They are not frame times.
  jittered = snapshot_rates(snapshot(10, 10, old), snapshot(11, 10.4, new))
  assert jittered['snapshot_dt_s'] == 1 and jittered['dadc_frames_per_s'] == 100


def test_wrapping_byte_counters_zero_service_and_prefetch_lead():
  old = [100, 100, 0, 0, 0, 0, 0, 0] + [0xFFFFFFF0] * 4
  new = [110, 120, 0, 0, 0, 0, 0, 0] + [0x10, 0x20, 0x31, 0x30]
  result = snapshot_rates(snapshot(255, 1, old), snapshot(0, 2, new))
  assert result['valid'] and result['byte_deltas'] == [32, 48, 65, 64]
  assert result['approx_padding_bytes_per_s'] == -1
  assert result['prefetch_ahead_of_service']
  assert result['spi_service_bytes_per_s'] == 64
  no_service = list(new)
  no_service[8:12] = [old[8] + 1, old[9] + 1, old[10], old[11]]
  result = snapshot_rates(snapshot(0, 1, old), snapshot(1, 2, no_service))
  assert result['valid'] and result['spi_service_bytes_per_s'] == 0
  assert result['observed_headroom_fraction'] is None


def test_missing_reset_saturation_and_uncertain_rate_intervals():
  old = [100, 100, 0, 0, 0, 0, 0, 0, 1000, 1000, 1000, 1000]
  new = [110, 120, 0, 0, 0, 0, 0, 0, 1200, 1300, 1400, 1500]
  gap = snapshot_rates(snapshot(10, 10, old), snapshot(12, 12, new))
  assert gap['valid'] and gap['missing_snapshots'] == 1 and gap['dadc_frames_per_s'] == 5
  for seq, stamp in [(10, 11), (16, 16), (11, 20), (9, 11)]:
    result = snapshot_rates(snapshot(10, 10, old), snapshot(seq, stamp, new))
    assert not result['valid'] and result['input_demand_bytes_per_s'] is None
  reset = [0] * 12
  assert not snapshot_rates(snapshot(10, 10, old), snapshot(11, 11, reset))['valid']
  assert not snapshot_rates(snapshot(10, 10, old), snapshot(11, 11, new), True)['valid']
  # A small counter going backward is an implausible modulo jump in this short window.
  bad_bytes = list(new)
  bad_bytes[11] = 1
  assert not snapshot_rates(snapshot(10, 10, old), snapshot(11, 11, bad_bytes))['valid']
  saturated_old = list(old)
  saturated_new = list(new)
  saturated_old[0] = saturated_new[0] = 0xFFFFFFFF
  saturated_old[2] = saturated_new[2] = 0xFFFFFFFF
  result = snapshot_rates(snapshot(10, 10, saturated_old), snapshot(11, 11, saturated_new))
  assert result['valid'] and result['dadc_frames_per_s'] is None and result['dadc_drop_increase'] is None
  assert result['frame_rates_reason'] == 'event_counter_saturated'
  assert result['input_demand_bytes_per_s'] == 500  # Wrapping byte counters remain usable.


def test_rate_status_occupancy_and_sustained_observations():
  values = [100, 100, 0, 0, 32 | (32 << 16), 65536, 131072, 0, 1000, 1000, 1000, 1000]
  assembler = DiagnosticAssembler(0)
  feed(assembler, 0, 1, values)
  assert not assembler.status(1.1)['rates']['valid']
  for seq in (1, 2):
    values = list(values)
    values[0] += 10
    values[5] += 1000
    values[8] += 1000
    values[9] += 1000
    values[10] += 1000
    values[11] += 1000
    feed(assembler, seq, seq + 1, values)
  status = assembler.status(3.1)
  assert status['rates']['valid']
  assert status['deficit_observation_intervals'] == 2
  assert status['fifo_growing_observation_intervals'] == 2
  assert status['fifo_peak_percent'] == 100
  assert status['fifo_current_percent'] == pytest.approx(100 * (65536 + 2000) / 131072)
  assert status['queue_usage_is_peak_not_current']
  assert not assembler.status(10)['rates']['valid']
  assert assembler.status(10)['rates']['observed_headroom_fraction'] is None


def firmware_payload(major=1, minor=0, patch=0, build_id=1):
  return bytes([0x2F, major, minor, patch]) + build_id.to_bytes(4, 'little')


def test_firmware_vector_and_independent_fields():
  from openpilot.system.flexray_logd.diagnostics import decode_firmware

  for major, minor, patch, build in [(1, 0, 0, 1), (2, 3, 4, 0x12345678), (255, 254, 253, 0xFFFFFFFF)]:
    data = firmware_payload(major, minor, patch, build)
    identity = decode_firmware(0x1FA, 1, data, 1)
    assert (identity.major, identity.minor, identity.patch, identity.build_id) == (major, minor, patch, build)
    assert identity.version == f'{major}.{minor}.{patch}'
    assert decode_page(0x1FA, 1, data, 1) is None
  assert firmware_payload() == bytes.fromhex('2F 01 00 00 01 00 00 00')


@pytest.mark.parametrize('tag', list(range(0x28, 0x2F)) + [0x1F, 0x3F, 0xFF])
def test_firmware_unsupported_records_rejected(tag):
  assembler = DiagnosticAssembler(1)
  data = bytes([tag]) + firmware_payload()[1:]
  assert not assembler.accept(0x1FA, 1, data, 1)
  status = assembler.status(1)
  assert status['firmware']['state'] == 'unknown'
  assert status['firmware']['version'] is None and status['firmware']['build_id'] is None
  assert status['page_mask'] == 0 and status['latest_sequence'] is None
  assert assembler.stats['valid_pages'] == 0


def test_firmware_invalid_bus_id_dlc_and_unknown():
  assembler = DiagnosticAssembler(1)
  data = firmware_payload()
  for address, bus, body in [(0x1F9, 1, data), (0x800001FA, 1, data), (0x1FA, 0, data), (0x1FA, 6, data), (0x1FA, 1, data[:-1]), (0x1FA, 1, data + b'\0')]:
    assert not assembler.accept(address, bus, body, 1)
    assert assembler.status(1)['firmware']['state'] == 'unknown'
  assert assembler.firmware is None and assembler.latest_sequence is None


def test_firmware_unknown_fresh_stale_duplicate_and_delayed():
  assembler = DiagnosticAssembler(1)
  assert assembler.status(1)['firmware']['description'] == 'unknown'
  assert assembler.accept(0x1FA, 1, firmware_payload(), 10)
  known = assembler.status(12.999)['firmware']
  assert known['description'] == 'FPGA firmware 1.0.0 / build 1'
  assert known['state'] == 'fresh' and known['received_at'] == 10
  stale = assembler.status(13)['firmware']
  assert stale['state'] == 'stale' and stale['age_s'] == 3
  assert stale['version'] == '1.0.0' and stale['received_at'] == 10
  assert assembler.accept(0x1FA, 1, firmware_payload(), 15)
  assert assembler.status(15)['firmware']['state'] == 'fresh'
  assert assembler.stats['firmware_changes'] == 0
  assert not assembler.accept(0x1FA, 1, firmware_payload(9), 14, now=16)
  assert assembler.status(16)['firmware']['version'] == '1.0.0'
  assert assembler.status(16)['firmware']['received_at'] == 15
  delayed = DiagnosticAssembler(1)
  assert delayed.accept(0x1FA, 1, firmware_payload(), 1, now=10)
  assert delayed.status(10)['firmware']['state'] == 'stale'
  assert delayed.status(10)['firmware']['received_at'] == 1
  assert not delayed.status(10)['firmware']['cryptographic_source_attestation']


def test_firmware_interleaved_has_no_sequence_mask_or_rate_effect():
  plain = DiagnosticAssembler(0)
  identified = DiagnosticAssembler(0)
  for sequence, stamp in [(255, 10), (0, 11)]:
    for page in range(8):
      if page == 4:
        before_mask = identified.status(stamp + 0.031)['page_mask']
        assert identified.accept(0x1FA, 0, firmware_payload(200, 3, 4, 0x12345678), stamp + 0.035)
        assert identified.status(stamp + 0.035)['page_mask'] == before_mask
        assert identified.latest_sequence == sequence  # Major=200 is never a sequence.
      for assembler in (plain, identified):
        assembler.accept(0x1FA, 0, payload(page, sequence), stamp + page * 0.01)
    assert identified.last_complete.words() == plain.last_complete.words() == tuple(VALUES)
    assert identified.rates == plain.rates
  assert identified.stats['valid_pages'] == 16 and identified.stats['completed'] == 2
  assert identified.stats['firmware_records'] == 2 and identified.stats['firmware_changes'] == 0
  assert plain.status(11.1)['firmware']['state'] == 'unknown'  # Older FPGA statistics keep working.


@pytest.mark.parametrize('identity', [(2, 0, 0, 1), (1, 1, 0, 1), (1, 0, 1, 1), (1, 0, 0, 2)])
def test_firmware_change_discards_pending_and_rate_baseline(identity):
  assembler = DiagnosticAssembler(1)
  assembler.accept(0x1FA, 1, firmware_payload(), 1)
  feed(assembler, 10, 2)
  feed(assembler, 11, 3)
  assert assembler.status(3.1)['rates']['valid']
  feed(assembler, 12, 4, order=range(4))
  assert assembler.status(4.04)['page_mask'] == 15
  assert assembler.accept(0x1FA, 1, firmware_payload(*identity), 4.05)
  status = assembler.status(4.06)
  assert status['page_mask'] == 0 and status['last_complete'] is None
  assert status['latest_sequence'] is None and status['pending'] == {}
  assert not status['rates']['valid'] and assembler.rates['reason'] == 'firmware_changed'
  assert assembler.stats['firmware_changes'] == 1
  # Delayed statistics stamped before the observed identity change cannot join the new epoch.
  assert not assembler.accept(0x1FA, 1, payload(4, 12), 4.01, now=4.2)
  feed(assembler, 0, 5)
  assert assembler.last_complete.sequence == 0 and not assembler.status(5.1)['rates']['valid']
  feed(assembler, 1, 6)
  assert assembler.status(6.1)['rates']['valid']


def test_firmware_bus_isolation_and_same_identity_reset():
  left, right = DiagnosticAssembler(0), DiagnosticAssembler(1)
  left.accept(0x1FA, 0, firmware_payload(1), 1)
  right.accept(0x1FA, 1, firmware_payload(2), 1)
  assert not left.accept(0x1FA, 1, firmware_payload(3), 2)
  assert left.status(2)['firmware']['version'] == '1.0.0'
  assert right.status(2)['firmware']['version'] == '2.0.0'
  for assembler in (left, right):
    feed(assembler, 10, 2)
    feed(assembler, 11, 3)
  assert left.accept(0x1FA, 0, firmware_payload(1), 3.1)
  assert left.status(3.1)['rates']['valid']  # An identical ID refresh is not an epoch reset.
  left.accept(0x1FA, 0, firmware_payload(1, build_id=2), 3.2)
  assert left.last_complete is None and right.last_complete.sequence == 11
  assert right.status(3.2)['rates']['valid']
  feed(right, 12, 4, [0] * 12)
  assert right.counter_decrease and right.reset_observations == 1
  assert not right.status(4.1)['rates']['valid']
  assert right.status(4.1)['firmware']['version'] == '2.0.0'
  assert right.stats['firmware_changes'] == 0  # Same identifier cannot exclude an FPGA reset.
