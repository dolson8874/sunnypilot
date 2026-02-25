#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "flexray_decoder.h"

#define _USE_CRC_TABLE_

#define FLEXRAY_CRC11_POLY   0x385
#define FLEXRAY_CRC11_INIT   0x01A
#define FLEXRAY_CRC11_WIDTH  11
#define FLEXRAY_CRC11_MASK   ((1u << FLEXRAY_CRC11_WIDTH) - 1)

#ifdef _USE_CRC_TABLE_

// poly=0x385, width=11, MSB-first
static const uint16_t flexray_crc11_table8[256] = {
  0x000, 0x385, 0x70A, 0x48F, 0x591, 0x614, 0x29B, 0x11E,
  0x0A7, 0x322, 0x7AD, 0x428, 0x536, 0x6B3, 0x23C, 0x1B9,
  0x14E, 0x2CB, 0x644, 0x5C1, 0x4DF, 0x75A, 0x3D5, 0x050,
  0x1E9, 0x26C, 0x6E3, 0x566, 0x478, 0x7FD, 0x372, 0x0F7,
  0x29C, 0x119, 0x596, 0x613, 0x70D, 0x488, 0x007, 0x382,
  0x23B, 0x1BE, 0x531, 0x6B4, 0x7AA, 0x42F, 0x0A0, 0x325,
  0x3D2, 0x057, 0x4D8, 0x75D, 0x643, 0x5C6, 0x149, 0x2CC,
  0x375, 0x0F0, 0x47F, 0x7FA, 0x6E4, 0x561, 0x1EE, 0x26B,
  0x538, 0x6BD, 0x232, 0x1B7, 0x0A9, 0x32C, 0x7A3, 0x426,
  0x59F, 0x61A, 0x295, 0x110, 0x00E, 0x38B, 0x704, 0x481,
  0x476, 0x7F3, 0x37C, 0x0F9, 0x1E7, 0x262, 0x6ED, 0x568,
  0x4D1, 0x754, 0x3DB, 0x05E, 0x140, 0x2C5, 0x64A, 0x5CF,
  0x7A4, 0x421, 0x0AE, 0x32B, 0x235, 0x1B0, 0x53F, 0x6BA,
  0x703, 0x486, 0x009, 0x38C, 0x292, 0x117, 0x598, 0x61D,
  0x6EA, 0x56F, 0x1E0, 0x265, 0x37B, 0x0FE, 0x471, 0x7F4,
  0x64D, 0x5C8, 0x147, 0x2C2, 0x3DC, 0x059, 0x4D6, 0x753,
  0x1F5, 0x270, 0x6FF, 0x57A, 0x464, 0x7E1, 0x36E, 0x0EB,
  0x152, 0x2D7, 0x658, 0x5DD, 0x4C3, 0x746, 0x3C9, 0x04C,
  0x0BB, 0x33E, 0x7B1, 0x434, 0x52A, 0x6AF, 0x220, 0x1A5,
  0x01C, 0x399, 0x716, 0x493, 0x58D, 0x608, 0x287, 0x102,
  0x369, 0x0EC, 0x463, 0x7E6, 0x6F8, 0x57D, 0x1F2, 0x277,
  0x3CE, 0x04B, 0x4C4, 0x741, 0x65F, 0x5DA, 0x155, 0x2D0,
  0x227, 0x1A2, 0x52D, 0x6A8, 0x7B6, 0x433, 0x0BC, 0x339,
  0x280, 0x105, 0x58A, 0x60F, 0x711, 0x494, 0x01B, 0x39E,
  0x4CD, 0x748, 0x3C7, 0x042, 0x15C, 0x2D9, 0x656, 0x5D3,
  0x46A, 0x7EF, 0x360, 0x0E5, 0x1FB, 0x27E, 0x6F1, 0x574,
  0x583, 0x606, 0x289, 0x10C, 0x012, 0x397, 0x718, 0x49D,
  0x524, 0x6A1, 0x22E, 0x1AB, 0x0B5, 0x330, 0x7BF, 0x43A,
  0x651, 0x5D4, 0x15B, 0x2DE, 0x3C0, 0x045, 0x4CA, 0x74F,
  0x6F6, 0x573, 0x1FC, 0x279, 0x367, 0x0E2, 0x46D, 0x7E8,
  0x71F, 0x49A, 0x015, 0x390, 0x28E, 0x10B, 0x584, 0x601,
  0x7B8, 0x43D, 0x0B2, 0x337, 0x229, 0x1AC, 0x523, 0x6A6
};

