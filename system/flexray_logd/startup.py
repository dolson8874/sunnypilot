"""Bounded startup buffering until loggerd consumes this publisher's probe.

The acknowledgement means the current writer/subscriber is ready. It is not a
per-frame disk durability acknowledgement. SPI capture never waits on this gate.
"""
from collections import deque
import time

from msgq import IpcError

from cereal import messaging
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import UnknownKeyName

MAX_STARTUP_BYTES = 4 * 1024 * 1024
FLUSH_BYTES = 256 * 1024


class LoggerStartup:
  def __init__(self, pm, params, telemetry, clock=time.monotonic, capacity=MAX_STARTUP_BYTES):
    self.pm, self.params, self.telemetry = pm, params, telemetry
    self.clock, self.capacity = clock, capacity
    self.ready = False
    self.queue = deque()
    self.buffered_bytes = self.buffered_frames = 0
    self.dropped_bytes = self.dropped_frames = 0
    self.probes = deque(maxlen=16)
    self.next_probe = self.next_check = self.next_report = 0.0
    self.transport_failures = 0
    self.next_error_report = 0.0

  def submit(self, frames):
    if not frames:
      return
    message = messaging.new_message('can', len(frames))
    message.valid = True
    message.can = frames
    data = message.to_bytes()
    counts = {src: sum(f['src'] == src for f in frames) for src in (4, 6)}
    received_at = self.clock()
    self.telemetry.ingested_counts(counts)
    if self.ready and not self.queue and self._send(data, counts, received_at):
      return
    if self.buffered_bytes + len(data) > self.capacity:
      self.dropped_bytes += len(data)
      self.dropped_frames += len(frames)
      self._report_drop('logger_startup_queue_full', message.logMonoTime)
      return
    self.queue.append((data, counts, received_at, len(frames)))
    self.buffered_bytes += len(data)
    self.buffered_frames += len(frames)

  def _transport_error(self, operation, error):
    self.transport_failures += 1
    self.ready = False
    self.probes.clear()
    now = self.clock()
    self.next_probe = now + 0.25
    self.next_check = now
    self.telemetry.last_error = f'{operation}: {error}'[:1024]
    if now >= self.next_error_report:
      cloudlog.error(f'FlexRay recorder transport failed: operation={operation} error={error} failures={self.transport_failures}')
      self.next_error_report = now + 1

  def _send(self, data, counts, received_at):
    try:
      self.pm.send('flexray', data)
    except (IpcError, OSError) as error:
      self._transport_error('send_frames', error)
      return False
    self.telemetry.received_counts(counts, received_at)
    return True

  def poll(self):
    now = self.clock()
    if not self.ready:
      if now >= self.next_probe:
        probe = messaging.new_message('can', 0)
        probe.valid = False
        try:
          self.pm.send('flexray', probe)
        except (IpcError, OSError) as error:
          self._transport_error('send_probe', error)
        else:
          self.probes.append(probe.logMonoTime)
        self.next_probe = now + 0.25
      if now >= self.next_check:
        try:
          ack = int(self.params.get('FlexrayLoggerAck'))
        except (ValueError, TypeError):
          ack = None
        except (OSError, UnknownKeyName) as error:
          ack = None
          self.telemetry.last_error = f'logger_ack_read: {error}'[:1024]
          if now >= self.next_error_report:
            cloudlog.error(f'FlexRay recorder readiness unavailable: error={error}')
            self.next_error_report = now + 1
        if ack in self.probes:
          self.ready = True
          cloudlog.info(f'FlexRay logger ready: probe={ack} buffered_frames={self.buffered_frames} buffered_bytes={self.buffered_bytes}')
        self.next_check = now + 0.1
    if self.ready:
      budget = FLUSH_BYTES
      while self.queue and budget > 0:
        data, counts, received_at, frames = self.queue[0]
        if not self._send(data, counts, received_at):
          break
        self.queue.popleft()
        self.buffered_bytes -= len(data)
        self.buffered_frames -= frames
        budget -= len(data)
    self.telemetry.logger_state(self.ready, self.buffered_frames, self.buffered_bytes,
                                self.dropped_frames, self.dropped_bytes)

  def _report_drop(self, reason, event_time=0, force=False):
    now = self.clock()
    if force or now >= self.next_report:
      cloudlog.error(f'FlexRay startup loss: reason={reason} event_mono_time={event_time} '
                     + f'dropped_frames={self.dropped_frames} dropped_bytes={self.dropped_bytes}')
      self.next_report = now + 1
    self.telemetry.logger_state(self.ready, self.buffered_frames, self.buffered_bytes,
                                self.dropped_frames, self.dropped_bytes)

  def close(self):
    # Do not wait for a recorder or spend unbounded time flushing at shutdown.
    deadline = self.clock() + 1.0
    while self.ready and self.queue and self.clock() < deadline:
      self.poll()
    if self.queue:
      first_time = int(self.queue[0][2] * 1e9)
      self.dropped_bytes += self.buffered_bytes
      self.dropped_frames += self.buffered_frames
      self.queue.clear()
      self.buffered_bytes = self.buffered_frames = 0
      reason = 'capture_stopped_with_startup_backlog' if self.ready else 'capture_stopped_before_logger_ready'
      self._report_drop(reason, first_time, force=True)
