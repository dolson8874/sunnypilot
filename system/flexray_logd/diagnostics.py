"""Read-only FPGA logging diagnostics v2 from a selected physical Panda CAN bus.

Packed pages form one 48-byte snapshot. FPGA byte rates describe logging wire
bytes, never physical FlexRay occupancy or acknowledgement of USB delivery.
"""

import argparse
from dataclasses import dataclass, field
import json
import math
import struct
import time

DIAGNOSTIC_ID = 0x1FA
FIFO_CAPACITY = 131072
COUNTER_ITEMS = (0, 1, 2, 3, 7)  # Saturating event counters; bytes 8..11 wrap instead.
ITEM_NAMES = (
  'dadc_received',
  'bcm_received',
  'dadc_dropped',
  'bcm_dropped',
  'queue_peaks',
  'fifo_bytes',
  'fifo_peak_bytes',
  'fifo_full_entries',
  'dadc_input_bytes',
  'bcm_input_bytes',
  'spi_valid_prefetch_bytes',
  'spi_completed_bytes',
)
NOMINAL_SPI_BYTES_PER_S = 7500000 / 8
MAX_RATE_SNAPSHOT_GAP = 5
RATE_FIELDS = (
  'dadc_frames_per_s',
  'bcm_frames_per_s',
  'dadc_input_bytes_per_s',
  'bcm_input_bytes_per_s',
  'input_demand_bytes_per_s',
  'valid_output_bytes_per_s',
  'spi_service_bytes_per_s',
  'approx_padding_bytes_per_s',
  'observed_headroom_fraction',
  'fifo_delta_bytes',
  'input_exceeds_service',
  'fifo_growing',
  'spi_read_not_progressing',
  'loss_observed',
  'prefetch_ahead_of_service',
)


@dataclass(frozen=True)
class DiagnosticPage:
  bus: int
  sequence: int
  page: int
  chunk: bytes


def decode_page(address: int, bus: int, data: bytes, expected_bus: int) -> DiagnosticPage | None:
  if bus != expected_bus or address != DIAGNOSTIC_ID or len(data) != 8 or not 0x20 <= data[0] <= 0x27:
    return None
  return DiagnosticPage(bus, data[1], data[0] & 15, bytes(data[2:8]))


@dataclass(frozen=True)
class FirmwareIdentity:
  major: int
  minor: int
  patch: int
  build_id: int

  @property
  def version(self) -> str:
    return f'{self.major}.{self.minor}.{self.patch}'


def decode_firmware(address: int, bus: int, data: bytes, expected_bus: int) -> FirmwareIdentity | None:
  if bus != expected_bus or address != DIAGNOSTIC_ID or len(data) != 8 or data[0] != 0x2F:
    return None
  return FirmwareIdentity(data[1], data[2], data[3], int.from_bytes(data[4:8], 'little'))


@dataclass
class Snapshot:
  sequence: int
  generation: int
  first: float
  last: float
  pages: dict[int, bytes] = field(default_factory=dict)
  conflicted: bool = False

  @property
  def mask(self) -> int:
    return sum(1 << page for page in self.pages)

  def words(self) -> tuple[int, ...]:
    if self.mask != 0xFF:
      raise ValueError('all eight packed pages are required')
    return struct.unpack('<12I', b''.join(self.pages[page] for page in range(8)))

  def values(self) -> dict:
    words = self.words()
    result = {name: words[index] for index, name in enumerate(ITEM_NAMES) if index != 4}
    result['dadc_queue_peak'] = words[4] & 0xFFFF
    result['bcm_queue_peak'] = words[4] >> 16
    return result


def monotonic_decrease(previous: Snapshot, current: Snapshot) -> bool:
  old, new = previous.words(), current.words()
  # FIFO current usage can fall normally; byte counters can wrap normally.
  return any(new[i] < old[i] for i in COUNTER_ITEMS) or new[6] < old[6] or (new[4] & 0xFFFF) < (old[4] & 0xFFFF) or (new[4] >> 16) < (old[4] >> 16)