// ---- 4비트(니블) 테이블(16) ----
// (8비트 테이블의 상위 16개와 동일)
static const uint16_t flexray_crc11_table4[16] = {
  0x000, 0x385, 0x70A, 0x48F, 0x591, 0x614, 0x29B, 0x11E,
  0x0A7, 0x322, 0x7AD, 0x428, 0x536, 0x6B3, 0x23C, 0x1B9
};

// data20: 상위 20비트 데이터 (flags(2)+frame_id(11)+length(7))
static inline uint16_t flexray_crc11_calc(uint32_t data20)
{
  uint16_t crc = FLEXRAY_CRC11_INIT;

  // 상위 8비트
  uint8_t d8  = (data20 >> 12) & 0xFF;
  uint8_t idx = ((crc >> (FLEXRAY_CRC11_WIDTH - 8)) ^ d8) & 0xFF;
  crc = ((crc << 8) ^ flexray_crc11_table8[idx]) & FLEXRAY_CRC11_MASK;

  // 중간 8비트
  d8  = (data20 >> 4) & 0xFF;
  idx = ((crc >> (FLEXRAY_CRC11_WIDTH - 8)) ^ d8) & 0xFF;
  crc = ((crc << 8) ^ flexray_crc11_table8[idx]) & FLEXRAY_CRC11_MASK;

  // 마지막 4비트(니블 테이블 사용)
  uint8_t d4 = data20 & 0x0F;
  idx = ((crc >> (FLEXRAY_CRC11_WIDTH - 4)) ^ d4) & 0x0F;
  crc = ((crc << 4) ^ flexray_crc11_table4[idx]) & FLEXRAY_CRC11_MASK;

  return crc;
}

#else  // _USE_CRC_TABLE_

static inline uint16_t flexray_crc11_calc(uint32_t data20)
{
  uint16_t reg = FLEXRAY_CRC11_INIT;

  for (int i = 19; i >= 0; --i) {
    uint16_t bit = ((reg >> (FLEXRAY_CRC11_WIDTH - 1)) & 1u) ^ ((data20 >> i) & 1u);
    reg = ((reg << 1) & FLEXRAY_CRC11_MASK);
    if (bit) reg ^= FLEXRAY_CRC11_POLY;
  }
  return reg & FLEXRAY_CRC11_MASK;
}
#endif // _USE_CRC_TABLE_

uint8_t calculate_flexray_checksum(uint8_t *header, uint16_t fid /*unused*/) {
  (void)fid;
  struct flexray_header *hdr = (struct flexray_header *)header;

  // 입력 20비트 구성: flags(2) + frame_id(11) + length(7)
  uint32_t data20 =
      (((uint32_t)(hdr->flagsid & 0x3)   << 14) |
       ((uint32_t)(hdr->frame_id & 0x7FF) << 7) |
       ((uint32_t)(hdr->length   & 0x7F)));

  uint16_t crc_calc = flexray_crc11_calc(data20);

  // 원본 CRC 11비트: [10] = crc_msb, [9:2] = crc, [1:0] = crc_lsb
  uint16_t crc_org =
      ( ((uint16_t)(hdr->crc_msb & 0x1) << 10) |
        ((uint16_t) hdr->crc           << 2)   |
        ((uint16_t)(hdr->crc_lsb & 0x3)) );

  if (crc_calc != crc_org) {
    fprintf(stderr, "flexray_decoder: CRC mismatch data=0x%05X calc=0x%03X org=0x%03X\n",
            (unsigned)data20, crc_calc, crc_org);
  }
  // 0 = OK, 1 = 에러
  return (crc_calc != crc_org);
}



