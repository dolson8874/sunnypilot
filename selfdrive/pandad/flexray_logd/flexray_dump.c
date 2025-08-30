#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <errno.h>
#include "flexray_common.h"
#include "flexray_reader.h"
#include "flexray_decoder.h"

char raw_buffer[SPI_BUFFER_SIZE];
size_t raw_wpos =0, raw_rpos = 0;

char proc_buffer[SPI_BUFFER_SIZE];
size_t proc_wpos =0, proc_rpos = 0;


char receive_buffer[SPI_BUFFER_SIZE+ 272];
size_t receive_buffer_size = 0;

pthread_mutex_t raw_mutex = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t proc_mutex = PTHREAD_MUTEX_INITIALIZER;

volatile int running = 1;
volatile int do_exit = 0;
FILE *fp = NULL;
int ft_type = -1;

#define LOG_FNAME "flexray_dump"


static void
sigintHandler(int signum) {
    running = 0;
    do_exit = 1;
    if (fp) fclose(fp);
		fp = NULL;
    fprintf(stderr, "\nexit flexray dump\n");
}



void *processing_thread(void *arg) {
    char fname[512];

    switch(ft_type) {
      case FT_FASTSERIAL :
          sprintf(fname, "%s-fastserial.log", LOG_FNAME);
          break;
      case FT_SPI :
          sprintf(fname, "%s-spi.log", LOG_FNAME);
          break;
      default:
    }

    printf("loging %s\n", fname);

    fp = fopen(fname, "wb");

    if (fp == NULL) {
      fprintf(stderr, "fail create file\n");
      return NULL;
    }

    while (running) {
				size_t cp_size = MAX_SEND_SIZE - receive_buffer_size;

        pthread_mutex_lock(&raw_mutex);
        size_t available = (raw_wpos >= raw_rpos) ?
            (raw_wpos - raw_rpos) : (SPI_BUFFER_SIZE - raw_rpos + raw_wpos);
        if (available == 0) {
            pthread_mutex_unlock(&raw_mutex);
            usleep(100);
            continue;
        }

				if (cp_size  > available) cp_size = available;


        size_t end = SPI_BUFFER_SIZE - raw_rpos;
        if (cp_size <= end) {
            memcpy(&receive_buffer[receive_buffer_size],
										raw_buffer + raw_rpos, cp_size);
            raw_rpos = (raw_rpos + cp_size) % SPI_BUFFER_SIZE;
        } else {
            memcpy(&receive_buffer[receive_buffer_size],
										raw_buffer + raw_rpos, end);
            memcpy(&receive_buffer[receive_buffer_size + end],
										raw_buffer, cp_size - end);
            raw_rpos = cp_size - end;
        }
        pthread_mutex_unlock(&raw_mutex);

        receive_buffer_size += cp_size;

        fwrite(receive_buffer, 1, receive_buffer_size, fp);
        fflush(fp);

        receive_buffer_size = 0;
    }

    fclose(fp);
    fp = NULL;
    return NULL;
}


int main(int argc, char *argv[]) {
    char *filename= NULL;
    pthread_t t1, t2;


    for (int i = 1; i < argc - 1; i++) {
        if (strcmp(argv[i], "-f") == 0) {
            filename = argv[i+1];
            break;
        }
    }

    ft_type = open_ftdi(filename);

    if(ft_type < 0) {
        return -1;
    }

		signal(SIGINT, sigintHandler);
		signal(SIGKILL, sigintHandler);
    signal(SIGPIPE, SIG_IGN);

    struct flexray_reader_args reader_args = {
        .raw_buffer = raw_buffer,
        .raw_wpos = &raw_wpos,
        .raw_rpos = &raw_rpos,
        .raw_mutex = &raw_mutex,
        .running = &running,
        .ft_type = ft_type
    };

    pthread_create(&t1, NULL, read_ftdi, (void *)&reader_args);
    pthread_create(&t2, NULL, processing_thread, NULL);

    pthread_join(t1, NULL);
    pthread_join(t2, NULL);

    signal(SIGINT, SIG_DFL);
    signal(SIGPIPE, SIG_DFL);
    return 0;
}
