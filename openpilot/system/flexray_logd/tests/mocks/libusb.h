#ifndef SPI_TEST_LIBUSB_H
#define SPI_TEST_LIBUSB_H
struct libusb_device_handle;
#define LIBUSB_ERROR_NO_DEVICE -4
#define LIBUSB_ERROR_TIMEOUT -7
#define LIBUSB_ERROR_INTERRUPTED -10
int libusb_bulk_transfer(struct libusb_device_handle *, unsigned char,
                         unsigned char *, int, int *, unsigned int);
#endif
