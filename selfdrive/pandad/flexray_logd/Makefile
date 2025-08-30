CC= gcc
CFLAGS= -g -Wall -I. -I./libftdi -I/usr/include/libusb-1.0


LIBOBJS = libftdi/ftdispi.o libftdi/ftdi.o
LIBSTATIC = libftdi/libftdispi.a

LIBS=-L./libftdi -L/aarch64-linux-gnu -lusb-1.0


FLEXRAY_LOGD = flexray_logd
FLEXRAY_DUMP = flexray_dump
TEST_SPI= test_spi
TEST_GET_LOG = test_get_log
TEST_DECODE = test_decode

OBJS= $(LIBOBJS) test_spi.o
OBJS2= $(LIBOBJS) flexray_reader.o flexray_decoder.o flexray_logd.o
OBJS3= flexray_unpack.o test_get_log.o
OBJS4= flexray_unpack.o flexray_decoder.o test_decode.o
OBJS5= $(LIBOBJS) flexray_reader.o flexray_decoder.o flexray_dump.o


$(LIBSTATIC): $(LIBOBJS)
	ar rcs $@ $^

$(FLEXRAY_LOGD): $(OBJS2)
	$(CC) $(CFLAGS) -o $@ $(OBJS2) $(LIBS)

$(FLEXRAY_DUMP): $(OBJS5)
	$(CC) $(CFLAGS) -o $@ $(OBJS5) $(LIBS)

$(TEST_SPI): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LIBS)

$(TEST_GET_LOG): $(OBJS3)
	$(CC) $(CFLAGS) -o $@ $(OBJS3)

$(TEST_DECODE): $(OBJS4)
	$(CC) $(CFLAGS) -o $@ $(OBJS3)


libftdi/ftdispi.o: libftdi/ftdispi.h libftdi/ftdispi.c
libftdi/ftdi.o: libftdi/ftdi.h libftdi/ftdi.c
flexray_logd.o: flexray_logd.c flexray_decoder.h
flexray_reader.o: flexray_reader.c flexray_reader.h
flexray_decoder.o: flexray_decoder.c flexray_decoder.h
flexray_unpack.o: flexray_unpack.c flexray_decoder.h
flexray_dump.o: flexray_dump.c
test_get_log.o: test_get_log.c
test_spi.o: test_spi.c

all: $(LIBSTATIC) $(FLEXRAY_LOGD) $(FLEXRAY_DUMP)

test: $(TEST_SPI) $(TEST_GET_LOG)

clean:
	rm -f *.o libftdi/*.o
	rm -f $(FLEXRAY_LOGD)
	rm -f $(TEST_GET_LOG)
	rm -f $(TEST_SPI)
