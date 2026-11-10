CC = gcc
.DEFAULT_GOAL := all
CPPFLAGS += -I. -Ilibftdi $(shell pkg-config --cflags libusb-1.0)
CFLAGS += -g -std=gnu11 -Wall -Wextra -pthread -MMD -MP
LDLIBS += $(shell pkg-config --libs libusb-1.0) -pthread
COMMON = flexray_capture.o flexray_output.o flexray_journal.o flexray_reader.o flexray_decoder.o libftdi/ftdispi.o libftdi/ftdispi_usb.o libftdi/ftdi.o

.PHONY: all test
tests/test_spi_pipeline: tests/test_spi_pipeline.c flexray_reader.c libftdi/ftdispi.c libftdi/ftdispi_usb.c
	$(CC) -Itests/mocks -I. -Ilibftdi $(CFLAGS) -o $@ $(filter %.c,$^) -pthread
all: flexray_logd flexray_dump
flexray_logd: flexray_logd.o $(COMMON)
flexray_dump: flexray_dump.o $(COMMON)
tests/test_decoder: tests/test_decoder.c flexray_decoder.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $(filter %.c %.o,$^)
tests/test_spi_timeout: tests/test_spi_timeout.c libftdi/ftdispi.o libftdi/ftdispi_usb.o libftdi/ftdi.o
	$(CC) $(CPPFLAGS) $(CFLAGS) -Wl,--wrap=ftdi_read_data -Wl,--wrap=ftdi_write_data -o $@ $(filter %.c %.o,$^) $(LDLIBS)
tests/test_output: tests/test_output.c flexray_output.c flexray_journal.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -Wl,--wrap=send -Wl,--wrap=write -o $@ $(filter %.c %.o,$^) -pthread
tests/test_reader: tests/test_reader.c tests/test_spi_pipeline.c flexray_reader.c libftdi/ftdispi.c libftdi/ftdispi_usb.c
	$(CC) -Itests/mocks -I. -Ilibftdi $(CFLAGS) -o $@ tests/test_reader.c flexray_reader.c libftdi/ftdispi.c libftdi/ftdispi_usb.c -pthread

test: all tests/test_decoder tests/test_spi_timeout tests/test_spi_pipeline tests/test_output tests/test_reader
	./tests/test_decoder
	./tests/test_spi_timeout
	./tests/test_spi_pipeline
	./tests/test_output
	./tests/test_reader
	python3 tests/test_capture.py

-include $(wildcard *.d libftdi/*.d tests/*.d)
