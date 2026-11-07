#ifndef FLEXRAY_OUTPUT_H
#define FLEXRAY_OUTPUT_H
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include <pthread.h>

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
  size_t rotate_bytes;
  time_t last_drop_report;
  uint64_t dropped_bytes, written_bytes;
};
int flexray_output_start(struct flexray_output *out, const char *path, bool socket, size_t rotate_bytes);
// Full queues drop whole new batches and count/report the loss without stopping capture.
int flexray_output_push(struct flexray_output *out, const void *data, size_t size);
int flexray_output_close(struct flexray_output *out);
#endif
