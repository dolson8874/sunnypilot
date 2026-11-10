"""Bounded native stderr bridge. The drain thread never calls logging or IPC."""
import json
import os
import select
import re
import threading
import time
from collections import deque

from openpilot.common.swaglog import cloudlog


class NativeCaptureLog:
  MAX_LINE = 1024
  MAX_LINES = 16

  def __init__(self, process):
    self.process = process
    self.lines = deque(maxlen=self.MAX_LINES)
    self.tail = deque(maxlen=8)
    self.initialization = []
    self.initialization_sent = 0
    self.lock = threading.Lock()
    self.cancel = threading.Event()
    self.eof = False
    self.first_error = None
    self.last_error = None
    self.last_read = None
    self.delivered = 0
    self.dropped = 0
    self.total_bytes = 0
    self.last_report = 0.0
    self.thread = threading.Thread(target=self._drain, name='flexray-stderr', daemon=True)
    self.thread.start()

  def _line(self, raw):
    line = raw.decode('utf-8', errors='replace')
    with self.lock:
      self.tail.append(line)
      if line.startswith('native ') and len(self.initialization) < 64:
        self.initialization.append(line)
      if len(self.lines) == self.MAX_LINES:
        self.dropped += 1
      self.lines.append(line)
      error = ('failed' in line.lower() or re.search(r'(?:rc=-|libusb_code=-|error=-?[1-9]|errno=[1-9])', line)
               or line.startswith('flexray: ') and not line.startswith('flexray: input='))
      # A detach result alone is not an open/claim failure. Retain it in the
      # initialization trace without presenting it as the capture's cause.
      if error and 'stage=kernel_driver_detach ' not in line:
        if self.first_error is None:
          self.first_error = line
        self.last_error = line
      read_time = re.search(r'last_read_monotonic=([0-9.]+)', line)
      if read_time is not None:
        try:
          timestamp = float(read_time[1])
          if timestamp > 0:
            self.last_read = timestamp
        except ValueError:
          pass
      elif 'stage=first_bulk_read success' in line:
        self.last_read = time.monotonic()
      if line.startswith('SPI:'):
        fields = dict(field.split('=', 1) for field in line.split() if '=' in field)
        try:
          delivered = int(fields.get('delivered', self.delivered))
          if delivered > self.delivered and read_time is None:
            self.last_read = time.monotonic()
          self.delivered = delivered
        except ValueError:
          pass

  def _drain(self):
    pending = bytearray()
    pipe = self.process.stderr
    try:
      os.set_blocking(pipe.fileno(), False)
      while not self.cancel.is_set():
        if not select.select([pipe], [], [], 0.05)[0]:
          continue
        try:
          block = os.read(pipe.fileno(), 8192)
        except BlockingIOError:
          continue
        if not block:
          self.eof = True
          break
        self.total_bytes += len(block)
        # Split long lines as well as newline-delimited records: bounded even
        # when a broken child writes megabytes without a single newline.
        pending.extend(block)
        while pending:
          newline = pending.find(b'\n', 0, self.MAX_LINE)
          if newline >= 0:
            self._line(pending[:newline])
            del pending[:newline + 1]
          elif len(pending) >= self.MAX_LINE:
            self._line(pending[:self.MAX_LINE])
            del pending[:self.MAX_LINE]
          else:
            break
      if pending:
        self._line(pending)
    finally:
      pipe.close()

  def report(self, final=False):
    now = time.monotonic()
    if not final and now - self.last_report < 1:
      return
    with self.lock:
      lines = list(self.lines)
      self.lines.clear()
      info = {'pid': self.process.pid, 'returncode': self.process.poll(), 'stderr': lines,
              'suppressed_lines': self.dropped, 'first_error': self.first_error,
              'last_error': self.last_error, 'stderr_eof': self.eof,
              'initialization': self.initialization[self.initialization_sent:]}
      self.initialization_sent = len(self.initialization)
      if final:
        info['stderr_tail'] = list(self.tail)
    cloudlog.info('FlexRay native: ' + json.dumps(info))
    self.last_report = now

  def finish(self):
    # After wait(), read the short-lived child's pipe through EOF. A descendant
    # retaining the fd must not hold shutdown forever.
    self.thread.join(timeout=1)
    if self.thread.is_alive():
      self.cancel.set()
      self.thread.join(timeout=0.2)
    self.report(final=True)

  def health(self):
    with self.lock:
      return {'last_successful_read_monotonic': self.last_read,
              'last_successful_read_age_s': None if self.last_read is None else time.monotonic() - self.last_read, 'last_actual_error': self.last_error,
              'delivered_bytes': self.delivered}