// decode flexray for cabana
size_t decode_flexray_buffer(char *data, size_t *psize, char *out, size_t out_size) {
	int pos = 0;
  int o_size = 0;
  size_t  size = *psize;

  while (pos <= size - sizeof(struct can_header)) {
    struct can_header header, new_header;

    uint16_t data_len;
    struct flexray_header *fheader;
    uint16_t frame_id;


		// find frame start
    if((uint8_t)data[pos] != 0xCA || (uint8_t)data[pos+1] != 0xA0) {
      pos++;
      continue;
    }

    pos++;

    memcpy(&header, &data[pos], sizeof(struct can_header));

    fheader =  (struct flexray_header *)(&header);

    // flags(1) + counter (1) + data (len) + CRC (3)
    data_len =  fheader->length * 2 + 5;

    frame_id = fheader->frame_id | ((fheader->flagsid & 0x7) << 8);

    //printf("id=%x cycle=%d\n", frame_id, fheader->counter);

   if (pos + sizeof(struct can_header) + data_len > size) {
      // we don't have all the data for this message yet
      break;
    }

    if (out_size - o_size < sizeof(struct can_header) + data_len) {
      break;
    }

    if (calculate_flexray_checksum((uint8_t *) &header , frame_id) != 0) {
        //fprintf(stderr, "flexray_decoder : err header check_sum\n");
        pos++;
        continue;
    }

    if (fheader->reserved == 1 ){
      unsigned char sync_id;

      switch(frame_id)
      {
        // 200Hz
        case 0x7F:
          sync_id = 0;
          break;

        // 100Hz
        case 0x0f: // 250114 50->100hz
    		case 0x12:
        case 0x17:
        case 0x18:
        case 0x1E:
        case 0x20: // 250114 50->100
        case 0x22:
        case 0x23:
        case 0x29: // 250114 50->100
        case 0x2B:
        case 0x2F:
        case 0x3A:
        case 0x3E: // 250114 50->100
          sync_id = fheader->counter % 2;
          break;

        case 0x3B:
          // 250113
          sync_id = fheader->counter % 2;
          if (sync_id == 0) {
            // 50Hz
            sync_id = fheader->counter % 4;
            sync_id = sync_id + 0x10;
          }
          break;

        case 0x32:
          sync_id = fheader->counter % 2;
          if (sync_id == 1)
          {
            sync_id = fheader->counter % 4;
            sync_id = sync_id + 0x10;
          }
          break;
       // 25Hz
        case 0x10: // 250112
        case 0x6: // 250112
          sync_id = fheader->counter % 8;
          if (fheader->counter == 1 || fheader->counter == 33)
            sync_id = 0x11;
          else if (sync_id == 2 && (fheader->counter % 16) == 2)
            sync_id = 0x22;
          else if (sync_id == 5 && fheader->counter == 5)
            sync_id = 0x55;
          break;

        case 0x30:
        case 0x2E:
        case 0x31: // 250111 50->25
          sync_id = fheader->counter % 8;

          // merge 0,4
          if (sync_id == 4) {
            sync_id = 0;

          // split 5, 13
          }else if (sync_id == 5) {
              sync_id = fheader->counter % 16;
              sync_id = sync_id + 0x50;
          }
          break;

        // 13Hz
        case 0x5:
        case 0x19:  // 250114 50->13hz
          sync_id = fheader->counter % 16;
          // 250112
          if (sync_id == 0xa)
            sync_id = 2;
          break;
        case 0x14: // 250111
          sync_id = fheader->counter % 16;
          break;
        case 0x24: // 250112
          sync_id = fheader->counter % 16;
          if (sync_id == 0 &&  (fheader->counter % 32))
            sync_id = 0x32;
          break;


        case 0xa : // 250114, 100-> 50hz
        case 0xb : // 250111, 100-> 50hz
        default:
          // 50Hz
          sync_id = fheader->counter % 4;

          if (frame_id == 0xa && sync_id == 2) // 250115 50->100
            sync_id = 0;

          else if (frame_id == 0x1A)
          {
            if (sync_id != 0 && sync_id != 3)   // 250115, 250116 add 3
            {
              sync_id = fheader->counter % 16;
              sync_id = sync_id + 0x10;
            }
          }
          else if (frame_id == 0x1B)
          {
            if (sync_id != 0 && sync_id != 2)
            {
              sync_id = fheader->counter % 8;
              // 250112
              if (sync_id == 3 && (fheader->counter % 16) == 3)
                sync_id = 0x33;
            }

            if (fheader->counter == 7)
              sync_id = 0x77;
          }
          break;

      }

      new_header.addr = frame_id << 8 | (sync_id & 0xff);

    }

    new_header.rejected = 0;
    new_header.returned = 0;
    new_header.bus = fheader->bus;
    new_header.checksum = fheader->length;


		memcpy(&out[o_size], (char *)&new_header, sizeof(struct can_header));
    memcpy(&out[o_size + sizeof(struct can_header)], (char *)&data[pos + sizeof(struct can_header)], data_len);

    #if 0
    static unsigned long dcount = 0;
    dcount++;
    //if (dcount >= 900 && dcount <= 914) 
    {
      int i;

      printf("%04ld: ", dcount);
      for(i=0; i< sizeof(struct can_header) + data_len; i++) {
        printf("%02X ", out[o_size + i]);
      }

      printf("\n");
    }
    #endif

    pos += sizeof(struct can_header) + data_len;
    o_size += sizeof(struct can_header) + data_len;
  }


  // move the overflowing data to the beginning of the buffer for the next round

  //fprintf (stderr, "size = %ld, osize=%d, pos=%d\n", size, o_size, pos);
  memmove(data, &data[pos], size - pos);
  *psize -= pos;

  return o_size;
}


