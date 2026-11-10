#ifndef SPI_TEST_LIBUSB_H
#define SPI_TEST_LIBUSB_H
struct libusb_device_handle;
struct libusb_device;
struct libusb_device_descriptor {
  unsigned short idVendor, idProduct, bcdDevice;
  unsigned char bNumConfigurations;
};
int libusb_get_device_descriptor(struct libusb_device *, struct libusb_device_descriptor *);
int libusb_get_device_speed(struct libusb_device *);
unsigned char libusb_get_bus_number(struct libusb_device *);
unsigned char libusb_get_device_address(struct libusb_device *);
int libusb_get_port_numbers(struct libusb_device *, unsigned char *, int);
const char *libusb_error_name(int);
#define LIBUSB_ERROR_NO_DEVICE -4
#define LIBUSB_ERROR_TIMEOUT -7
#define LIBUSB_ERROR_INTERRUPTED -10
int libusb_bulk_transfer(struct libusb_device_handle *, unsigned char,
                         unsigned char *, int, int *, unsigned int);
#endif
