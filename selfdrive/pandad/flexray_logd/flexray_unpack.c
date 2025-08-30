#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "flexray_decoder.h"
#include "flexray_unpack.h"

int flexray_unpack(char *data, int size) {
  int pos = 0;

  while (pos <= size - sizeof(struct can_header)) {
    struct can_header header;

    uint16_t data_len;
    uint16_t hdrsize = sizeof(header);

    memcpy(&header, &data[pos], hdrsize);

    // flags(1) + counter (1) + data (len) + CRC (3)
    // use flexray data length
    data_len =  header.checksum * 2 + 5;


    if (pos + hdrsize + data_len > size) {
      // we don't have all the data for this message yet
      #if 0
      printf("pos(%d)+hdrsize(%d)+data_len(%d) > size %d > %d remain=%d\n",
          pos, hdrsize, data_len, 
          pos + hdrsize + data_len, size,
          size-pos);
      #endif
      break;
    }

#if 1
    printf("%05x %02d : ", header.addr, header.bus);

    for(int i=0; i<data_len; i++)
       printf("%02X ", data[pos + hdrsize + i]);

    printf("\n");
#else
    // debug
    if ( (header.addr & 0x300) != 0x300 || data_len  != 31)
      printf("err \n");
#endif

    pos += hdrsize + data_len;


  }

  memmove(data, &data[pos], size - pos);
  size -= pos;

  return size;
}
