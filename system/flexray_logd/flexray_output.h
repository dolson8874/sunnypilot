#ifndef FLEXRAY_OUTPUT_H
#define FLEXRAY_OUTPUT_H
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include <pthread.h>

struct flexray_journal;
enum flexray_push_result { FLEXRAY_PUSH_ERROR = -1, FLEXRAY_PUSH_QUEUED = 0, FLEXRAY_PUSH_DROPPED = 1 };

struct byte_queue {
  pthread_mutex_t mutex;
  pthread_cond_t changed;
  unsigned char *data;
  size_t capacity, read, count;
  bool finished;
};
struct flexray_output {
  struct byte_queue queue;
  pthread_t thread;
  atomic_int error;
  atomic_bool stop;
  bool started, socket;
  int fd;
  int lock_fd;
  char *path;
  char segment_name[96];
  size_t rotate_bytes;
  time_t last_drop_report;
  atomic_uint_fast64_t dropped_bytes, written_bytes, dropped_batches, reset_bytes, failed_bytes, failed_batches;
  uint64_t input_bytes;  // Producer only; includes skipped raw input.
  struct flexray_journal *journal;
};
int flexray_output_start(struct flexray_output *out, const char *path, bool socket, size_t rotate_bytes);
// QUEUED means accepted into memory, not persisted. DROPPED is nonfatal queue overflow.
// ERROR denotes worker failure; capture decides policy. Raw losses are journaled asynchronously.
enum flexray_push_result flexray_output_push(struct flexray_output *out, const void *data, size_t size);
int flexray_output_close(struct flexray_output *out);
#endif