def unknown_rates(reason: str) -> dict:
  return dict.fromkeys(RATE_FIELDS) | {
    'valid': False,
    'reason': reason,
    'nominal_spi_ceiling_bytes_per_s': NOMINAL_SPI_BYTES_PER_S,
    'nominal_ceiling_is_measurement': False,
  }


def snapshot_rates(previous: Snapshot | None, current: Snapshot, reset_or_ambiguous: bool = False) -> dict:
  if previous is None:
    return unknown_rates('no_previous_snapshot')
  steps = (current.sequence - previous.sequence) & 0xFF
  host_dt = current.first - previous.first
  if reset_or_ambiguous or monotonic_decrease(previous, current):
    return unknown_rates('reset_or_sequence_ambiguity')
  if not 1 <= steps <= MAX_RATE_SNAPSHOT_GAP:
    return unknown_rates('snapshot_gap_or_sequence_ambiguity')
  # Derive dt from the specified 1 Hz snapshot clock, not eight CAN arrival gaps.
  dt = float(steps)
  if host_dt <= 0 or abs(host_dt - dt) > 1.0:
    return unknown_rates('uncertain_snapshot_timing')
  old, new = previous.words(), current.words()
  delta = [(new[i] - old[i]) & 0xFFFFFFFF for i in range(8, 12)]
  # A half-range jump in <=5 snapshots cannot be safely distinguished from reset.
  if any(value > 0x7FFFFFFF for value in delta):
    return unknown_rates('ambiguous_byte_counter_jump')
  event_delta = [None if old[i] == 0xFFFFFFFF or new[i] == 0xFFFFFFFF else new[i] - old[i] for i in COUNTER_ITEMS]
  dadc, bcm, output, service = [value / dt for value in delta]
  result = unknown_rates('ok') | {
    'valid': True,
    'snapshot_dt_s': dt,
    'host_first_page_dt_s': host_dt,
    'sequence_steps': steps,
    'missing_snapshots': steps - 1,
    'dadc_frames_per_s': None if event_delta[0] is None else event_delta[0] / dt,
    'bcm_frames_per_s': None if event_delta[1] is None else event_delta[1] / dt,
    'frame_rates_reason': 'event_counter_saturated' if None in event_delta[:2] else 'ok',
    'dadc_input_bytes_per_s': dadc,
    'bcm_input_bytes_per_s': bcm,
    'input_demand_bytes_per_s': dadc + bcm,
    'valid_output_bytes_per_s': output,
    'spi_service_bytes_per_s': service,
    'spi_read_not_progressing': service == 0 and dadc + bcm > 0 and new[5] == FIFO_CAPACITY,
    'approx_padding_bytes_per_s': service - output,
    'prefetch_ahead_of_service': output > service,
    'observed_headroom_fraction': (service - dadc - bcm) / service if service else None,
    'input_exceeds_service': dadc + bcm > service,
    'fifo_delta_bytes': new[5] - old[5],
    'fifo_growing': new[5] > old[5],
    'dadc_drop_increase': event_delta[2],
    'bcm_drop_increase': event_delta[3],
    'fifo_full_entry_increase': event_delta[4],
    'loss_observed': True if any(value is not None and value > 0 for value in event_delta[2:4]) else (None if None in event_delta[2:4] else False),
    'byte_deltas': delta,
  }
  return result


