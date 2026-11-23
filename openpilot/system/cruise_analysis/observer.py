"""Read-only candidate views. Original can/flexray events remain the authoritative record."""
import copy
import uuid
from itertools import islice

from openpilot.system.cruise_analysis.radar import RadarWindows

VERSION = 1
# Host observation watchdogs: replayed batch gaps were <=103 ms (CAN/FR), <=171 ms (radar headers).
# Include the 0.5 s summary period: conservative 1/2 s availability limits are not physical validity timeouts.
MAX_EVENT_BYTES = 1 << 20
MAX_FRAMES = 4096


def motorola(data, start, size):
  value = 0
  for _ in range(size):
    value = (value << 1) | ((data[start // 8] >> (start % 8)) & 1)
    start = start + 15 if start % 8 == 0 else start - 1
  return value


def intel(data, start, size):
  return (int.from_bytes(data, 'little') >> start) & ((1 << size) - 1)


class Observer:
  def __init__(self, epoch=None):
    self.epoch = epoch or uuid.uuid4().hex
    self.frames = {}
    self.context = {}
    self.counts = {'events': 0, 'frames': 0, 'rejected': 0, 'conflicts': 0, 'errors': 0, 'budgetExceeded': 0}
    self.last_event = {}
    self.order = 0
    self.last_error = ''
    self.radar = RadarWindows()
    self.wheel_sample = None
    self.wheel_change = None

  def consume(self, event, host_ns, transport="can"):
    """No mutations of the caller's event, and no publishers in this decoder."""
    kind = event.which()
    self.counts['events'] += 1
    stamp = int(event.logMonoTime)
    self.last_event[transport if kind == 'can' else kind] = {'eventMonoTime': stamp, 'hostReceiveMonoTime': host_ns, 'valid': bool(event.valid)}
    if kind != 'can':
      values = getattr(event, kind).to_dict()
      self.context[kind] = {'eventMonoTime': stamp, 'valid': bool(event.valid), 'values': values}
      if kind == 'carState':
        wheels = values.get('wheelSpeeds', {})
        current = [wheels.get(w) for w in ('fl', 'fr', 'rl', 'rr')]
        self.wheel_change = {'dtNs': None, 'perWheelDeltaVPerSecond': None, 'reason': 'firstOrInvalidSample',
                                 'source': 'carStateWheelSpeeds;existingCANScale;publisherTime'}
        if event.valid and all(v is not None for v in current):
          if self.wheel_sample is not None:
            previous_time, previous = self.wheel_sample
            dt = stamp - previous_time
            self.wheel_change['dtNs'] = dt
            self.wheel_change['reason'] = 'hostGapPolicy500ms' if dt > 0 else 'nonPositiveDt'
            if dt > 500_000_000:
              self.wheel_change['reason'] = 'hostGapExceeded'
            if 0 < dt <= 500_000_000:
              self.wheel_change['perWheelDeltaVPerSecond'] = [(v - p) / (dt / 1e9) for v, p in zip(current, previous, strict=True)]
          self.wheel_sample = stamp, current
        else:
          self.wheel_sample = None
      return
    for frame in islice(event.can, MAX_FRAMES):
      self.order += 1
      src, address, data = int(frame.src), int(frame.address), bytes(frame.dat)
      # Returned/rejected sources (128/192 bits), CAN2, diagnostic and control IDs stay raw only.
      radar = transport == "can" and src == 1 and (0x190 <= address <= 0x196 or
                            0x200 <= address <= 0x475 and (address - 0x200) % 16 < 6)
      fr = transport == "flexray" and src == 6 and address in (0x1f, 0x31)
      can = transport == "can" and src == 0 and address in (0x100, 0x102, 0x10c)
      if not (radar or fr or can):
        continue
      if radar:
        self.radar.add(address, data, stamp, bool(event.valid))
      self.counts['frames'] += 1
      mux = data[1] % (4 if address == 0x1f else 8) if fr and len(data) >= 2 else -1
      key = f'{src}:{address}:{mux}'
      previous = self.frames.get(key)
      conflict = previous is not None and previous['eventMonoTime'] == stamp and previous['hex'] != data.hex()
      self.counts['conflicts'] += int(conflict)
      reason = None
      if not event.valid:
        reason = 'invalidEvent'
      elif fr and len(data) != 31:
        reason = 'length'
      elif fr and not data[0] & 4:
        reason = 'nfi0'
      elif radar and len(data) != (7 if address >= 0x200 and address % 16 == 4 else 8):
        reason = 'length'
      elif can and len(data) != 8:
        reason = 'length'
      values = {}
      if reason is None:
        if src == 6 and address == 0x1f and mux == 1:
          values = {'dadcRaw16': motorola(data, 95, 16), 'byte10': data[10],
                        'm58': motorola(data, 58, 1), 'm58u2': motorola(data, 58, 2)}
        elif src == 6 and address == 0x1f and mux == 2:
          values = {'eRaw': data[12]}
        elif src == 6 and address == 0x31 and mux == 1:
          values = {name: motorola(data, bit, width) for name, bit, width in (
            ('hRaw', 175, 8), ('gapRaw', 153, 2), ('iconRaw', 183, 4),
            ('hudOnRaw', 165, 1), ('greenRaw', 154, 1), ('modeRaw', 146, 3))}
        elif src == 0:
          values = {'word56Raw': int.from_bytes(data[5:7], 'big')} if address == 0x10c else {}
        elif radar and address >= 0x200:
          member = address % 16
          if member == 2:
            values = {'aRaw': intel(data, 27, 12), 'bRaw': intel(data, 28, 11), 'vRaw': intel(data, 39, 12)}
          elif member == 4:
            values = {'indexRaw': intel(data, 20, 6)}
      self.counts['rejected'] += int(reason is not None)
      self.frames[key] = {'src': src, 'address': address, 'mux': mux, 'hex': data.hex(), 'length': len(data),
                              'eventMonoTime': stamp, 'hostReceiveMonoTime': host_ns, 'order': self.order,
                              'excluded': reason, 'sameTimeConflict': conflict, 'values': values,
                              'crc': 'unknownInObserver;nativeTransportValidatesFR' if fr else 'unknown'}
    if len(event.can) > MAX_FRAMES:
      self.counts['budgetExceeded'] += len(event.can) - MAX_FRAMES

  def snapshot(self, now_ns):
    frames = copy.deepcopy(self.frames)
    for frame in frames.values():
      frame['ageNs'] = now_ns - frame['eventMonoTime']
      frame['staleAfterNs'] = 2_000_000_000 if frame['src'] == 1 else 1_000_000_000
      frame['freshness'] = ('clockConflict' if frame['ageNs'] < 0 else
                            'stale' if frame['ageNs'] >= frame['staleAfterNs'] else 'recent')
    slots = []
    for slot in range(40):
      members = [frames.get(f'1:{0x200 + 16 * slot + member}:-1') for member in range(6)]
      received = [m for m in members if m is not None]
      # Do not combine counter reuse across publication cycles into a completed group.
      slots.append({'slot': slot, 'memberMask': sum(1 << i for i, m in enumerate(members) if m is not None),
                        'assembly': 'notAssembled', 'indexRaw': members[4]['values'].get('indexRaw') if members[4] else None,
                        'lastEventMonoTime': max((m['eventMonoTime'] for m in received), default=None)})
    return {'version': VERSION, 'epoch': self.epoch, 'snapshotMonoTime': now_ns, 'counts': dict(self.counts),
                'lastError': self.last_error, 'wheelChange': copy.deepcopy(self.wheel_change), 'frames': frames, 'slots': slots,
                'context': copy.deepcopy(self.context), 'radarWindows': self.radar.snapshot(),
                'inputs': copy.deepcopy(self.last_event), 'physicalInterpretation': 'candidate',
                'sensorMeasurementTime': 'unknown', 'fpgaBeforeAfter': 'unknown', 'fpgaLoadedVersion': 'unknown',
                'freshnessPolicy': 'hostAvailabilityV1:CAN_FR1000ms;radar2000ms;notSensorValidity', 'transportLoss': 'unknown',
                'timing': 'eventMonoTimeIsPublisherBatchTime;hostReceiveMonoTimeIsObserverReceiveTime'}
