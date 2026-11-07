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
  bool initialized, spi_owned, loop;
};
int flexray_reader_open(struct flexray_reader *reader, const char *file, bool loop);
// File EOF returns zero; device errors return -1, including incomplete SPI transfers.
ssize_t flexray_reader_read(struct flexray_reader *reader, void *data, size_t capacity);
void flexray_reader_close(struct flexray_reader *reader);
#endif