class DiagnosticAssembler:
  def __init__(self, bus: int, timeout: float = 1.5, stale_after: float = 2.5):
    if bus not in range(4) or not 0 < timeout < 128 or not math.isfinite(stale_after) or stale_after <= 0:
      raise ValueError('select a physical Panda bus 0..3 and finite positive time limits')
    self.bus, self.timeout, self.stale_after = bus, timeout, stale_after
    self.firmware: FirmwareIdentity | None = None
    self.firmware_received_at: float | None = None
    self.firmware_epoch_started_at: float | None = None
    self.pending: dict[int, Snapshot] = {}
    self.retired: dict[int, float] = {}
    self.latest_sequence: int | None = None
    self.latest_generation = 0
    self.last_complete: Snapshot | None = None
    self.reset_candidate: Snapshot | None = None
    self.reset_suspected = False
    self.counter_decrease = False
    self.rates = unknown_rates('no_previous_snapshot')
    self.spi_stalled_intervals = 0
    self.deficit_intervals = 0
    self.fifo_growing_intervals = 0
    self.reset_observations = 0
    self.sequence_discontinuities = 0
    self.stats = {
      'bus_frames': 0,
      'id_frames': 0,
      'valid_pages': 0,
      'invalid_pages': 0,
      'invalid_snapshots': 0,
      'duplicates': 0,
      'conflicts': 0,
      'expired': 0,
      'old_pages': 0,
      'completed': 0,
      'firmware_records': 0,
      'firmware_changes': 0,
      'invalid_firmware_records': 0,
      'old_firmware_records': 0,
    }

  def accept_firmware(self, address: int, bus: int, data: bytes, received_at: float, now: float) -> bool:
    identity = decode_firmware(address, bus, data, self.bus)
    if identity is None:
      self.stats['invalid_firmware_records'] += 1
      return False
    if received_at > now or (self.firmware_received_at is not None and received_at < self.firmware_received_at):
      self.stats['old_firmware_records'] += 1
      return False
    if self.firmware is not None and identity != self.firmware:
      self.stats['firmware_changes'] += 1
      self.firmware_epoch_started_at = received_at
      self.pending.clear()
      self.retired.clear()
      self.latest_sequence = None
      self.latest_generation = 0
      self.last_complete = None
      self.reset_candidate = None
      self.reset_suspected = False
      self.counter_decrease = False
      self.spi_stalled_intervals = 0
      self.rates = unknown_rates('firmware_changed')
      self.deficit_intervals = 0
      self.fifo_growing_intervals = 0
    # First observation establishes identity without discarding statistics already
    # received from an unidentified FPGA. Identical repeats only refresh last-seen.
    self.firmware = identity
    self.firmware_received_at = received_at
    self.stats['firmware_records'] += 1
    return True

  def firmware_status(self, now: float) -> dict:
    identity = self.firmware
    age = None if self.firmware_received_at is None else max(0.0, now - self.firmware_received_at)
    return {
      'state': 'unknown' if identity is None else ('stale' if age >= 3.0 else 'fresh'),
      'version': None if identity is None else identity.version,
      'major': None if identity is None else identity.major,
      'minor': None if identity is None else identity.minor,
      'patch': None if identity is None else identity.patch,
      'build_id': None if identity is None else identity.build_id,
      'received_at': self.firmware_received_at,
      'age_s': age,
      'description': 'unknown' if identity is None else f'FPGA firmware {identity.version} / build {identity.build_id}',
      'format_version': None if identity is None else 2,
      'build_id_is_manual_release_number': True,
      'cryptographic_source_attestation': False,
    }

  def expire(self, now: float) -> None:
    for seq, snapshot in list(self.pending.items()):
      if now - snapshot.first >= self.timeout:
        del self.pending[seq]
        self.retired[seq] = now
        self.stats['expired'] += 1
    self.retired = {seq: stamp for seq, stamp in self.retired.items() if now - stamp < self.timeout}
    if self.reset_candidate and now - self.reset_candidate.last >= self.timeout:
      self.reset_candidate = None

  def accept(self, address: int, bus: int, data: bytes, received_at: float, now: float | None = None) -> bool:
    now = received_at if now is None else now
    self.expire(now)
    if bus == self.bus:
      self.stats['bus_frames'] += 1
    if bus != self.bus or address != DIAGNOSTIC_ID:
      return False
    self.stats['id_frames'] += 1
    # 0x2F has no snapshot sequence: byte1 is firmware major, never a page key.
    if data and data[0] == 0x2F:
      return self.accept_firmware(address, bus, data, received_at, now)
    page = decode_page(address, bus, data, self.bus)
    if page is None:
      self.stats['invalid_pages'] += 1
      return False
    if (
      now - received_at >= self.timeout
      or received_at > now
      or page.sequence in self.retired
      or (self.firmware_epoch_started_at is not None and received_at < self.firmware_epoch_started_at)
    ):
      self.stats['old_pages'] += 1
      return False
    self.stats['valid_pages'] += 1
    if self.latest_sequence is None:
      self.latest_sequence = page.sequence
    delta = ((page.sequence - self.latest_sequence + 128) % 256) - 128
    if delta > 0:
      self.latest_generation += delta
      self.latest_sequence = page.sequence
    generation = self.latest_generation + min(delta, 0)
    snapshot = self.pending.get(page.sequence)
    if snapshot is None:
      snapshot = Snapshot(page.sequence, generation, received_at, received_at)
      self.pending[page.sequence] = snapshot
      if self.last_complete and generation <= self.last_complete.generation and received_at > self.last_complete.last:
        self.reset_suspected = True
    if received_at < snapshot.first:
      self.stats['old_pages'] += 1
      return False
    snapshot.last = received_at
    if page.page in snapshot.pages:
      self.stats['duplicates'] += 1
      if snapshot.pages[page.page] != page.chunk:
        # Could be a reset or sequence reuse: discard the entire ambiguous assembly.
        snapshot.conflicted = True
        self.reset_suspected = True
        self.stats['conflicts'] += 1
      return False
    snapshot.pages[page.page] = page.chunk
    if snapshot.mask != 0xFF or snapshot.conflicted:
      return False
    del self.pending[page.sequence]
    self.retired[page.sequence] = now
    words = snapshot.words()
    if words[5] > words[6] or words[5] > FIFO_CAPACITY or words[6] > FIFO_CAPACITY:
      self.stats['invalid_snapshots'] += 1
      return False
    previous = self.last_complete
    epoch_changed = False
    if previous and snapshot.generation <= previous.generation and snapshot.first <= previous.first:
      self.stats['old_pages'] += 8
      return False
    if previous and snapshot.generation <= previous.generation:
      # A complete older/reused sequence is not a new latest state. A possible
      # reset requires two successive complete snapshots before accepting an epoch.
      candidate = self.reset_candidate
      if (
        candidate is None or (snapshot.sequence - candidate.sequence) % 256 != 1 or snapshot.first <= candidate.last or monotonic_decrease(candidate, snapshot)
      ):
        self.reset_candidate = snapshot
        self.stats['old_pages'] += 8
        return False
      epoch_changed = True
      self.sequence_discontinuities += 1
      self.latest_generation = previous.generation + 1
      snapshot.generation = self.latest_generation
      self.latest_sequence = snapshot.sequence
      self.pending.clear()
    self.counter_decrease = bool(previous and monotonic_decrease(previous, snapshot))
    if self.counter_decrease:
      self.reset_observations += 1
    self.rates = snapshot_rates(previous, snapshot, self.counter_decrease or epoch_changed or self.reset_suspected)
    self.spi_stalled_intervals = self.spi_stalled_intervals + 1 if self.rates.get('spi_read_not_progressing') else 0
    self.deficit_intervals = self.deficit_intervals + 1 if self.rates['valid'] and self.rates['input_exceeds_service'] else 0
    self.fifo_growing_intervals = self.fifo_growing_intervals + 1 if self.rates['valid'] and self.rates['fifo_growing'] else 0
    self.reset_candidate = None
    self.reset_suspected = False
    self.last_complete = snapshot
    self.stats['completed'] += 1
    return True

  def status(self, now: float) -> dict:
    self.expire(now)
    complete = self.last_complete
    age = None if complete is None else max(0.0, now - complete.last)
    active = max(
      (s for s in self.pending.values() if complete is None or s.generation > complete.generation or (self.reset_suspected and s.first > complete.last)),
      key=lambda s: s.first if self.reset_suspected else s.generation,
      default=None,
    )
    latest_complete = bool(complete and complete.generation == self.latest_generation and complete.sequence == self.latest_sequence)
    latest_fresh = bool(latest_complete and age <= self.stale_after and active is None and not self.reset_suspected)
    rates = dict(self.rates) if latest_fresh else unknown_rates(self.rates['reason'] if complete is None else 'snapshot_incomplete_or_stale')
    return {
      'bus': self.bus,
      'firmware': self.firmware_status(now),
      'latest_sequence': self.latest_sequence,
      'last_complete_age': age,
      'complete_fresh': bool(complete and age <= self.stale_after and not self.reset_suspected),
      'latest_state_complete': latest_fresh,
      'last_complete_sequence': None if complete is None else complete.sequence,
      'last_complete': None if complete is None else complete.values(),
      'assembling_sequence': None if active is None else active.sequence,
      'page_mask': (active.mask if active else (0xFF if latest_complete and not self.reset_suspected else 0)),
      'pending': {str(seq): {'mask': s.mask, 'age': now - s.first, 'conflicted': s.conflicted} for seq, s in self.pending.items()},
      'possible_reset_or_reordering': self.reset_suspected,
      'counter_decrease': self.counter_decrease,
      'counter_reset_observations': self.reset_observations,
      'sequence_discontinuities': self.sequence_discontinuities,
      'sequence_alone_cannot_identify_reset': True,
      'saturated': [] if complete is None else [ITEM_NAMES[i] for i in COUNTER_ITEMS if complete.words()[i] == 0xFFFFFFFF],
      'rates': rates,
      'spi_read_state': ('SPI 읽기 미진행' if self.spi_stalled_intervals >= 2 else
                         'awaiting_progress_confirmation' if rates.get('spi_read_not_progressing') else
                         'progressing' if rates.get('spi_service_bytes_per_s', 0) else 'unknown') if rates['valid'] else 'unknown',
      'fifo_current_percent': None if complete is None else 100 * complete.words()[5] / FIFO_CAPACITY,
      'fifo_peak_percent': None if complete is None else 100 * complete.words()[6] / FIFO_CAPACITY,
      'queue_usage_is_peak_not_current': True,
      'spi_stalled_observation_intervals': self.spi_stalled_intervals if rates['valid'] else 0,
      'deficit_observation_intervals': self.deficit_intervals if rates['valid'] else 0,
      'fifo_growing_observation_intervals': self.fifo_growing_intervals if rates['valid'] else 0,
      'stats': dict(self.stats),
    }


