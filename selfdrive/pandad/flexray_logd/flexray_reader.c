#include <stdio.h>
#include <unistd.h>
#include <sys/time.h>

#include "flexray_common.h"
#include "flexray_reader.h"
#include "ftdispi.h"

struct ftdi_context    fc;
struct ftdispi_context fsc;
FILE   *fd;

int open_ftdi(char *fname) {

  if (fname) {
    fd = fopen(fname, "rb");
    if (fd)
      return FT_FILE_TEST;
    else
      fprintf(stderr, "fail open file %s\n", fname);
  }

  if (open_ftdi_dev(FTDI_PID, FTDI_VID) == 0) {
    return FT_FASTSERIAL;
  }

  if (open_ftdi_dev(FTDI_PID, FTDI_VID4) == 0) {
    return FT_SPI;
  }

  return -1;
}

int open_ftdi_dev(int pid, int vid) {
    int i;

    if (ftdi_init(&fc) < 0)
    {
        fprintf(stderr, "ftdi_init failed\n");
        return -1;
    }

    if(ftdi_set_interface(&fc, INTERFACE_B) < 0)
    {
      fprintf(stderr, "Set Int Fail\n");
      return -1;
    }

    i = ftdi_usb_open(&fc, pid, vid);
    if (i < 0 && i != -5)
    {
        fprintf(stderr,
            "OPEN: %s (pid=%x, vid=%x)\n", ftdi_get_error_string(&fc), pid, vid);
        return -1;
    }

    return 0;
}


void *read_ftdi(void *arg) {
    struct flexray_reader_args *args = (struct flexray_reader_args*)arg;

    switch(args->ft_type) {
      case FT_FASTSERIAL:
          read_ftdi_fastserial(arg);
          break;

      case FT_SPI:
          read_ftdi_spi(arg);
          break;

      default:
          read_file_test(arg);
          break;
    }

    return NULL;
}


void read_file_test(void *arg) {
    struct flexray_reader_args *args = (struct flexray_reader_args*)arg;

    char buf[SPI_CHUNK_SIZE];
    char pending_buf[SPI_CHUNK_SIZE];
    int pending_len = 0;
    int is_printed = 0;

    struct timeval start, end;

    while(*(args->running)) {
        int bytes_read = 0;

        gettimeofday(&start, NULL);

        if(pending_len > 0) {
            bytes_read = pending_len;
            memcpy(buf, pending_buf, pending_len);
            pending_len = 0;
        } else {
          bytes_read = fread(buf, 1, SPI_CHUNK_SIZE, fd);
          if (bytes_read <= 0) {
             if (feof(fd)) {
                rewind(fd);
                clearerr(fd);
             } else if (ferror(fd)) {
                   perror("fread error");
             }

             usleep(10);
             continue;
          }
        }

				{
					pthread_mutex_lock(args->raw_mutex);

          size_t free_space = BUFFER_FREE(*args->raw_wpos, *args->raw_rpos, SPI_BUFFER_SIZE);
          if (bytes_read > free_space) {
            memcpy(pending_buf, buf, bytes_read);
            pending_len = bytes_read;

            if (!is_printed) {
              fprintf(stderr, "[flexray_logd:fileOVERFLOW]  %zu, free %zu, write %zu, read %zu\n", (size_t)bytes_read, free_space, *args->raw_wpos, *args->raw_rpos);
              is_printed = 1;
            }
            pthread_mutex_unlock(args->raw_mutex);
            continue;
          }

          size_t end_space = SPI_BUFFER_SIZE - *args->raw_wpos;

          if ((size_t)bytes_read <= end_space) {
            memcpy(args->raw_buffer + *args->raw_wpos, buf, bytes_read);
            *args->raw_wpos = (*args->raw_wpos + bytes_read) % SPI_BUFFER_SIZE;
          } else {
            memcpy(args->raw_buffer + *args->raw_wpos, buf, end_space);
            memcpy(args->raw_buffer, buf + end_space, bytes_read - end_space);
            *args->raw_wpos = bytes_read - end_space;
          }

					pthread_mutex_unlock(args->raw_mutex);
				}
        is_printed = 0;

        gettimeofday(&end, NULL);
        double elapsed = (end.tv_sec - start.tv_sec)
                         + (end.tv_usec - start.tv_usec) / 1e6;

        // 10MHz SPI: 1024바이트 = 819.2us 필요
        double need = bytes_read * 0.8e-6; // n * 0.8us (단위: 초)
        if (elapsed < need) {
           usleep((useconds_t)((need - elapsed) * 1e6));
        }
    }

    fclose(fd);
}



