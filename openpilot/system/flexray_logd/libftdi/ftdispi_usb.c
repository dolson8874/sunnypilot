#include <libusb.h>
#include "ftdispi.h"

int ftdispi_read_usb_partial(struct ftdi_context *fc, unsigned char *data,
                           int capacity, int *usb_error) {
  if (!fc || !data || capacity <= 0 || !usb_error) return -1;
  *usb_error = 0;
  if (fc->readbuffer_remaining) {
    if (!fc->readbuffer || fc->readbuffer_offset > fc->readbuffer_chunksize ||
        fc->readbuffer_remaining > fc->readbuffer_chunksize - fc->readbuffer_offset) return -1;
    unsigned n = fc->readbuffer_remaining;
    if (n > (unsigned)capacity) n = capacity;
    memcpy(data, fc->readbuffer + fc->readbuffer_offset, n);
    fc->readbuffer_offset += n; fc->readbuffer_remaining -= n;
    return n;
  }
  if (!fc->usb_dev || !fc->readbuffer || !fc->readbuffer_chunksize || fc->max_packet_size < 2) {
    *usb_error = LIBUSB_ERROR_NO_DEVICE; return 0;
  }
  int raw = 0;
  *usb_error = libusb_bulk_transfer(fc->usb_dev, fc->out_ep, fc->readbuffer,
                                  fc->readbuffer_chunksize, &raw, fc->usb_read_timeout);
  if (raw < 0 || (unsigned)raw > fc->readbuffer_chunksize) return -1;
  unsigned source = 0, payload = 0;
  while (source < (unsigned)raw) {
    unsigned packet = raw - source;
    if (packet > fc->max_packet_size) packet = fc->max_packet_size;
    if (packet > 2) {
      memmove(fc->readbuffer + payload, fc->readbuffer + source + 2, packet - 2);
      payload += packet - 2;
    }
    source += packet;
  }
  unsigned n = payload;
  if (n > (unsigned)capacity) n = capacity;
  memcpy(data, fc->readbuffer, n);
  fc->readbuffer_offset = n; fc->readbuffer_remaining = payload - n;
  return n;
}
