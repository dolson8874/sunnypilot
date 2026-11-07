#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include "flexray_common.h"
#include "flexray_output.h"

static size_t peek(struct byte_queue *q, void *data, size_t capacity) {
  size_t size = q->count < capacity ? q->count : capacity;
  size_t first = q->capacity - q->read;
  if (first > size) first = size;
  memcpy(data, q->data + q->read, first);
  memcpy((unsigned char *)data + first, q->data, size - first);
  return size;
}

static void consume(struct byte_queue *q, size_t size) {
  q->read = (q->read + size) % q->capacity;
  q->count -= size;
}

static int open_segment(struct flexray_output *out) {
  struct timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  size_t capacity = strlen(out->path) + 96;
  char *name = malloc(capacity);
  if (!name) return -1;
  snprintf(name, capacity, "%s/flexray-%lld-%09ld-XXXXXX.log", out->path,
           (long long)ts.tv_sec, ts.tv_nsec);
  int fd = mkstemps(name, 4);  // Exclusive creation; existing files are never truncated.
  if (fd >= 0) fprintf(stderr, "flexray: recording %s\n", name);
  free(name);
  return fd;
}

static void *write_file(void *arg) {
  struct flexray_output *out = arg;
  struct byte_queue *q = &out->queue;
  unsigned char buffer[MAX_SEND_SIZE];
  size_t segment_bytes = 0;
  for (;;) {
    pthread_mutex_lock(&q->mutex);
    while (!q->count && !q->finished) pthread_cond_wait(&q->changed, &q->mutex);
    size_t n = peek(q, buffer, sizeof(buffer));
    bool done = q->finished;
    pthread_mutex_unlock(&q->mutex);
    if (!n && done) break;
    if (segment_bytes == out->rotate_bytes) {
      int sync_error = fsync(out->fd);
      int close_error = close(out->fd);
      out->fd = -1;
      if (sync_error || close_error) goto failed;
      out->fd = open_segment(out);
      if (out->fd < 0) goto failed;
      segment_bytes = 0;
    }
    size_t remaining = out->rotate_bytes - segment_bytes;
    if (n > remaining) n = remaining;
    size_t sent = 0;
    while (sent < n) {
      ssize_t count = write(out->fd, buffer + sent, n - sent);
      if (count < 0 && errno == EINTR) continue;
      if (count <= 0) goto failed;
      sent += count;
      pthread_mutex_lock(&q->mutex);
      consume(q, count);
      pthread_mutex_unlock(&q->mutex);
      segment_bytes += count;
      out->written_bytes += count;
    }
  }
  if (fsync(out->fd)) goto failed;
  return NULL;
failed: {
  int error = errno ? errno : EIO;
  atomic_store(&out->error, error);
  fprintf(stderr, "flexray: recording failed directory=%s errno=%d (%s)\n", out->path, error, strerror(error));
  return NULL;
}
}

static int receive_exact(int fd, void *buffer, size_t size, struct flexray_output *out) {
  unsigned char *data = buffer;
  while (size && !atomic_load(&out->stop)) {
    struct pollfd p = {.fd = fd, .events = POLLIN};
    int ready = poll(&p, 1, 100);
    if (ready < 0 && errno == EINTR) continue;
    if (ready <= 0) return -1;
    ssize_t n = recv(fd, data, size, 0);
    if (n <= 0) return -1;
    size -= n;
    data += n;
  }
  return size ? -1 : 0;
}

static ssize_t send_some(struct flexray_output *out, int fd, const void *data, size_t size) {
  while (!atomic_load(&out->stop)) {
    struct pollfd p = {.fd = fd, .events = POLLOUT};
    int ready = poll(&p, 1, 100);
    if (ready < 0 && errno == EINTR) continue;
    if (ready <= 0) return -1;
    ssize_t n = send(fd, data, size, MSG_NOSIGNAL);
    if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    return n;
  }
  return -1;
}

