#ifndef FLEXRAY_READER_H
#define FLEXRAY_READER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/types.h>
#include "ftdispi.h"

typedef enum { FT_FILE_TEST, FT_FASTSERIAL, FT_SPI } FTDI_DEV_TYPE;
struct flexray_reader {
  FTDI_DEV_TYPE type;
  FILE *file;
  struct ftdi_context usb;
  struct ftdispi_context spi;
  bool initialized, spi_owned, loop, received_data;
  struct timespec report_at, last_read_at;
  uint64_t report_bytes;
};
int flexray_reader_open(struct flexray_reader *reader, const char *file, bool loop);
// Zero means file EOF or transient empty USB data; partial SPI bytes are returned.
ssize_t flexray_reader_read(struct flexray_reader *reader, void *data, size_t capacity);
int flexray_reader_close(struct flexray_reader *reader);
void flexray_reader_finish(struct flexray_reader *reader);
bool flexray_reader_pending(const struct flexray_reader *reader);
#endif
