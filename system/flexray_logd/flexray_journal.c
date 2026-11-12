#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "flexray_journal.h"

#define JOURNAL_CAPACITY 256
struct gap_event {
  const char *reason;  // Static strings only.
  uint64_t offset, size, written, monotonic_ns, realtime_ns;
  int error;
  char segment[96];
};
struct flexray_journal {
  pthread_mutex_t mutex;
  pthread_cond_t changed;
  pthread_t thread;
  struct gap_event events[JOURNAL_CAPACITY];
  size_t read, count;
  uint64_t lost;
  int fd, error;
  bool finished;
};

static void *write_journal(void *arg) {
  struct flexray_journal *j = arg;
  for (;;) {
    pthread_mutex_lock(&j->mutex);
    while (!j->count && !j->finished) pthread_cond_wait(&j->changed, &j->mutex);
    if (!j->count && j->finished) { pthread_mutex_unlock(&j->mutex); break; }
    struct gap_event e = j->events[j->read];
    j->read = (j->read + 1) % JOURNAL_CAPACITY;
    j->count--;
    int error = j->error;
    pthread_mutex_unlock(&j->mutex);
    char line[512];
    int size = snprintf(line, sizeof(line),
      "{\"type\":\"raw_gap\",\"reason\":\"%s\",\"input_offset\":%llu,\"bytes\":%llu,"
      "\"segment\":\"%s\",\"written_bytes\":%llu,\"monotonic_ns\":%llu,\"realtime_ns\":%llu,\"errno\":%d}\n",
      e.reason, (unsigned long long)e.offset, (unsigned long long)e.size,
      e.segment, (unsigned long long)e.written, (unsigned long long)e.monotonic_ns,
      (unsigned long long)e.realtime_ns, e.error);
    if (size < 0 || (size_t)size >= sizeof(line)) error = EOVERFLOW;
    for (int pos = 0; !error && pos < size;) {
      ssize_t n = write(j->fd, line + pos, size - pos);
      if (n < 0 && errno == EINTR) continue;
      if (n <= 0) error = errno ? errno : EIO;
      else pos += n;
    }
    if (error) {
      pthread_mutex_lock(&j->mutex);
      bool first_error = !j->error;
      j->error = error;
      j->lost++;
      pthread_mutex_unlock(&j->mutex);
      if (first_error) fprintf(stderr, "flexray: gap metadata write failed errno=%d (%s)\n", error, strerror(error));
    }
  }
  pthread_mutex_lock(&j->mutex);
  uint64_t lost = j->lost;
  int error = j->error;
  pthread_mutex_unlock(&j->mutex);
  if (!error) {
    char summary[128];
    int size = snprintf(summary, sizeof(summary), "{\"type\":\"raw_metadata_summary\",\"lost_events\":%llu}\n",
                        (unsigned long long)lost);
    for (int pos = 0; pos < size;) {
      ssize_t n = write(j->fd, summary + pos, size - pos);
      if (n < 0 && errno == EINTR) continue;
      if (n <= 0) { error = errno ? errno : EIO; break; }
      pos += n;
    }
    if (error) {
      pthread_mutex_lock(&j->mutex);
      j->error = error;
      pthread_mutex_unlock(&j->mutex);
    }
  }
  if (fsync(j->fd)) {
    pthread_mutex_lock(&j->mutex);
    j->error = errno;
    pthread_mutex_unlock(&j->mutex);
  }
  return NULL;
}

struct flexray_journal *flexray_journal_open(const char *directory) {
  struct flexray_journal *j = calloc(1, sizeof(*j));
  if (!j) return NULL;
  size_t size = strlen(directory) + 64;
  char *path = malloc(size);
  if (!path) { free(j); return NULL; }
  snprintf(path, size, "%s/flexray-gaps-XXXXXX.jsonl", directory);
  j->fd = mkstemps(path, 6);
  if (j->fd < 0) { free(path); free(j); return NULL; }
  fprintf(stderr, "flexray: raw gap metadata %s\n", path);
  free(path);
  int error = pthread_mutex_init(&j->mutex, NULL);
  if (error) goto failed;
  error = pthread_cond_init(&j->changed, NULL);
  if (error) { pthread_mutex_destroy(&j->mutex); goto failed; }
  error = pthread_create(&j->thread, NULL, write_journal, j);
  if (error) { pthread_cond_destroy(&j->changed); pthread_mutex_destroy(&j->mutex); goto failed; }
  return j;
failed:
  close(j->fd);
  free(j);
  errno = error;
  return NULL;
}

static void enqueue(struct flexray_journal *j, const struct gap_event *e) {
  pthread_mutex_lock(&j->mutex);
  if (j->count == JOURNAL_CAPACITY) j->lost++;
  else {
    j->events[(j->read + j->count) % JOURNAL_CAPACITY] = *e;
    j->count++;
    pthread_cond_signal(&j->changed);
  }
  pthread_mutex_unlock(&j->mutex);
}

void flexray_journal_gap(struct flexray_journal *j, const char *reason, uint64_t offset,
                         uint64_t size, uint64_t written, int error) {
  if (!j) return;
  struct timespec mono, real;
  clock_gettime(CLOCK_MONOTONIC, &mono);
  clock_gettime(CLOCK_REALTIME, &real);
  struct gap_event e = {reason, offset, size, written,
    (uint64_t)mono.tv_sec * 1000000000 + mono.tv_nsec,
    (uint64_t)real.tv_sec * 1000000000 + real.tv_nsec, error, {0}};
  enqueue(j, &e);
}

void flexray_journal_segment(struct flexray_journal *j, const char *name, uint64_t written) {
  if (!j) return;
  struct timespec mono, real;
  clock_gettime(CLOCK_MONOTONIC, &mono);
  clock_gettime(CLOCK_REALTIME, &real);
  struct gap_event e = {.reason = "segment_start", .written = written,
    .monotonic_ns = (uint64_t)mono.tv_sec * 1000000000 + mono.tv_nsec,
    .realtime_ns = (uint64_t)real.tv_sec * 1000000000 + real.tv_nsec};
  snprintf(e.segment, sizeof(e.segment), "%s", name);
  enqueue(j, &e);
}

void flexray_journal_status(struct flexray_journal *j, uint64_t *lost, int *error) {
  if (!j) { *lost = 0; *error = ENODEV; return; }
  pthread_mutex_lock(&j->mutex);
  *lost = j->lost;
  *error = j->error;
  pthread_mutex_unlock(&j->mutex);
}

void flexray_journal_close(struct flexray_journal *j) {
  if (!j) return;
  pthread_mutex_lock(&j->mutex);
  j->finished = true;
  pthread_cond_signal(&j->changed);
  pthread_mutex_unlock(&j->mutex);
  pthread_join(j->thread, NULL);
  uint64_t lost; int error;
  flexray_journal_status(j, &lost, &error);
  if (lost || error) fprintf(stderr, "flexray: gap metadata incomplete lost_events=%llu errno=%d\n", (unsigned long long)lost, error);
  close(j->fd);
  pthread_cond_destroy(&j->changed);
  pthread_mutex_destroy(&j->mutex);
  free(j);
}
