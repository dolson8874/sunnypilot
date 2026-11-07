#include <assert.h>
#include <stdio.h>
#include <time.h>
#include "ftdispi.h"

static int short_write;
int __wrap_ftdi_write_data(struct ftdi_context *ctx, const unsigned char *data, int size) {
  (void)ctx; (void)data;
  return short_write ? size - 1 : size;
}
int __wrap_ftdi_read_data(struct ftdi_context *ctx, unsigned char *data, int size) {
  (void)ctx; (void)data; (void)size;
  return 0;
}
int main(void) {
  uint8_t memory[32], output[16];
  struct ftdispi_context context = {0};
  context.mem = memory;
  struct timespec start, end;
  clock_gettime(CLOCK_MONOTONIC, &start);
  assert(ftdispi_read_stream(&context, output, sizeof(output), 0) == FTDISPI_ERROR_TO);
  clock_gettime(CLOCK_MONOTONIC, &end);
  double elapsed = end.tv_sec - start.tv_sec + (end.tv_nsec - start.tv_nsec) / 1e9;
  assert(elapsed >= 0.9 && elapsed < 3.0);
  short_write = 1;
  assert(ftdispi_read_stream(&context, output, sizeof(output), 0) == FTDISPI_ERROR_LIB);
  puts("SPI: zero-read timeout and short command write OK");
  return 0;
}