static void serve_client(struct flexray_output *out, int client) {
  unsigned char command[3], buffer[MAX_SEND_SIZE];
  struct byte_queue *q = &out->queue;
  if (receive_exact(client, command, 1, out)) return;
  if (command[0] == 0x1f) {
    pthread_mutex_lock(&q->mutex);
    out->dropped_bytes += q->count;
    consume(q, q->count);
    pthread_mutex_unlock(&q->mutex);
    size_t sent = 0;
    while (sent < 2) {
      ssize_t n = send_some(out, client, &"OK"[sent], 2 - sent);
      if (n <= 0) break;
      sent += n;
    }
    return;
  }
  if (command[0] != 0x80 || receive_exact(client, command + 1, 2, out)) return;
  size_t requested = ((size_t)command[1] << 8) | command[2];
  if (requested > sizeof(buffer)) requested = sizeof(buffer);
  pthread_mutex_lock(&q->mutex);
  size_t size = peek(q, buffer, requested);
  pthread_mutex_unlock(&q->mutex);
  size_t sent = 0;
  while (sent < size && !atomic_load(&out->stop)) {
    ssize_t n = send_some(out, client, buffer + sent, size - sent);
    if (n <= 0) break;
    // Only the server consumes this queue; producers never overwrite unread bytes.
    pthread_mutex_lock(&q->mutex);
    consume(q, n);
    pthread_mutex_unlock(&q->mutex);
    sent += n;
  }
}

