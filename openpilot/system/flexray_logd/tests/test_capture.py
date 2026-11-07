import pathlib
import resource
import signal
import socket
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def crc(bits, width, initial, polynomial):
  result = initial
  for bit in bits:
    feedback = ((result >> (width - 1)) ^ bit) & 1
    result = (result << 1) & ((1 << width) - 1)
    if feedback:
      result ^= polynomial
  return result


def bits(value, width):
  return [(value >> i) & 1 for i in range(width - 1, -1, -1)]


def frame():
  flags, identifier, words, counter = 3, 0x47F, 2, 7
  header_crc = crc(bits((flags << 18) | (identifier << 7) | words, 20), 11, 0x1A, 0x385)
  header = ((flags << 35) | (identifier << 24) | (words << 17) | (header_crc << 6) | counter).to_bytes(5, 'big')
  payload = b'\x12\x34\x56\x78'
  trailer = crc([bit for byte in header + payload for bit in bits(byte, 8)], 24, 0xFEDCBA, 0x5D6DCB)
  return b'\xca\xa0' + header + bytes([flags, counter]) + payload + trailer.to_bytes(3, 'big')


class CaptureTest(unittest.TestCase):
  def run_binary(self, name, *args):
    return subprocess.run([str(ROOT / name), *map(str, args)], capture_output=True, timeout=5)

  def test_rotation_and_no_overwrite(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      data = frame() * 200
      source = path / 'input'
      source.write_bytes(data)
      sentinel = path / 'flexray_dump-file.log'
      sentinel.write_bytes(b'previous capture')
      result = self.run_binary('flexray_dump', '-f', source, '-o', path, '-m', 127)
      self.assertEqual(result.returncode, 0, result.stderr)
      files = sorted(path.glob('flexray-*.log'))
      self.assertGreater(len(files), 1)
      self.assertTrue(all(file.stat().st_size <= 127 for file in files))
      self.assertEqual(b''.join(file.read_bytes() for file in files), data)
      self.assertEqual(sentinel.read_bytes(), b'previous capture')

  def test_startup_errors_and_empty_loop(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source = path / 'empty'
      source.touch()
      for args in [('-f', path / 'missing'), ('-f', source, '-o', path / 'missing'),
                   ('-f', source, '-l', '-o', path), ('-m', '-1'), ('-l',)]:
        result = self.run_binary('flexray_dump', *args)
        self.assertNotEqual(result.returncode, 0, result.stderr)

  def test_socket_and_recording_continue_without_consumer(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source = path / 'input'
      packet = frame()
      source.write_bytes(packet * 2048)
      socket_path = path / 's'
      proc = subprocess.Popen([str(ROOT / 'flexray_logd'), '-f', str(source), '-l', '-o', directory,
                               '-p', str(socket_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      try:
        for _ in range(100):
          if socket_path.exists():
            break
          self.assertIsNone(proc.poll())
          time.sleep(0.01)
        with socket.socket(socket.AF_UNIX) as client:
          client.settimeout(2)
          client.connect(str(socket_path))
          client.sendall(b'\x80')
          time.sleep(0.02)
          client.sendall(struct.pack('>H', 15))
          output = b''
          while len(output) < 15:
            chunk = client.recv(15 - len(output))
            self.assertTrue(chunk)
            output += chunk
        expected = b'\x04' + (0x47F << 3).to_bytes(4, 'little') + b'\x02' + packet[7:]
        self.assertEqual(output, expected)
        time.sleep(0.4)  # Stop consuming until the independent socket queue fills.
        self.assertIsNone(proc.poll())
        proc.terminate()
        _, error = proc.communicate(timeout=4)
        self.assertEqual(proc.returncode, 0, error)
        recorded = b''.join(p.read_bytes() for p in sorted(path.glob('flexray-*.log')))
        self.assertGreater(len(recorded), 131072 * 2)
        self.assertEqual(recorded, (packet * ((len(recorded) + 15) // 16))[:len(recorded)])
        self.assertNotIn(b'socket dropped=0 ', error)
        self.assertFalse(socket_path.exists())
      finally:
        if proc.poll() is None:
          proc.kill()
          proc.communicate()

  def test_disk_failure_keeps_capture_and_socket_alive(self):
    def limit_file_size():
      signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
      resource.setrlimit(resource.RLIMIT_FSIZE, (1, 1))

    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source = path / 'input'
      packet = frame()
      source.write_bytes(packet * 2048)
      socket_path = path / 's'
      proc = subprocess.Popen([str(ROOT / 'flexray_logd'), '-f', str(source), '-l', '-o', directory,
                               '-p', str(socket_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              preexec_fn=limit_file_size)
      try:
        for _ in range(100):
          if socket_path.exists():
            break
          self.assertIsNone(proc.poll())
          time.sleep(0.01)
        time.sleep(0.1)  # The writer has now hit the one-byte file size limit.
        self.assertIsNone(proc.poll())
        with socket.socket(socket.AF_UNIX) as client:
          client.settimeout(2)
          client.connect(str(socket_path))
          client.sendall(b'\x80\x00\x0f')
          output = b''
          while len(output) < 15:
            block = client.recv(15 - len(output))
            self.assertTrue(block)
            output += block
        expected = b'\x04' + (0x47F << 3).to_bytes(4, 'little') + b'\x02' + packet[7:]
        self.assertEqual(output, expected)
        self.assertIsNone(proc.poll())
        proc.terminate()
        _, error = proc.communicate(timeout=4)
        self.assertIn(b'recording failed', error)
        self.assertIn(b'errno=', error)
        self.assertIn(b'capture continues', error)
        self.assertIn(b'disabled_recording_skipped=', error)
        self.assertNotEqual(proc.returncode, 0)  # Incomplete recording reported at shutdown only.
        self.assertEqual(sum(p.stat().st_size for p in path.glob('flexray-*.log')), 1)
      finally:
        if proc.poll() is None:
          proc.kill()
          proc.communicate()

  def test_crash_restart_and_active_socket_protection(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source, sock = path / 'input', path / 's'
      source.write_bytes(frame() * 2048)
      args = [str(ROOT / 'flexray_logd'), '-f', str(source), '-l', '-p', str(sock)]
      proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      try:
        for _ in range(100):
          if sock.exists():
            break
          self.assertIsNone(proc.poll())
          time.sleep(0.01)
        self.assertTrue(sock.exists())
        second = subprocess.run(args, capture_output=True, timeout=4)
        self.assertNotEqual(second.returncode, 0)
        self.assertIsNone(proc.poll())
        proc.kill()
        proc.wait(timeout=2)
        self.assertTrue(sock.exists())
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connected = False
        for _ in range(100):
          self.assertIsNone(proc.poll())
          with socket.socket(socket.AF_UNIX) as client:
            try:
              client.connect(str(sock))
              connected = True
              break
            except (ConnectionRefusedError, FileNotFoundError):
              time.sleep(0.01)
        self.assertTrue(connected)
        proc.terminate()
        self.assertEqual(proc.wait(timeout=4), 0)
        self.assertFalse(sock.exists())
      finally:
        if proc.poll() is None:
          proc.kill()
          proc.wait()

  def test_regular_file_at_socket_path_is_preserved(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source, sock = path / 'input', path / 's'
      source.write_bytes(frame())
      sock.write_bytes(b'keep this file')
      result = self.run_binary('flexray_logd', '-f', source, '-p', sock)
      self.assertNotEqual(result.returncode, 0)
      self.assertEqual(sock.read_bytes(), b'keep this file')

  def test_listener_without_lock_is_preserved(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory)
      source, sock = path / 'input', path / 's'
      source.write_bytes(frame())
      with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(sock))
        listener.listen(4)
        inode = sock.stat().st_ino
        result = self.run_binary('flexray_logd', '-f', source, '-p', sock)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sock.stat().st_ino, inode)
        with socket.socket(socket.AF_UNIX) as probe:
          probe.connect(str(sock))


if __name__ == '__main__':
  unittest.main()