void read_ftdi_fastserial(void *arg) {
    struct flexray_reader_args *args = (struct flexray_reader_args*)arg;

    char buf[SPI_CHUNK_SIZE];
    char pending_buf[SPI_CHUNK_SIZE];
    int pending_len = 0;
    int is_printed = 0;

    if (ftdi_set_bitmode(&fc,  0xff, BITMODE_RESET) < 0) {
      fprintf(stderr, "Can't set synchronous fifo mode, Error %s",
          ftdi_get_error_string(&fc));
       return;
    }

    if (ftdi_set_latency_timer(&fc, 2)) {
      fprintf(stderr, "Can't set latency : (%s)", ftdi_get_error_string(&fc));
       return;
    }

    fc.usb_read_timeout = 5;

    while(*(args->running)) {
        int bytes_read = 0;

        if(pending_len > 0) {
            bytes_read = pending_len;
            memcpy(buf, pending_buf, pending_len);
            pending_len = 0;
        } else {
          bytes_read = ftdi_read_data(&fc, (uint8_t *)buf, SPI_CHUNK_SIZE);
          if (bytes_read < 0)
             continue;
#if _DEBUG_
           for (ssize_t i = 0; i < bytes_read; i++) {
                  printf("%02X ", (unsigned char)buf[i]);
                  if ((i + 1) % 16 == 0) printf("\n");
           }
           printf("\n");
#endif
        }

				pthread_mutex_lock(args->raw_mutex);

        size_t free_space = BUFFER_FREE(*args->raw_wpos, *args->raw_rpos, SPI_BUFFER_SIZE);
        if (bytes_read > free_space) {
          memcpy(pending_buf, buf, bytes_read);
          pending_len = bytes_read;

          if (!is_printed) {
            fprintf(stderr, 
               "[flexray_logd:fastserialOVERFLOW]  %zu, free %zu, write %zu, read %zu\n", 
               (size_t)bytes_read, free_space, *args->raw_wpos, *args->raw_rpos);
               is_printed = 1;
          }
          pthread_mutex_unlock(args->raw_mutex);
          continue;
        }

        size_t end_space = SPI_BUFFER_SIZE - *args->raw_wpos;

        if ((size_t)bytes_read <= end_space) {
          memcpy(args->raw_buffer + *args->raw_wpos, buf, bytes_read);
          *args->raw_wpos = (*args->raw_wpos + bytes_read) % SPI_BUFFER_SIZE;
        } else {
          memcpy(args->raw_buffer + *args->raw_wpos, buf, end_space);
          memcpy(args->raw_buffer, buf + end_space, bytes_read - end_space);
          *args->raw_wpos = bytes_read - end_space;
        }

			pthread_mutex_unlock(args->raw_mutex);
      is_printed = 0;
    }

    ftdi_usb_close(&fc);
}


void read_ftdi_spi(void *arg) {
    struct flexray_reader_args *args = (struct flexray_reader_args*)arg;

    char buf[SPI_CHUNK_SIZE];
    char pending_buf[SPI_CHUNK_SIZE];
    int pending_len = 0;
    int is_printed = 0;

    //if (open_ftdi_dev() < 0) return NULL;

    ftdispi_open(&fsc, &fc, INTERFACE_B);
    ftdispi_setmode(&fsc, 1, 0, 0, 0, 0, 0);
    //ftdispi_setclock(&fsc, 10000000);
    ftdispi_setclock(&fsc, 7500000);
    ftdispi_setloopback(&fsc,  0);

    while(*(args->running)) {
        int status = FTDISPI_ERROR_NONE;
        int bytes_read = 0;

        if(pending_len > 0) {
            bytes_read = pending_len;
            memcpy(buf, pending_buf, pending_len);
            pending_len = 0;
        } else {
          memset(buf, 0, SPI_CHUNK_SIZE);
          status = ftdispi_read_stream(&fsc, buf, SPI_CHUNK_SIZE, 0);
          if (status != FTDISPI_ERROR_NONE)
             continue;

          bytes_read = SPI_CHUNK_SIZE;
        }

				{
					pthread_mutex_lock(args->raw_mutex);

          size_t free_space = BUFFER_FREE(*args->raw_wpos, *args->raw_rpos, SPI_BUFFER_SIZE);
          if (bytes_read > free_space) {
            memcpy(pending_buf, buf, bytes_read);
            pending_len = bytes_read;

            if (!is_printed) {
              fprintf(stderr, "[flexray_logd:spiOVERFLOW]  %zu, free %zu, write %zu, read %zu\n", (size_t)bytes_read, free_space, *args->raw_wpos, *args->raw_rpos);
              is_printed = 1;
            }
            pthread_mutex_unlock(args->raw_mutex);
            continue;
          }


          size_t end_space = SPI_BUFFER_SIZE - *args->raw_wpos;

          if ((size_t)bytes_read <= end_space) {
            memcpy(args->raw_buffer + *args->raw_wpos, buf, bytes_read);
            *args->raw_wpos = (*args->raw_wpos + bytes_read) % SPI_BUFFER_SIZE;
          } else {
            memcpy(args->raw_buffer + *args->raw_wpos, buf, end_space);
            memcpy(args->raw_buffer, buf + end_space, bytes_read - end_space);
            *args->raw_wpos = bytes_read - end_space;
          }

					pthread_mutex_unlock(args->raw_mutex);
          is_printed = 0;
				}
    }

    ftdispi_close(&fsc, 1);
    return ;
}