class DiagnosticReceiver:
  """Additional CAN subscriber; no publisher and no control-side effects."""

  def __init__(self, bus: int):
    from cereal import messaging

    self.sock = messaging.sub_sock('can', conflate=False)
    self.assembler = DiagnosticAssembler(bus)
    self.last_report = 0.0

  def poll(self, now: float) -> dict | None:
    from cereal import messaging

    updated = False
    # Bound work so a busy CAN bus cannot starve SPI publication.
    for _ in range(64):
      event = messaging.recv_one_or_none(self.sock)
      if event is None:
        break
      now = max(now, time.monotonic())
      if event.which() == 'can' and event.valid:
        for frame in event.can:
          updated = self.assembler.accept(frame.address, frame.src, bytes(frame.dat), event.logMonoTime / 1e9, now) or updated
    if updated or now - self.last_report >= 1.0:
      self.last_report = now
      return self.assembler.status(now)
    return None


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--bus', type=int, choices=range(4), required=True, help='physical Panda receive bus, never SPI source 4/6')
  parser.add_argument('--rlog', help='read an existing route/log instead of live CAN')
  args = parser.parse_args()
  if args.rlog:
    from openpilot.tools.lib.logreader import LogReader

    assembler = DiagnosticAssembler(args.bus)
    now = 0.0
    for event in LogReader(args.rlog):
      now = max(now, event.logMonoTime / 1e9)
      if event.which() == 'can' and event.valid:
        for frame in event.can:
          if assembler.accept(frame.address, frame.src, bytes(frame.dat), event.logMonoTime / 1e9, now):
            print(json.dumps(assembler.status(now), sort_keys=True))
    print(json.dumps(assembler.status(now), sort_keys=True))
  else:
    receiver = DiagnosticReceiver(args.bus)
    try:
      while True:
        status = receiver.poll(time.monotonic())
        if status is not None:
          print(json.dumps(status, sort_keys=True), flush=True)
        time.sleep(0.01)
    except KeyboardInterrupt:
      pass


if __name__ == '__main__':
  main()
