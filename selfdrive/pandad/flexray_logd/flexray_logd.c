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


char receive_buffer[SPI_BUFFER_SIZE];
size_t receive_buffer_size = 0;

pthread_mutex_t raw_mutex = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t proc_mutex = PTHREAD_MUTEX_INITIALIZER;

volatile int is_decode = 1;
volatile int running = 1;
volatile int do_exit = 0;
int server_fd = -1;


static void
sigintHandler(int signum) {
    running = 0;
    do_exit = 1;
    if (server_fd >= 0) close(server_fd);
    unlink(SOCKET_PATH);
		server_fd = -1;
    fprintf(stderr, "\nexit flexraylogd\n");
    exit(0);
}


void *processing_thread(void *arg) {
    int is_printed = 0;

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

#if 0
        printf("receive_buffer_size=%ld\n", receive_buffer_size);
        for (ssize_t i = 0; i < receive_buffer_size; i++) {
              printf("%02X ", (unsigned char)receive_buffer[i]);
                if ((i + 1) % 16 == 0) printf("\n");
        }
        printf("\n");
#endif
        receive_buffer_size += cp_size;

        char out[MAX_SEND_SIZE+277];

        if (is_decode) {
				  cp_size = decode_flexray_buffer(receive_buffer, &receive_buffer_size, out, sizeof(out));
        } else {
          memcpy(out, receive_buffer, receive_buffer_size);
          cp_size = receive_buffer_size;
          receive_buffer_size = 0;
        }

        pthread_mutex_lock(&proc_mutex);

        size_t free = (proc_rpos > proc_wpos) ?
            (proc_rpos - proc_wpos - 1) : (SPI_BUFFER_SIZE - proc_wpos + proc_rpos - 1);

        while (cp_size > free && running) {
            pthread_mutex_unlock(&proc_mutex);
            usleep(100);

            pthread_mutex_lock(&proc_mutex);
            free = (proc_rpos > proc_wpos) ?
                        (proc_rpos - proc_wpos - 1) : (SPI_BUFFER_SIZE - proc_wpos + proc_rpos - 1);

            if (!is_printed) {
              fprintf(stderr, "[flexray_logd:processOVERFLOW]  %zu, free %zu, write %zu, read %zu\n", (size_t)cp_size, free, proc_wpos, proc_rpos);
            is_printed = 1;
            }

        }

        size_t pend = SPI_BUFFER_SIZE - proc_wpos;
        if (cp_size <= pend) {
           memcpy(proc_buffer + proc_wpos, out, cp_size);
           proc_wpos = (proc_wpos + cp_size) % SPI_BUFFER_SIZE;
        } else {
            memcpy(proc_buffer + proc_wpos, out, pend);
            memcpy(proc_buffer, out + pend, cp_size - pend);
            proc_wpos = cp_size - pend;
        }
        pthread_mutex_unlock(&proc_mutex);
        is_printed = 0;
    }
    return NULL;
}


void *server_thread(void *arg) {
    int client_fd;
    struct sockaddr_un addr;
    char sendbuf[MAX_SEND_SIZE];

    server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return NULL;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path)-1);
    unlink(SOCKET_PATH);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) == -1) {
        perror("bind");
        close(server_fd);
        return NULL;
    }
    if (listen(server_fd, 1) == -1) {
        perror("listen");
        close(server_fd);
        return NULL;
    }

		while (running) {
    	client_fd = accept(server_fd, NULL, NULL);
    	if (client_fd == -1) continue;

      unsigned char cmd_buf[16] = {0};
      ssize_t n = read(client_fd, cmd_buf, sizeof(cmd_buf));
      ssize_t req_size = MAX_SEND_SIZE;

      if (n>0) {
        switch(cmd_buf[0]) {
          case 0x1F : // Init buffer
            printf("flexray_logd: reset buffer\n");
            pthread_mutex_lock(&proc_mutex);
            proc_wpos = 0;
            proc_rpos = 0;
            memset(proc_buffer, 0, SPI_BUFFER_SIZE);
            pthread_mutex_unlock(&proc_mutex);

            n = write(client_fd, "OK", 2);
            close(client_fd);
            continue;
            break;
          case 0x80 : // read buffer
            req_size = cmd_buf[1] << 8 | cmd_buf[2];
            if (req_size > MAX_SEND_SIZE) 
              req_size = MAX_SEND_SIZE;
            break;
          default:
            close(client_fd);
            continue;
        }
      }


  	  pthread_mutex_lock(&proc_mutex);

    	size_t temp_write_pos = proc_wpos;
	    size_t available = 0;

  	  if (proc_rpos == temp_write_pos) {
    	    available = 0;
	    } else if (proc_rpos < temp_write_pos) {
  	      available = temp_write_pos - proc_rpos;
	    } else {
  	      available = (SPI_BUFFER_SIZE - proc_rpos) + temp_write_pos;
	    }

	    size_t to_send = (available < MAX_SEND_SIZE) ? available : MAX_SEND_SIZE;
      if (to_send > req_size)
        to_send = req_size;

  	  if (to_send == 0) {
        	pthread_mutex_unlock(&proc_mutex);
      	  close(client_fd);
	        continue;
  	  }

  	  if (proc_rpos < temp_write_pos 
 						|| to_send <= SPI_BUFFER_SIZE - proc_rpos) {
	        memcpy(sendbuf, proc_buffer + proc_rpos, to_send);
	    } else {
  	      size_t first_chunk = SPI_BUFFER_SIZE - proc_rpos;
    	    memcpy(sendbuf, proc_buffer + proc_rpos, first_chunk);
      	  memcpy(sendbuf + first_chunk, proc_buffer, to_send - first_chunk);
	    }
  	  proc_rpos = (proc_rpos + to_send) % SPI_BUFFER_SIZE;

  	  pthread_mutex_unlock(&proc_mutex);

  	  n = write(client_fd, sendbuf, to_send);
      //printf("req %zd, send %zd\n", req_size, n);

      if(n < 0) {
        if(errno == EPIPE)
           fprintf(stderr, "flexray_logd: error pipe\n");
        else
           fprintf(stderr, "flexray_logd: errno = %d\n", errno);
      }

   	 	close(client_fd);
		}

    if (server_fd >= 0) close(server_fd);
    unlink(SOCKET_PATH);

    return NULL;
}


int main(int argc, char *argv[]) {
    pthread_t t1, t2, t3;
    char *filename= NULL;
    int ft_type = -1;
    int opt;


    while ((opt = getopt(argc, argv, "sf:")) != -1) {
        switch (opt) {
            case 's':
                is_decode = 0;
                break;
            case 'f':
                filename = optarg;
                break;
            default:
                fprintf(stderr, "Usage: %s [-sf]\n", argv[0]);
                fprintf(stderr, "      -s : skip decode frame\n");
                fprintf(stderr, "      -f : file open data\n");
                fprintf(stderr, "\n");
                exit(EXIT_FAILURE);
        }
    }



    for (int i = 1; i < argc - 1; i++) {
        if (strcmp(argv[i], "-f") == 0) {
            filename = argv[i+1];
            break;
        }
    }


    //filename = "/data/dolson/flexray_logd/flexray_dump-fastserial-250808-01.log";
    ft_type = open_ftdi(filename);

    if(ft_type < 0) {
        while(!do_exit) usleep(100);

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
    pthread_create(&t3, NULL, server_thread, NULL);

    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    pthread_join(t3, NULL);

    signal(SIGINT, SIG_DFL);
    signal(SIGPIPE, SIG_DFL);
    return 0;
}
