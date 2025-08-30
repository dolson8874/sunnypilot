#ifndef FLEXRAY_READER_H
#define FLEXRAY_READER_H

#include <stddef.h>
#include <pthread.h>

#define FTDI_PID  0x0403
#define FTDI_VID  0x6010   // ft2232 fastserial
#define FTDI_VID4 0x6011   // ft4232 spi

typedef enum {
    FT_FILE_TEST = 0,
    FT_FASTSERIAL,
    FT_SPI
} FTDI_DEV_TYPE;


void read_ftdi_fastserial(void *arg);
void read_ftdi_spi(void *arg);
void read_file_test(void *arg);

void *read_ftdi(void *arg);
int open_ftdi_dev(int pid, int vid);
int open_ftdi(char *fname);

struct flexray_reader_args {
    char *raw_buffer;
    size_t *raw_wpos;
    size_t *raw_rpos;
    pthread_mutex_t *raw_mutex;
    volatile int *running;
    FTDI_DEV_TYPE ft_type;
};

#endif

