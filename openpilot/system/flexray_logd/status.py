"""Low-rate capture health; never infer valid frames from USB bytes or heartbeats."""
import time

from openpilot.cereal import messaging

FRAME_FRESH_SECONDS = 2.0
STATUS_FRESH_SECONDS = 3.0


class CaptureStatus:
  def __init__(self, pm, clock=time.monotonic):
    self.pm = pm
    self.clock = clock
    self.phase = 'starting'
    self.pid = 0
    self.retry_count = 0
    self.last_read = 0.0
    self.last_frame = 0.0
    self.last_error = ''
    self.last_native_error = ''
    self.usb_bytes = 0
    self.logger = {'loggerReady': True, 'startupBufferedFrames': 0, 'startupBufferedBytes': 0,
                   'startupDroppedFrames': 0, 'startupDroppedBytes': 0}
    self.counts = {4: 0, 6: 0}
    self.arrival_counts = {4: 0, 6: 0}
    self.rates = {4: 0.0, 6: 0.0}
    self.previous_counts = dict(self.arrival_counts)
    self.sample_at = self.clock()
    self.published_at = None

  def starting(self, pid):
    self.phase = 'starting'
    self.pid = pid
    self.last_read = self.last_frame = 0.0
    self.usb_bytes = 0
    self.last_error = ''
    self.last_native_error = ''
    self.rates = {4: 0.0, 6: 0.0}
    self.previous_counts = dict(self.arrival_counts)
    self.sample_at = self.clock()
    self.publish(force=True)

  def received(self, frames):
    counts = {src: sum(frame['src'] == src for frame in frames) for src in self.counts}
    self.ingested_counts(counts)
    self.received_counts(counts, self.clock())

  def ingested_counts(self, counts):
    for src, count in counts.items():
      if src in self.arrival_counts:
        self.arrival_counts[src] += count

  def received_counts(self, counts, received_at):
    for src, count in counts.items():
      if src in self.counts:
        self.counts[src] += count
        if count:
          self.last_frame = max(self.last_frame, received_at)
    if self.phase not in ('retrying', 'stopped'):
      self.phase = 'waiting'

  def logger_state(self, ready, frames, byte_count, dropped_frames, dropped_bytes):
    self.logger = {'loggerReady': ready, 'startupBufferedFrames': frames, 'startupBufferedBytes': byte_count,
                   'startupDroppedFrames': dropped_frames, 'startupDroppedBytes': dropped_bytes}

  def native(self, health):
    self.last_read = health.get('last_successful_read_monotonic') or 0.0
    self.usb_bytes = health.get('delivered_bytes', 0)
    native_error = health.get('last_actual_error') or health.get('first_actual_error') or ''
    if native_error and native_error != self.last_native_error:
      self.last_error = native_error
    self.last_native_error = native_error
    if self.last_read and self.phase == 'starting':
      self.phase = 'waiting'

  def retrying(self, error):
    self.phase = 'retrying'
    self.retry_count += 1
    self.last_error = self.last_error or str(error)
    self.rates = {4: 0.0, 6: 0.0}
    self.publish(force=True)

  def snapshot(self, now=None):
    now = self.clock() if now is None else now
    state = self.phase
    if state not in ('retrying', 'stopped') and not self.logger['loggerReady'] and self.logger['startupBufferedFrames']:
      state = 'buffering'
    elif state not in ('retrying', 'stopped') and self.last_frame and 0 <= now - self.last_frame < FRAME_FRESH_SECONDS:
      state = 'receiving'
    return {'state': state, 'pid': self.pid, 'retryCount': self.retry_count,
            'lastReadMonoTime': int(self.last_read * 1e9), 'lastFrameMonoTime': int(self.last_frame * 1e9),
            'src4Frames': self.counts[4], 'src6Frames': self.counts[6],
            'src4Rate': self.rates[4] if state == 'receiving' else 0.0,
            'src6Rate': self.rates[6] if state == 'receiving' else 0.0,
            'lastError': self.last_error[:1024], 'usbDeliveredBytes': self.usb_bytes,
            'src4ReceivedFrames': self.arrival_counts[4], 'src6ReceivedFrames': self.arrival_counts[6]} | self.logger

  def publish(self, force=False):
    now = self.clock()
    if not force and self.published_at is not None and now - self.published_at < 1.0:
      return
    dt = now - self.sample_at
    if dt >= 1.0:
      self.rates = {src: (self.arrival_counts[src] - self.previous_counts[src]) / dt for src in self.counts}
      self.previous_counts = dict(self.arrival_counts)
      self.sample_at = now
    message = messaging.new_message('flexrayStatus')
    message.valid = True
    message.flexrayStatus = self.snapshot(now)
    self.pm.send('flexrayStatus', message)
    self.published_at = now


def display_state(status, now, enabled=True, received_at=None):
  """UI state depends on fresh telemetry AND an actual recent valid frame."""
  if not enabled:
    return 'disabled'
  if status is None or received_at is None or not 0 <= now - received_at < STATUS_FRESH_SECONDS:
    return 'unavailable'
  if status.state in ('retrying', 'stopped', 'buffering'):
    return status.state
  last_frame = status.lastFrameMonoTime / 1e9
  if last_frame > 0 and 0 <= now - last_frame < FRAME_FRESH_SECONDS:
    return 'receiving'
  return 'starting' if status.state == 'starting' else 'waiting'
