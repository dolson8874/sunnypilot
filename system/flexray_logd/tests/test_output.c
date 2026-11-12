#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include "flexray_output.h"
#include "flexray_journal.h"

static atomic_bool fail_send, fail_write, pause_file, file_waiting, pause_journal, journal_waiting;
static size_t fd_count(void) {
  DIR *directory = opendir("/proc/self/fd");
  assert(directory);
  size_t count = 0;
  while (readdir(directory)) ++count;
  closedir(directory);
  return count;
}
ssize_t __real_send(int fd, const void *data, size_t size, int flags);
ssize_t __wrap_send(int fd, const void *data, size_t size, int flags) {
  if (atomic_load(&fail_send)) { errno = EPIPE; return -1; }
  // Exercise successful short writes too.
  if (size > 1) size = 1;
  return __real_send(fd, data, size, flags);
}
ssize_t __real_write(int fd, const void *data, size_t size);
ssize_t __wrap_write(int fd, const void *data, size_t size) {
  if (atomic_load(&pause_file) || atomic_load(&pause_journal)) {
    char link[64], target[512];
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
    ssize_t count = readlink(link, target, sizeof(target) - 1);
    if (count > 0) {
      target[count] = 0;
      if (strstr(target, "flexray-gaps-") && atomic_load(&pause_journal)) {
        atomic_store(&journal_waiting, true);
        while (atomic_load(&pause_journal)) usleep(1000);
      }
      if (strstr(target, "flexray-") && strstr(target, ".log")) {
        atomic_store(&file_waiting, true);
        while (atomic_load(&pause_file)) usleep(1000);
      }
    }
  }
  if (atomic_load(&fail_write)) { errno = ENOSPC; return -1; }
  return __real_write(fd, data, size);
}
static int request(const char *path) {
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  struct sockaddr_un address = {.sun_family = AF_UNIX};
  strcpy(address.sun_path, path);
  assert(connect(fd, (void *)&address, sizeof(address)) == 0);
  const unsigned char command[] = {0x80, 0, 100};
  assert(__real_write(fd, command, sizeof(command)) == sizeof(command));
  return fd;
}
int main(void) {
  size_t original_fds = fd_count();
  char directory[] = "/tmp/flexray-output-test-XXXXXX";
  assert(mkdtemp(directory));
  char path[128];snprintf(path, sizeof(path), "%s/socket", directory);
  struct flexray_output out;
  assert(flexray_output_start(&out, path, true, 0) == 0);
  struct flexray_output other;
  assert(flexray_output_start(&other, path, true, 0) < 0);
  unsigned char data[100], reply[100];memset(data, 0x55, sizeof(data));
  assert(flexray_output_push(&out, data, sizeof(data)) == 0);
  atomic_store(&fail_send, true);
  int fd = request(path);
  assert(read(fd, reply, sizeof(reply)) == 0);close(fd);
  pthread_mutex_lock(&out.queue.mutex);
  assert(out.queue.count == sizeof(data));
  pthread_mutex_unlock(&out.queue.mutex);
  atomic_store(&fail_send, false);
  fd = request(path);
  size_t received = 0;
  ssize_t n;
  while ((n = read(fd, reply + received, sizeof(reply) - received)) > 0) received += n;
  close(fd);
  assert(received == sizeof(data) && memcmp(reply, data, sizeof(data)) == 0);
  fd = socket(AF_UNIX, SOCK_STREAM, 0);
  struct sockaddr_un address = {.sun_family = AF_UNIX};
  strcpy(address.sun_path, path);
  assert(connect(fd, (void *)&address, sizeof(address)) == 0);
  unsigned char reset = 0x1f;
  assert(__real_write(fd, &reset, 1) == 1);
  received = 0;
  while (received < 2 && (n = read(fd, reply + received, 2 - received)) > 0) received += n;
  close(fd);
  assert(received == 2 && memcmp(reply, "OK", 2) == 0);
  assert(flexray_output_close(&out) == 0);
  assert(flexray_output_start(&out, directory, false, 1024) == 0);
  assert(flexray_output_push(&out, data, out.queue.capacity + 1) == FLEXRAY_PUSH_DROPPED);
  assert(atomic_load(&out.error) == 0);
  assert(out.dropped_bytes == out.queue.capacity + 1);
  assert(flexray_output_push(&out, data, sizeof(data)) == 0);
  assert(flexray_output_close(&out) == 0);
  assert(out.written_bytes == sizeof(data));
  // A stalled raw writer never waits inside the producer; full queues report DROPPED.
  assert(flexray_output_start(&out, directory, false, 16 * 1024 * 1024) == 0);
  unsigned char *large = malloc(out.queue.capacity);
  assert(large);
  memset(large, 0x55, out.queue.capacity);
  atomic_store(&pause_file, true);
  assert(flexray_output_push(&out, large, out.queue.capacity) == FLEXRAY_PUSH_QUEUED);
  for (int i = 0; !atomic_load(&file_waiting) && i < 1000; ++i) usleep(1000);
  assert(atomic_load(&file_waiting));
  assert(flexray_output_push(&out, data, sizeof(data)) == FLEXRAY_PUSH_DROPPED);
  assert(out.dropped_bytes == sizeof(data));
  atomic_store(&pause_file, false);
  free(large);
  assert(flexray_output_close(&out) == 0);

  // A stalled metadata writer also cannot block the raw producer. Its own
  // bounded queue explicitly counts missing gap records instead of hiding loss.
  atomic_store(&pause_journal, true);
  assert(flexray_output_start(&out, directory, false, 1024) == 0);
  for (int i = 0; !atomic_load(&journal_waiting) && i < 1000; ++i) usleep(1000);
  assert(atomic_load(&journal_waiting));
  for (int i = 0; i < 300; ++i)
    assert(flexray_output_push(&out, data, out.queue.capacity + 1) == FLEXRAY_PUSH_DROPPED);
  uint64_t metadata_lost = 0;
  int metadata_error = 0;
  flexray_journal_status(out.journal, &metadata_lost, &metadata_error);
  assert(metadata_lost >= 44 && metadata_error == 0);
  atomic_store(&pause_journal, false);
  assert(flexray_output_close(&out) == 0);
  assert(flexray_output_start(&out, directory, false, 1024) == 0);
  atomic_store(&fail_write, true);
  assert(flexray_output_push(&out, data, sizeof(data)) == 0);
  assert(flexray_output_close(&out) < 0);
  assert(errno == ENOSPC);
  atomic_store(&fail_write, false);
  for (int i = 0; i < 8; ++i) {
    assert(flexray_output_start(&out, path, true, 0) == 0);
    assert(flexray_output_close(&out) == 0);
  }
  assert(fd_count() == original_fds);
  // Remove only this test's generated files.
  DIR *dir = opendir(directory);
  assert(dir);
  bool saw_gap = false, saw_segment = false;
  struct dirent *entry;
  while ((entry = readdir(dir))) {
    if (entry->d_name[0] == '.') continue;
    char name[512];snprintf(name, sizeof(name), "%s/%s", directory, entry->d_name);
    if (strstr(entry->d_name, ".jsonl")) {
      FILE *metadata = fopen(name, "r");
      assert(metadata);
      char line[1024];
      while (fgets(line, sizeof(line), metadata)) {
        if (strstr(line, "\"reason\":\"queue_full\"")) {
          assert(strstr(line, "\"errno\":105"));  // ENOBUFS on Linux.
          assert(strstr(line, "\"monotonic_ns\":"));
          saw_gap = true;
        }
        if (strstr(line, "\"reason\":\"segment_start\"")) {
          assert(strstr(line, "\"segment\":\"flexray-"));
          saw_segment = true;
        }
      }
      fclose(metadata);
    }
    assert(unlink(name) == 0);
  }
  closedir(dir);
  assert(saw_gap && saw_segment);
  assert(rmdir(directory) == 0);
  puts("output: EPIPE retention, short sends, occupied socket, queue overflow recovery, disk failure OK");
  return 0;
}