static void *serve_socket(void *arg) {
  struct flexray_output *out = arg;
  while (!atomic_load(&out->stop)) {
    struct pollfd p = {.fd = out->fd, .events = POLLIN};
    int ready = poll(&p, 1, 100);
    if (ready < 0 && errno == EINTR) continue;
    if (ready < 0) { atomic_store(&out->error, errno); break; }
    if (!ready) continue;
    int client = accept4(out->fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (client < 0) {
      if (errno == EINTR || errno == EAGAIN) continue;
      atomic_store(&out->error, errno);
      break;
    }
    serve_client(out, client);
    close(client);
  }
  return NULL;
}

static int lock_socket_path(struct flexray_output *out, const struct sockaddr_un *address) {
  size_t size = strlen(out->path) + 6;
  char *name = malloc(size);
  if (!name) return -1;
  snprintf(name, size, "%s.lock", out->path);
  out->lock_fd = open(name, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
  free(name);
  if (out->lock_fd < 0) return -1;
  struct stat info;
  if (fstat(out->lock_fd, &info)) return -1;
  if (!S_ISREG(info.st_mode) || info.st_uid != geteuid()) { errno = EACCES; return -1; }
  // Keep the lock file: unlinking it would allow two processes to lock different inodes.
  if (flock(out->lock_fd, LOCK_EX | LOCK_NB)) { errno = EADDRINUSE; return -1; }
  if (lstat(out->path, &info)) return errno == ENOENT ? 0 : -1;
  if (!S_ISSOCK(info.st_mode) || info.st_uid != geteuid()) { errno = EADDRINUSE; return -1; }
  // Also protect listeners from older versions which do not hold this lock.
  int probe = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
  if (probe < 0) return -1;
  int connected = connect(probe, (const struct sockaddr *)address, sizeof(*address));
  int error = errno;
  close(probe);
  if (connected == 0 || error != ECONNREFUSED) { errno = EADDRINUSE; return -1; }
  return unlink(out->path);
}

int flexray_output_start(struct flexray_output *out, const char *path, bool socket_output, size_t rotate_bytes) {
  memset(out, 0, sizeof(*out));
  atomic_init(&out->error, 0);
  atomic_init(&out->stop, false);
  out->fd = -1;
  out->lock_fd = -1;
  out->socket = socket_output;
  out->rotate_bytes = rotate_bytes;
  out->path = strdup(path);
  struct byte_queue *q = &out->queue;
  q->capacity = socket_output ? SPI_BUFFER_SIZE : 8 * 1024 * 1024;
  q->data = malloc(q->capacity);
  if (!q->data || !out->path) { errno = ENOMEM; goto failed; }
  if (!socket_output && !rotate_bytes) { errno = EINVAL; goto failed; }
  int error = pthread_mutex_init(&q->mutex, NULL);
  if (error) { errno = error; goto failed; }
  error = pthread_cond_init(&q->changed, NULL);
  if (error) { pthread_mutex_destroy(&q->mutex); errno = error; goto failed; }
  if (socket_output) {
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    if (strlen(path) >= sizeof(address.sun_path)) { errno = ENAMETOOLONG; goto queue_failed; }
    strcpy(address.sun_path, path);
    if (lock_socket_path(out, &address)) goto queue_failed;
    out->fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (out->fd < 0) goto queue_failed;
    // The path is either absent or an owned stale socket, with concurrent starts locked out.
    if (bind(out->fd, (struct sockaddr *)&address, sizeof(address))) goto queue_failed;
    if (listen(out->fd, 4)) { unlink(path); goto queue_failed; }
  } else {
    out->fd = open_segment(out);
    if (out->fd < 0) goto queue_failed;
  }
  error = pthread_create(&out->thread, NULL, socket_output ? serve_socket : write_file, out);
  if (error) { if (socket_output) unlink(path); errno = error; goto queue_failed; }
  out->started = true;
  return 0;
queue_failed:
  error = errno;
  if (out->fd >= 0) close(out->fd);
  if (out->lock_fd >= 0) close(out->lock_fd);
  pthread_cond_destroy(&q->changed);
  pthread_mutex_destroy(&q->mutex);
  errno = error;
failed:
  free(q->data);
  free(out->path);
  return -1;
}

int flexray_output_push(struct flexray_output *out, const void *data, size_t size) {
  if (atomic_load(&out->error)) return -1;
  struct byte_queue *q = &out->queue;
  pthread_mutex_lock(&q->mutex);
  if (size > q->capacity - q->count) {
    out->dropped_bytes += size;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    if (out->last_drop_report != now.tv_sec) {
      fprintf(stderr, "flexray: %s queue full: dropped_batch=%zu dropped_total=%llu capacity=%zu\n",
              out->socket ? "socket" : "recording", size,
              (unsigned long long)out->dropped_bytes, q->capacity);
      out->last_drop_report = now.tv_sec;
    }
    pthread_mutex_unlock(&q->mutex);
    return 0;
  }
  size_t write_pos = (q->read + q->count) % q->capacity;
  size_t first = q->capacity - write_pos;
  if (first > size) first = size;
  memcpy(q->data + write_pos, data, first);
  memcpy(q->data, (const unsigned char *)data + first, size - first);
  q->count += size;
  pthread_cond_signal(&q->changed);
  pthread_mutex_unlock(&q->mutex);
  return 0;
}

int flexray_output_close(struct flexray_output *out) {
  if (!out->started) return 0;
  atomic_store(&out->stop, true);
  pthread_mutex_lock(&out->queue.mutex);
  out->queue.finished = true;
  pthread_cond_signal(&out->queue.changed);
  pthread_mutex_unlock(&out->queue.mutex);
  pthread_join(out->thread, NULL);
  int error = atomic_load(&out->error);
  if (close(out->fd) && !error) error = errno;
  if (out->socket) {
    unlink(out->path);
    close(out->lock_fd);
    fprintf(stderr, "flexray: socket dropped=%llu bytes, unsent=%zu bytes\n",
            (unsigned long long)out->dropped_bytes, out->queue.count);
  } else fprintf(stderr, "flexray: recorded=%llu bytes, queue_dropped=%llu bytes, unwritten=%zu bytes\n",
                 (unsigned long long)out->written_bytes, (unsigned long long)out->dropped_bytes, out->queue.count);
  pthread_cond_destroy(&out->queue.changed);
  pthread_mutex_destroy(&out->queue.mutex);
  free(out->queue.data);
  free(out->path);
  out->started = false;
  if (error) { errno = error; return -1; }
  return 0;
}
