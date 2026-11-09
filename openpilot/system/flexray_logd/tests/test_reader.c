#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "flexray_reader.h"

static int open_result = -5;
static int read_result;
int __wrap_ftdi_usb_open(struct ftdi_context *context, int vendor, int product) {
  (void)context; (void)vendor; (void)product;
  return open_result;
}
int __wrap_ftdi_set_bitmode(struct ftdi_context *context, unsigned char mask, unsigned char mode) {
  (void)context; (void)mask; (void)mode;
  return 0;
}
int __wrap_ftdi_set_latency_timer(struct ftdi_context *context, unsigned char latency) {
  (void)context; (void)latency;
  return 0;
}
int __wrap_ftdi_read_data(struct ftdi_context *context, unsigned char *data, int capacity) {
  (void)context;
  int n = read_result > capacity ? capacity : read_result;
  if (n > 0) memset(data, 0x55, n);
  return n;
}
int __wrap_ftdispi_stream_read_some(struct ftdispi_context *context, void *data, uint16_t count, uint8_t gpo) {
  (void)context; (void)data; (void)count; (void)gpo;
  return FTDISPI_ERROR_TO;
}
int main(void) {
  struct flexray_reader reader;
  assert(flexray_reader_open(&reader, NULL, false) < 0);
  assert(!reader.initialized);  // Claim failure (-5) must not be accepted as an open device.
  open_result = 0;
  assert(flexray_reader_open(&reader, NULL, false) == 0);
  assert(reader.type == FT_FASTSERIAL);
  unsigned char data[32];
  assert(flexray_reader_read(&reader, data, sizeof(data)) == 0);
  read_result = 4;
  assert(flexray_reader_read(&reader, data, sizeof(data)) == 4);
  for (int i = 0; i < 4; ++i) assert(data[i] == 0x55);
  read_result = -1;
  assert(flexray_reader_read(&reader, data, sizeof(data)) < 0);
  assert(errno == EIO);
  flexray_reader_close(&reader);
  reader.type = FT_SPI;
  assert(flexray_reader_read(&reader, data, sizeof(data)) < 0);
  assert(errno == EIO);
  puts("reader: claim failure, idle zero read, data resumption and input errors OK");
  return 0;
}
