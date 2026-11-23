"""Bounded candidate publication windows, matching the existing raw analysis assumptions."""
EXPECTED = set(range(0x190, 0x197)) | {0x200 + 16 * slot + member for slot in range(40) for member in range(6)}


class RadarWindows:
  def __init__(self):
    self.current = None
    self.last_closed = None
    self.started = 0
    self.pre_boundary = 0
    self.closed = 0
    self.complete = 0

  def add(self, address, data, stamp, valid):
    if address == 0x190:
      if self.current is not None:
        self.last_closed = self.summary(closed=True)
        self.closed += 1
        self.complete += int(self.last_closed['completeCandidate'])
      self.started += 1
      self.current = {'sequence': self.started, 'counterRaw': data[0] & 15 if data else None,
                      'firstEventMonoTime': stamp, 'lastEventMonoTime': stamp, 'seen': {},
                      'lengthErrors': 0, 'counterMismatches': 0, 'invalidEvents': 0, 'duplicateFrames': 0}
    if self.current is None:
      self.pre_boundary += 1
      return
    c = self.current
    c['lastEventMonoTime'] = stamp
    c['duplicateFrames'] += int(address in c['seen'])
    c['seen'][address] = c['seen'].get(address, 0) + 1
    c['lengthErrors'] += int(len(data) != (7 if address >= 0x200 and address % 16 == 4 else 8))
    c['counterMismatches'] += int(not data or data[0] & 15 != c['counterRaw'])
    c['invalidEvents'] += int(not valid)

  def summary(self, closed=False):
    if self.current is None:
      return None
    c = self.current
    missing = sorted(EXPECTED - set(c['seen']))
    complete = not missing and not any(c[k] for k in ('duplicateFrames', 'lengthErrors', 'counterMismatches', 'invalidEvents'))
    return {k: v for k, v in c.items() if k != 'seen'} | {
      'closed': closed, 'missingAddresses': missing, 'completeCandidate': complete,
      'interpretation': 'addressLengthCounterStructureOnly;notPhysicalValidity',
      'slotMasks': [sum(1 << m for m in range(6) if 0x200 + 16 * slot + m in c['seen']) for slot in range(40)]}

  def snapshot(self):
    return {'current': self.summary(), 'lastClosed': self.last_closed,
            'closedCount': self.closed, 'completeCandidateCount': self.complete,
            'preBoundaryFrames': self.pre_boundary, 'boundaryHypothesis': 'src1:0x190;counterLow4'}
