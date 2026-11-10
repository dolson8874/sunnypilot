#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <libusb.h>
#include "flexray_reader.h"

void flexray_reader_finish(struct flexray_reader *r) {
  if (r->type == FT_SPI) ftdispi_stream_finish(&r->spi);
}
bool flexray_reader_pending(const struct flexray_reader *r) {
  return r->type == FT_SPI && r->spi.stream_pending != 0;
}
static void report_spi(struct flexray_reader *r, bool force) {
  struct timespec now;
  clock_gettime(CLOCK_MONOTONIC, &now);
  if (!r->report_at.tv_sec && !r->report_at.tv_nsec) {
    r->report_at = now;
    r->report_bytes = r->spi.stream_usb_payload_bytes;
    if (!force) return;
  }
  double dt = now.tv_sec - r->report_at.tv_sec + (now.tv_nsec - r->report_at.tv_nsec) / 1e9;
  if (dt >= 1 || force) {
    fprintf(stderr, "SPI: configured_clock=%uHz usb_payload_bytes=%llu usb_payload_Bps=%.1f interval_s=%.3f "
      "last_read_monotonic=%.9f delivered=%llu pending=%u buffered=%u pending_peak=%u commands=%llu usb_calls=%llu "
      "empty=%llu timeout=%llu interrupted=%llu max_gap_ms=%.3f usb_read_ms=%.3f call_total_ms=%.3f error=%d\n",
      r->spi.actual_clock_hz, (unsigned long long)r->spi.stream_usb_payload_bytes,
      dt > 0 ? (r->spi.stream_usb_payload_bytes - r->report_bytes) / dt : 0, dt,
      r->last_read_at.tv_sec + r->last_read_at.tv_nsec / 1e9, (unsigned long long)r->spi.stream_bytes, r->spi.stream_pending, r->spi.fc.readbuffer_remaining,
      r->spi.stream_pending_peak, (unsigned long long)r->spi.stream_commands,
      (unsigned long long)r->spi.stream_usb_calls, (unsigned long long)r->spi.stream_idle_reads,
      (unsigned long long)r->spi.stream_timeouts, (unsigned long long)r->spi.stream_interrupts,
      r->spi.stream_gap_ns / 1e6, r->spi.stream_usb_read_ns / 1e6, r->spi.stream_read_ns / 1e6, r->spi.stream_error);
    r->report_at = now;
    r->report_bytes = r->spi.stream_usb_payload_bytes;
  }
}

int flexray_reader_close(struct flexray_reader *r) {
  int result = 0;
  if (r->file) fclose(r->file);
  if (r->spi_owned) {
    report_spi(r, true);
    if (ftdispi_close(&r->spi, 1) != 0) { errno = EIO; result = -1; }
  } else if (r->initialized) {
    ftdi_usb_close(&r->usb);
    ftdi_deinit(&r->usb);
  }
  r->file = NULL;
  r->initialized = r->spi_owned = false;
  return result;
}

