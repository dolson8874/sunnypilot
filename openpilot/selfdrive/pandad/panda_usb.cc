#include "selfdrive/pandad/panda_comms.h"

#include <libusb-1.0/libusb.h>

#include <memory>
#include <stdexcept>

#include "common/swaglog.h"

namespace {
constexpr unsigned control_timeout_ms = 100;
constexpr unsigned bulk_timeout_ms = 5;

bool is_internal_dos_port(libusb_device *device) {
  libusb_device_descriptor desc = {};
  uint8_t ports[2] = {};
  return libusb_get_device_descriptor(device, &desc) == 0 &&
         desc.idVendor == 0x3801 && desc.idProduct == 0xddcc &&
         libusb_get_bus_number(device) == 1 &&
         libusb_get_port_numbers(device, ports, sizeof(ports)) == 2 &&
         ports[0] == 1 && ports[1] == 2;
}

std::string read_serial(libusb_device *device, libusb_device_handle *handle) {
  libusb_device_descriptor desc = {};
  unsigned char bytes[26] = {};
  if (libusb_get_device_descriptor(device, &desc) != 0) return {};
  const int length = libusb_get_string_descriptor_ascii(handle, desc.iSerialNumber, bytes, sizeof(bytes));
  return length == 24 ? std::string(reinterpret_cast<const char *>(bytes), length) : std::string{};
}
}  // namespace

PandaUsbHandle::PandaUsbHandle(const std::string &serial) {
  if (libusb_init(&ctx) != 0) throw std::runtime_error("Unable to initialize Panda USB");

  libusb_device **devices = nullptr;
  const ssize_t count = libusb_get_device_list(ctx, &devices);
  for (ssize_t i = 0; i < count; ++i) {
    if (!is_internal_dos_port(devices[i]) || libusb_open(devices[i], &device) != 0) continue;
    hw_serial = read_serial(devices[i], device);
    if (!hw_serial.empty() && (serial.empty() || serial == hw_serial)) break;
    libusb_close(device);
    device = nullptr;
  }
  if (devices) libusb_free_device_list(devices, 1);

  if (device && libusb_set_auto_detach_kernel_driver(device, 1) == 0 &&
      libusb_claim_interface(device, 0) == 0) {
    claimed = true;
    return;
  }
  cleanup();
  throw std::runtime_error("Unable to claim the internal C3 Panda USB interface");
}

PandaUsbHandle::~PandaUsbHandle() {
  cleanup();
}

void PandaUsbHandle::cleanup() {
  if (device) {
    if (claimed) libusb_release_interface(device, 0);
    libusb_close(device);
  }
  if (ctx) libusb_exit(ctx);
}

std::vector<std::string> PandaUsbHandle::list() {
  libusb_context *context = nullptr;
  if (libusb_init(&context) != 0) return {};
  std::unique_ptr<libusb_context, decltype(&libusb_exit)> guard(context, libusb_exit);

  std::vector<std::string> serials;
  libusb_device **devices = nullptr;
  const ssize_t count = libusb_get_device_list(context, &devices);
  for (ssize_t i = 0; i < count; ++i) {
    libusb_device_handle *candidate = nullptr;
    if (!is_internal_dos_port(devices[i]) || libusb_open(devices[i], &candidate) != 0) continue;
    const auto serial = read_serial(devices[i], candidate);
    libusb_close(candidate);
    if (!serial.empty()) serials.push_back(serial);
  }
  if (devices) libusb_free_device_list(devices, 1);
  return serials;
}

void PandaUsbHandle::mark_failed(const char *transfer, uint8_t code, int requested, int transferred, unsigned timeout_ms, int error) {
  LOGE_100("Internal Panda USB %s failed: code=0x%02x requested=%d transferred=%d timeout=%ums error=%s",
           transfer, code, requested, transferred, timeout_ms, libusb_error_name(error));
  comms_healthy = false;
  connected = false;
}

int PandaUsbHandle::control_write(uint8_t request, uint16_t param1, uint16_t param2, unsigned int timeout) {
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  constexpr uint8_t request_type = LIBUSB_ENDPOINT_OUT | LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_DEVICE;
  const unsigned timeout_ms = timeout ? timeout : control_timeout_ms;
  const int result = libusb_control_transfer(device, request_type, request, param1, param2, nullptr, 0, timeout_ms);
  if (result < 0) mark_failed("control OUT", request, 0, -1, timeout_ms, result);
  return result;
}

int PandaUsbHandle::control_read(uint8_t request, uint16_t param1, uint16_t param2, unsigned char *data, uint16_t length, unsigned int timeout) {
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  constexpr uint8_t request_type = LIBUSB_ENDPOINT_IN | LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_DEVICE;
  const unsigned timeout_ms = timeout ? timeout : control_timeout_ms;
  const int result = libusb_control_transfer(device, request_type, request, param1, param2, data, length, timeout_ms);
  if (result < 0) mark_failed("control IN", request, length, -1, timeout_ms, result);
  return result;
}

int PandaUsbHandle::bulk_write(unsigned char endpoint, unsigned char *data, int length, unsigned int timeout) {
  if (!connected) return 0;
  int transferred = 0;
  const unsigned timeout_ms = timeout ? timeout : bulk_timeout_ms;
  const int result = libusb_bulk_transfer(device, endpoint, data, length, &transferred, timeout_ms);
  // A partial write may leave an incomplete frame in the firmware parser. Reconnect before sending any more.
  if (result != 0 || transferred != length) {
    mark_failed("bulk OUT", endpoint, length, transferred, timeout_ms, result != 0 ? result : LIBUSB_ERROR_IO);
  }
  return transferred;
}

int PandaUsbHandle::bulk_read(unsigned char endpoint, unsigned char *data, int length, unsigned int timeout) {
  if (!connected) return 0;
  int transferred = 0;
  const unsigned timeout_ms = timeout ? timeout : bulk_timeout_ms;
  const int result = libusb_bulk_transfer(device, endpoint, data, length, &transferred, timeout_ms);
  if (result != 0 && result != LIBUSB_ERROR_TIMEOUT) {
    mark_failed("bulk IN", endpoint, length, transferred, timeout_ms, result);
  }
  return transferred;
}
