#include <errno.h>
#include <string.h>
#include "flexray_reader.h"

void flexray_reader_close(struct flexray_reader *r) {
  if (r->file) fclose(r->file);
  if (r->spi_owned) {
    ftdispi_close(&r->spi, 1);
  } else if (r->initialized) {
    ftdi_usb_close(&r->usb);
    ftdi_deinit(&r->usb);
  }
  r->file = NULL;
  r->initialized = r->spi_owned = false;
}

int flexray_reader_open(struct flexray_reader *r, const char *file, bool loop) {
  memset(r, 0, sizeof(*r));
  r->loop = loop;
  if (file) {
    r->type = FT_FILE_TEST;
    r->file = fopen(file, "rb");
    return r->file ? 0 : -1;
  }
  const int products[] = {0x6010, 0x6011};
  for (size_t i = 0; i < 2; ++i) {
    if (ftdi_init(&r->usb) < 0) return -1;
    r->initialized = true;
    if (ftdi_set_interface(&r->usb, INTERFACE_B) == 0 &&
        ftdi_usb_open(&r->usb, 0x0403, products[i]) == 0) {
      r->usb.usb_read_timeout = 100;
      r->usb.usb_write_timeout = 1000;
      r->type = i == 0 ? FT_FASTSERIAL : FT_SPI;
      if (i == 0) {
        r->usb.usb_read_timeout = 100;
        if (ftdi_set_bitmode(&r->usb, 0xff, BITMODE_RESET) == 0 &&
            ftdi_set_latency_timer(&r->usb, 2) == 0) return 0;
      } else {
        // ftdispi_open transfers ownership by copying the FTDI context.
        r->spi_owned = true;
        if (ftdispi_open(&r->spi, &r->usb, INTERFACE_B) == 0 &&
            ftdispi_setmode(&r->spi, 1, 0, 0, 0, 0, 0) == 0 &&
            ftdispi_setclock(&r->spi, 7500000) == 0 &&
            ftdispi_setloopback(&r->spi, 0) == 0) {
          r->spi.fc.usb_read_timeout = 100;
          return 0;
        }
      }
      fprintf(stderr, "flexray: device setup failed: %s\n",
              ftdi_get_error_string(r->spi_owned ? &r->spi.fc : &r->usb));
      flexray_reader_close(r);
      errno = EIO;
      return -1;
    }
    fprintf(stderr, "flexray: open %04x: %s\n", products[i], ftdi_get_error_string(&r->usb));
    flexray_reader_close(r);
  }
  errno = ENODEV;
  return -1;
}

ssize_t flexray_reader_read(struct flexray_reader *r, void *data, size_t capacity) {
  if (r->type == FT_FILE_TEST) {
    size_t n = fread(data, 1, capacity, r->file);
    if (n) return n;
    if (ferror(r->file)) return -1;
    if (!r->loop) return 0;
    rewind(r->file);
    n = fread(data, 1, capacity, r->file);
    if (n) return n;
    errno = EINVAL;  // Empty looping input must not spin forever.
    return -1;
  }
  if (r->type == FT_SPI) {
    if (capacity > 65535) capacity = 65535;
    if (ftdispi_read_stream(&r->spi, data, capacity, 0) == 0) return capacity;
  } else {
    int n = ftdi_read_data(&r->usb, data, capacity);
    if (n >= 0) return n;
    // A timeout may have consumed partial USB data; fail visibly rather than silently retrying.
    fprintf(stderr, "flexray: read: %s\n", ftdi_get_error_string(&r->usb));
  }
  errno = EIO;
  return -1;
}