int flexray_reader_open(struct flexray_reader *r, const char *file, bool loop) {
  memset(r, 0, sizeof(*r));
  r->loop = loop;
  if (file) {
    r->type = FT_FILE_TEST;
    r->file = fopen(file, "rb");
    return r->file ? 0 : -1;
  }
  // 6010 Fast Serial is legacy and must be selected explicitly. Never silently
  // claim a different adapter when the expected 6011 is missing or busy.
  const char *product_setting = getenv("FLEXRAY_FTDI_PRODUCT");
  const char *serial_setting = getenv("FLEXRAY_FTDI_SERIAL");
  int product = 0x6011;
  if (product_setting && *product_setting) {
    if (!strcmp(product_setting, "6010")) product = 0x6010;
    else if (strcmp(product_setting, "6011")) { errno = EINVAL; return -1; }
  }
  const char *stage = "context_init";
  fprintf(stderr, "native stage=context_init starting pid=%ld\n", (long)getpid());
  errno = 0;
  int rc = ftdi_init(&r->usb);
  if (rc < 0) {
    int saved = errno;
    fprintf(stderr, "native stage=context_init failed rc=%d errno=%d strerror=%s libftdi=%s\n",
            rc, saved, strerror(saved), ftdi_get_error_string(&r->usb));
    ftdi_deinit(&r->usb);
    errno = saved ? saved : EIO;
    return -1;
  }
  r->initialized = true;
  struct ftdi_device_list *devices = NULL;
  struct libusb_device *selected = NULL;
  unsigned matches = 0;
  char serial[256] = "unknown";
  stage = "probe";
  errno = 0;
  rc = ftdi_usb_find_all(&r->usb, &devices, 0x0403, product);
  fprintf(stderr, "native stage=probe rc=%d vid=0403 pid=%04x serial_filter=%s\n",
          rc, product, serial_setting ? serial_setting : "unset");
  if (rc < 0) goto failed;
  for (struct ftdi_device_list *device = devices; device; device = device->next) {
    char candidate_serial[256] = {0};
    int strings_result = ftdi_usb_get_strings(&r->usb, device->dev, NULL, 0, NULL, 0, candidate_serial, sizeof(candidate_serial));
    fprintf(stderr, "native stage=probe_serial rc=%d serial=%s\n", strings_result, candidate_serial);
    if (serial_setting && *serial_setting && (strings_result < 0 || strcmp(serial_setting, candidate_serial))) continue;
    selected = device->dev;
    snprintf(serial, sizeof(serial), "%s", strings_result < 0 ? "unavailable" : candidate_serial);
    ++matches;
  }
  if (matches != 1) {
    errno = matches ? EBUSY : ENODEV;
    fprintf(stderr, "native stage=selection matches=%u; select one adapter with FLEXRAY_FTDI_SERIAL\n", matches);
    rc = -1; goto failed;
  }
  uint8_t ports[8];
  int port_count = libusb_get_port_numbers(selected, ports, sizeof(ports));
  fprintf(stderr, "native device vid=0403 pid=%04x serial=%s usb_bus=%u usb_address=%u port_path=",
          product, serial, libusb_get_bus_number(selected), libusb_get_device_address(selected));
  for (int port = 0; port < port_count; ++port) fprintf(stderr, "%s%u", port ? "." : "", ports[port]);
  fprintf(stderr, " interface=B legacy_fastserial=%d\n", product == 0x6010);
#define READER_STEP(NAME, CALL) do { \
  stage = NAME; errno = 0; \
  fprintf(stderr, "native stage=%s starting pid=%ld\n", stage, (long)getpid()); \
  rc = (CALL); \
  if (rc != 0) goto failed; \
  fprintf(stderr, "native stage=%s success rc=0\n", stage); \
} while (0)
  READER_STEP("interface_B", ftdi_set_interface(&r->usb, INTERFACE_B));
  READER_STEP("usb_open_claim", ftdi_usb_open_dev(&r->usb, selected));
  ftdi_list_free(&devices);
  fprintf(stderr, "native device type=%d interface=%d index=%d\n", r->usb.type, r->usb.interface, r->usb.index);
  r->usb.usb_read_timeout = 100;
  r->usb.usb_write_timeout = 1000;
  r->type = product == 0x6010 ? FT_FASTSERIAL : FT_SPI;
  if (r->type == FT_FASTSERIAL) {
    READER_STEP("fastserial_bitmode", ftdi_set_bitmode(&r->usb, 0xff, BITMODE_RESET));
    READER_STEP("fastserial_latency", ftdi_set_latency_timer(&r->usb, 2));
  } else {
    if (r->usb.type != TYPE_4232H) { stage = "expected_FT4232H"; rc = -1; errno = ENODEV; goto failed; }
    // open copies context ownership, including partial allocation failures.
    r->spi_owned = true;
    READER_STEP("mpsse_open", ftdispi_open(&r->spi, &r->usb, INTERFACE_B));
    READER_STEP("gpio_setmode", ftdispi_setmode(&r->spi, 1, 0, 0, 0, 0, 0));
    READER_STEP("setclock_7500000", ftdispi_setclock(&r->spi, 7500000));
    READER_STEP("loopback_off", ftdispi_setloopback(&r->spi, 0));
    r->spi.fc.usb_read_timeout = 100;
    fprintf(stderr, "native configured_clock=%u interface=B mode=0\n", r->spi.actual_clock_hz);
  }
#undef READER_STEP
  fprintf(stderr, "native stage=first_bulk_read waiting pid=%ld\n", (long)getpid());
  return 0;
failed: {
    int saved_errno = errno;
    struct ftdi_context *context = r->spi_owned ? &r->spi.fc : &r->usb;
    // Snapshot before close/deinit invalidates the library error/context.
    fprintf(stderr, "native stage=%s failed pid=%ld rc=%d errno=%d strerror=%s libftdi=%s\n",
            stage, (long)getpid(), rc, saved_errno, strerror(saved_errno), ftdi_get_error_string(context));
    if (devices) ftdi_list_free(&devices);
    flexray_reader_close(r);
    errno = saved_errno ? saved_errno : EIO;
    return -1;
  }
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
    int n = ftdispi_stream_read_some(&r->spi, data, capacity, 0);
    if (n > 0) clock_gettime(CLOCK_MONOTONIC, &r->last_read_at);
    report_spi(r, false);
    if (n > 0 && !r->received_data) {
      r->received_data = true;
      fprintf(stderr, "native stage=first_bulk_read success bytes=%d last_read_monotonic=%.9f\n",
              n, r->last_read_at.tv_sec + r->last_read_at.tv_nsec / 1e9);
    }
    if (n >= 0) return n;
    int saved = errno;
    fprintf(stderr, "native stage=bulk_read failed rc=%d pending=%u errno=%d strerror=%s libftdi=%s\n",
            n, r->spi.stream_pending, saved, strerror(saved), ftdi_get_error_string(&r->spi.fc));
  } else {
    int n = ftdi_read_data(&r->usb, data, capacity);
    if (n >= 0) return n;
    // A timeout may have consumed partial USB data; fail visibly rather than silently retrying.
    fprintf(stderr, "flexray: read: %s\n", ftdi_get_error_string(&r->usb));
  }
  errno = EIO;
  return -1;
}
