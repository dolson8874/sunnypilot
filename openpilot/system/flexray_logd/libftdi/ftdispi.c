/**
 * @file ftdispi.c
 *
 * @author Stany MARCEL <stanypub@gmail.com>
 *
 * @brief libftdispi permits to use FTDI component in SPI master
 * mode. Require libftdi
 *
 * BSD License
 *
 * Copyright ©2010, Stany MARCEL <stanypub@gmail.com> All rights
 * reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * Redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer.
 *
 * Redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the
 * distribution.
 *
 * Neither the name of the owner nor the names of its contributors may
 * be used to endorse or promote products derived from this software
 * without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT HOLDER BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
 * USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
 * OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "ftdispi.h"
#include <errno.h>

#define BBMODE_NORMAL 1
#define BBMODE_SPI    2

/* Clock X5 Command for H class component */
#define TCK_X5 0x8a

#define BIT_P_CS 0x08
#define BIT_P_DI 0x04
#define BIT_P_DO 0x02
#define BIT_P_SK 0x01
#define BIT_P_G0 FTDISPI_GPO0
#define BIT_P_G1 FTDISPI_GPO1
#define BIT_P_G2 FTDISPI_GPO2
#define BIT_P_G3 FTDISPI_GPO3
#define BIT_P_GX (FTDISPI_GPO0|FTDISPI_GPO1|FTDISPI_GPO2|FTDISPI_GPO3)

#define BIT_DIR (BIT_P_SK|BIT_P_DO|BIT_P_CS|BIT_P_G0|BIT_P_G1|BIT_P_G2|BIT_P_G3)

#define SPI_MAX_MSG_SIZE (64*1024)
#define DEFAULT_MEM_SIZE ((SPI_MAX_MSG_SIZE) + 9)

#define RETRY_MAX       10
#define RETRY_TIME      1000

#define FTDI_CHECK(FUN, MSG, CTX) do { \
  errno = 0; \
  int operation_result = (FUN); \
  int operation_errno = errno; \
  fprintf(stderr, "native stage=%s rc=%d errno=%d strerror=%s libftdi=%s\n", \
          MSG, operation_result, operation_errno, strerror(operation_errno), operation_result < 0 ? ftdi_get_error_string(&CTX) : "none"); \
  if (operation_result < 0) { errno = operation_errno; return FTDISPI_ERROR_LIB; } \
} while (0)

#define ASSERT_CHECK(TEST, MSG, RVAL) do {		\
		if ((TEST))                             \
		{                                       \
			fprintf(stderr,			\
				"ASSERT: %s\n", MSG);	\
			return RVAL;			\
		} } while (0)

static int spi_write_exact(struct ftdispi_context *fsc, const unsigned char *data, int size) {
  if (fsc->stream_error) return -1;
  int written = ftdi_write_data(&fsc->fc, data, size);
  if (written != size) {
    int saved = errno;
    fprintf(stderr, "native stage=command_write rc=%d expected=%d errno=%d strerror=%s libftdi=%s\n",
            written, size, saved, strerror(saved), ftdi_get_error_string(&fsc->fc));
    fsc->stream_error = FTDISPI_ERROR_LIB; errno = saved; return -1;
  }
  return written;
}

static int ftdispi_realloc(struct ftdispi_context *fsc, size_t size);
static int ftdispi_wait(struct ftdispi_context *fsc, uint8_t mask,
			uint8_t value, int maxtry);

static int spi_high_speed(const struct ftdispi_context *fsc) {
  return fsc->profile == FTDISPI_PROFILE_FLEXRAY_6011 ||
         fsc->fc.type == TYPE_2232H || fsc->fc.type == TYPE_4232H || fsc->fc.type == TYPE_232H;
}

__dll int ftdispi_open(struct ftdispi_context *fsc, struct ftdi_context *fc, int interface) {
  return ftdispi_open_profile(fsc, fc, interface, FTDISPI_PROFILE_AUTO);
}

__dll int ftdispi_open_profile(struct ftdispi_context *fsc, struct ftdi_context *fc,
                             int interface, enum ftdispi_profile profile)
{
	ASSERT_CHECK(!fc || !fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
	memset(fsc, 0, sizeof(*fsc));
  fsc->bitini = BIT_P_CS;
  fsc->profile = profile;
	memcpy(&fsc->fc, fc, sizeof(*fc));
	if (0 != (fsc->mem = malloc(DEFAULT_MEM_SIZE))) {
		fsc->memsize = DEFAULT_MEM_SIZE;
	}
	else return FTDISPI_ERROR_MEM;
  #if 0
	FTDI_CHECK(ftdi_write_data_set_chunksize(&fsc->fc, 512),
		   "SET CHUNK 512", fsc->fc);
  #else
	FTDI_CHECK(ftdi_write_data_set_chunksize(&fsc->fc, 16384),
		   "SET CHUNK 16384", fsc->fc);
  FTDI_CHECK(ftdi_read_data_set_chunksize(&fsc->fc, 16384),
       "SET RCHUNK 16K", fsc->fc);
  #endif
	FTDI_CHECK(ftdi_set_interface(&fsc->fc, interface), "SET INT",
		   fsc->fc);
	FTDI_CHECK(ftdi_usb_reset(&fsc->fc), "interface_reset", fsc->fc);
	FTDI_CHECK(ftdi_set_latency_timer(&fsc->fc, 2), "SET LAT 2ms", fsc->fc);
  #if 0
	FTDI_CHECK(ftdi_setflowctrl(&fsc->fc, SIO_RTS_CTS_HS), "RTS/CTS",
		   fsc->fc);
  #endif
	FTDI_CHECK(ftdi_set_bitmode(&fsc->fc, 0, BITMODE_RESET), "mpsse_reset", fsc->fc);
	FTDI_CHECK(ftdi_set_bitmode(&fsc->fc, 0, BBMODE_SPI), "SET SPI MODE",
		   fsc->fc);

  FTDI_CHECK(ftdi_tcioflush(&fsc->fc), "PURGE", fsc->fc);
  uint8_t init_cmds[] = {
    0x8A, // Disable divide-by-5 → 60 MHz ref
    0x97, // Disable adaptive clocking
    0x8D, // Disable 3-phase clocking (I2C용 기능, SPI에서는 OFF)
    0x85  // Disable loopback
  };
  int high_speed = spi_high_speed(fsc);
  unsigned char *initial = high_speed ? init_cmds : init_cmds + 3;
  int initial_size = high_speed ? sizeof(init_cmds) : 1;
  if (spi_write_exact(fsc, initial, initial_size) != initial_size) return FTDISPI_ERROR_LIB;

	fsc->wr_cmd = MPSSE_DO_WRITE;
	fsc->rd_cmd = MPSSE_DO_READ | MPSSE_READ_NEG;
	fsc->bitini = BIT_P_CS;


	return FTDISPI_ERROR_NONE;
}

__dll int ftdispi_setclock(struct ftdispi_context *fsc, uint32_t speed)
{
  ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
  int high_speed = spi_high_speed(fsc);
  if (speed < CLOCK_MIN_SPEED || speed > CLOCK_MAX_SPEEDX5 || (!high_speed && speed > CLOCK_MAX_SPEED))
    return FTDISPI_ERROR_CLK;
  uint32_t base = high_speed && speed > CLOCK_MAX_SPEED ? CLOCK_MAX_SPEEDX5 : CLOCK_MAX_SPEED;
  uint32_t divisor = (base + speed - 1) / speed - 1;
  if (divisor > 0xffff) return FTDISPI_ERROR_CLK;
  uint8_t command[4]; int size = 0;
  if (high_speed) command[size++] = base == CLOCK_MAX_SPEEDX5 ? 0x8a : 0x8b;
  command[size++] = TCK_DIVISOR;
  command[size++] = divisor & 0xff; command[size++] = divisor >> 8;
  if (spi_write_exact(fsc, command, size) != size) { fsc->actual_clock_hz = 0; fsc->stream_error = FTDISPI_ERROR_LIB; return FTDISPI_ERROR_LIB; }
  fsc->actual_clock_hz = base / (divisor + 1);
  fprintf(stderr, "SPI: requested_clock=%uHz configured_clock=%uHz divisor=%u divide_by_5=%d (not measured I/O)\n",
          speed, fsc->actual_clock_hz, divisor, high_speed && base == CLOCK_MAX_SPEED);
  return FTDISPI_ERROR_NONE;
}

__dll int ftdispi_setloopback(struct ftdispi_context *fsc, int active)
{
	uint8_t buf[1] = { 0 };

	ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
	if (active) {
		buf[0] = LOOPBACK_START;
		FTDI_CHECK(spi_write_exact(fsc, buf, 1), "SET LOOP",
			   fsc->fc);
	} else {
		buf[0] = LOOPBACK_END;
		FTDI_CHECK(spi_write_exact(fsc, buf, 1), "SET NO LOOP",
			   fsc->fc);
	}
	return FTDISPI_ERROR_NONE;
}

__dll int ftdispi_setmode(struct ftdispi_context *fsc,
			  int csh,
			  int cpol,
			  int cpha, int lsbfirst, int bitmode, int gpoini)
{
	uint8_t buf[3] = { 0, 0, 0 };

	ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
	fsc->wr_cmd = MPSSE_DO_WRITE | (bitmode ? MPSSE_BITMODE : 0);
	fsc->rd_cmd = MPSSE_DO_READ | (bitmode ? MPSSE_BITMODE : 0);
	fsc->bitini = (csh ? BIT_P_CS : 0) | (BIT_P_GX & gpoini);

	if (!cpol) {
		/* CLK IDLE = 0 */
		if (!cpha) {
			/* W=FE R=RE => NO TX */
			fsc->wr_cmd |= MPSSE_WRITE_NEG;
		} else {
			/* W=RE R=FE > RX OPT */
			fsc->rd_cmd |= MPSSE_READ_NEG;
		}
	} else {
		/* CLK IDLE == 1 */
		fsc->bitini |= BIT_P_SK;
		if (!cpha) {
			/* W=RE R=FE => NO TX */
			fsc->rd_cmd |= MPSSE_READ_NEG;
		} else {
			/* W=FE R=RE => RX OPT */
			fsc->wr_cmd |= MPSSE_WRITE_NEG;
		}
	}
	if (lsbfirst) {
		fsc->wr_cmd |= MPSSE_LSB;
		fsc->rd_cmd |= MPSSE_LSB;
	} else {
		fsc->wr_cmd &= ~MPSSE_LSB;
		fsc->rd_cmd &= ~MPSSE_LSB;
	}

	buf[0] = SET_BITS_LOW;
	buf[1] = fsc->bitini;
	buf[2] = BIT_DIR;
	FTDI_CHECK(spi_write_exact(fsc, buf, 3), "WR INI", fsc->fc);
	return ftdispi_wait(fsc, BIT_P_CS | BIT_P_GX, fsc->bitini, RETRY_MAX);
}


__dll int ftdispi_read_stream(struct ftdispi_context *fsc,
                              void *rbuf, uint16_t rcount, uint8_t gpo)
{
  int i = 0, n = 0, r;
  ASSERT_CHECK(!fsc || !fsc->mem || !rbuf || !rcount, "INVALID STREAM", FTDISPI_ERROR_CTX);
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
  struct timespec start, now;
  clock_gettime(CLOCK_MONOTONIC, &start);
  // CS Low
  fsc->mem[i++] = SET_BITS_LOW;
  fsc->mem[i++] = ((0x0F & (fsc->bitini ^ BIT_P_CS)) | (BIT_P_GX & gpo));
  fsc->mem[i++] = BIT_DIR;

  fsc->mem[i++] = fsc->rd_cmd;
  fsc->mem[i++] = (rcount - 1) & 0xFF;
  fsc->mem[i++] = ((rcount - 1) >> 8) & 0xFF;

  r = spi_write_exact(fsc, fsc->mem, i);
  if (r != i) return FTDISPI_ERROR_LIB;

  for (n = 0; n < rcount; n += r) {
    FTDI_CHECK(r = ftdi_read_data(&fsc->fc, (uint8_t*)rbuf + n, rcount - n),
               "RDSTREAM RD", fsc->fc);
    clock_gettime(CLOCK_MONOTONIC, &now);
    if (now.tv_sec - start.tv_sec + (now.tv_nsec - start.tv_nsec) / 1e9 >= 1.0)
      return FTDISPI_ERROR_TO;
    if (r == 0) usleep(1000);
  }

  return FTDISPI_ERROR_NONE;
}

static int64_t stream_ns(struct timespec t) {
  return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}

static int stream_refill(struct ftdispi_context *fsc) {
  if (fsc->stream_stop && *fsc->stream_stop) ftdispi_stream_finish(fsc);
  if (fsc->stream_draining || fsc->stream_error) return 0;
  // At most two chunks of response data can be outstanding. Replenish before
  // returning received data to the decoder/file workers, hiding their latency.
  while (fsc->stream_pending <= fsc->stream_chunk) {
    if (fsc->stream_stop && *fsc->stream_stop) { ftdispi_stream_finish(fsc); return 0; }
    uint16_t n = fsc->stream_chunk;
    uint8_t command[] = {SET_BITS_LOW,
      (uint8_t)((0x0f & (fsc->bitini ^ BIT_P_CS)) | (BIT_P_GX & fsc->stream_gpo)),
      BIT_DIR, fsc->rd_cmd, (uint8_t)(n-1), (uint8_t)((n-1)>>8)};
    int written = spi_write_exact(fsc, command, sizeof(command));
    if (written != (int)sizeof(command)) {
      // A short command can have entered MPSSE: never silently resubmit it.
      fsc->stream_error = FTDISPI_ERROR_LIB; return fsc->stream_error;
    }
    fsc->stream_pending += n; fsc->stream_commands++;
    if (fsc->stream_pending > fsc->stream_pending_peak) fsc->stream_pending_peak = fsc->stream_pending;
  }
  return 0;
}

__dll void ftdispi_stream_finish(struct ftdispi_context *fsc) {
  if (!fsc || fsc->stream_draining) return;
  fsc->stream_draining = 1;
  clock_gettime(CLOCK_MONOTONIC, &fsc->stream_drain_until);
  fsc->stream_drain_until.tv_sec++;
}

__dll int ftdispi_stream_read_some(struct ftdispi_context *fsc, void *rbuf,
                                uint16_t capacity, uint8_t gpo) {
  if (!fsc || !rbuf || !capacity || !fsc->mem) return FTDISPI_ERROR_CTX;
  struct timespec start, end;
  clock_gettime(CLOCK_MONOTONIC, &start);
  if (fsc->stream_chunk) {
    if (gpo != fsc->stream_gpo) return FTDISPI_ERROR_CMD;
    if (fsc->stream_returned.tv_sec || fsc->stream_returned.tv_nsec) {
      uint64_t gap = stream_ns(start) - stream_ns(fsc->stream_returned);
      if (gap > fsc->stream_gap_ns) fsc->stream_gap_ns = gap;
    }
  } else {
    if (fsc->fc.readbuffer_remaining) { fsc->stream_error = FTDISPI_ERROR_LIB; return fsc->stream_error; }
    fsc->stream_chunk = capacity; fsc->stream_gpo = gpo;
    fsc->stream_progress = start;
  }
  fsc->stream_calls++;
  if (fsc->stream_error && !fsc->fc.readbuffer_remaining) return fsc->stream_error;
  if (stream_refill(fsc) < 0) return fsc->stream_error;
  if (!fsc->stream_pending) return fsc->stream_error;
  int want = capacity;
  if ((uint32_t)want > fsc->stream_pending) want = fsc->stream_pending;
  // Never start another USB operation past the fixed drain deadline. Buffered
  // bytes already on the host can still be delivered without waiting for USB.
  int64_t deadline = stream_ns(fsc->stream_progress) + 1000000000LL;
  if (fsc->stream_draining && stream_ns(fsc->stream_drain_until) < deadline)
    deadline = stream_ns(fsc->stream_drain_until);
  struct timespec before_read;
  clock_gettime(CLOCK_MONOTONIC, &before_read);
  int64_t remaining_ns = deadline - stream_ns(before_read);
  if (remaining_ns <= 0) {
    if (!fsc->stream_error && fsc->stream_pending > fsc->fc.readbuffer_remaining) fsc->stream_error = FTDISPI_ERROR_TO;
    if (!fsc->fc.readbuffer_remaining) return fsc->stream_error;
  }
  if (remaining_ns < 1000000 && !fsc->fc.readbuffer_remaining) {
    // libusb timeout=0 means infinite. Do not round a final sub-ms budget up.
    if (!fsc->stream_error) fsc->stream_error = FTDISPI_ERROR_TO;
    return fsc->stream_error;
  }
  int saved_timeout = fsc->fc.usb_read_timeout;
  if (remaining_ns > 0) {
    int remaining_ms = (int)(remaining_ns / 1000000);
    if (remaining_ms < 1) remaining_ms = 1;
    if (saved_timeout <= 0 || saved_timeout > remaining_ms) fsc->fc.usb_read_timeout = remaining_ms;
  }
  unsigned buffered = fsc->fc.readbuffer_remaining;
  int usb_error = 0;
  struct timespec usb_start;
  clock_gettime(CLOCK_MONOTONIC, &usb_start);
  int n = ftdispi_read_usb_partial(&fsc->fc, rbuf, want, &usb_error);
  fsc->fc.usb_read_timeout = saved_timeout;
  clock_gettime(CLOCK_MONOTONIC, &end);
  if (!buffered) {
    fsc->stream_usb_calls++;
    fsc->stream_usb_read_ns += stream_ns(end) - stream_ns(usb_start);
    if (n >= 0) fsc->stream_usb_payload_bytes += n + fsc->fc.readbuffer_remaining;
  }
  if (n < 0 || n > want) { fsc->stream_error = FTDISPI_ERROR_LIB; return fsc->stream_error; }
  fsc->stream_pending -= n; fsc->stream_bytes += n;
  // libusb TIMEOUT=-7 and INTERRUPTED=-10 are resumable, including valid data.
  if (usb_error == -7) fsc->stream_timeouts++;
  if (usb_error == -10) fsc->stream_interrupts++;
  if (usb_error < 0 && usb_error != -7 && usb_error != -10) fsc->stream_error = FTDISPI_ERROR_LIB;
  if (fsc->fc.readbuffer_remaining > fsc->stream_pending) fsc->stream_error = FTDISPI_ERROR_LIB;
  if (n) fsc->stream_progress = end;
  else {
    fsc->stream_idle_reads++;
    if (!fsc->stream_error && stream_ns(end)-stream_ns(fsc->stream_progress) >= 1000000000LL)
      fsc->stream_error = FTDISPI_ERROR_TO;
  }
  if (!fsc->stream_error && fsc->stream_draining && stream_ns(end) >= stream_ns(fsc->stream_drain_until) && fsc->stream_pending > fsc->fc.readbuffer_remaining)
    fsc->stream_error = FTDISPI_ERROR_TO;
  stream_refill(fsc);
  clock_gettime(CLOCK_MONOTONIC, &end);
  fsc->stream_returned = end;
  fsc->stream_read_ns += stream_ns(end) - stream_ns(start);
  // Deliver a valid prefix before reporting a sticky fatal error on next call.
  if (n) return n;
  return fsc->stream_error;
}

__dll int ftdispi_cs_deassert(struct ftdispi_context *fsc)
{
  if (!fsc) return FTDISPI_ERROR_CTX;
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
  uint8_t buf[3] = { SET_BITS_LOW, 0, BIT_DIR };
  buf[1] = fsc->bitini; // (CS High 포함된 기본 상태)
  FTDI_CHECK(spi_write_exact(fsc, buf, 3), "CS HIGH", fsc->fc);
  return FTDISPI_ERROR_NONE;
}



__dll int ftdispi_write_read(struct ftdispi_context *fsc,
			     const void *wbuf,
			     uint16_t wcount,
			     void *rbuf, uint16_t rcount, uint8_t gpo)
{
	int i, n, r;

	ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
	ASSERT_CHECK(!((wbuf && wcount) || (rbuf && rcount)),
		     "NO CMD", FTDISPI_ERROR_CMD);
	n = wcount + (rcount ? 9 : 6);
	ASSERT_CHECK(ftdispi_realloc(fsc, n), "REALLOC", FTDISPI_ERROR_MEM);

	i = 0;
	fsc->mem[i++] = SET_BITS_LOW;
	fsc->mem[i++] = ((0x0F & (fsc->bitini ^ BIT_P_CS)) | (BIT_P_GX & gpo));
	fsc->mem[i++] = BIT_DIR;

	if (wcount && wbuf) {
		fsc->mem[i++] = fsc->wr_cmd;
		fsc->mem[i++] = (wcount - 1) & 0xFF;
		fsc->mem[i++] = ((wcount - 1) >> 8) & 0xFF;
		memcpy(fsc->mem + i, wbuf, wcount);
		i += wcount;
	}
	if (rcount && rbuf) {
		fsc->mem[i++] = fsc->rd_cmd;
		fsc->mem[i++] = (rcount - 1) & 0xFF;
		fsc->mem[i++] = ((rcount - 1) >> 8) & 0xFF;
		FTDI_CHECK(spi_write_exact(fsc, fsc->mem, i), "[WR]RD",
			   fsc->fc);
		for (n = 0; n < rcount;) {
			FTDI_CHECK(r =
				   ftdi_read_data(&fsc->fc, rbuf + n,
						  rcount - n), "RD", fsc->fc);
			n += r;
		}
		i = 0;
	}
	fsc->mem[i++] = SET_BITS_LOW;
	fsc->mem[i++] = fsc->bitini;
	fsc->mem[i++] = BIT_DIR;
	FTDI_CHECK(spi_write_exact(fsc, fsc->mem, i), "WR", fsc->fc);

	return ftdispi_wait(fsc, BIT_P_CS, fsc->bitini, RETRY_MAX);
}

__dll int ftdispi_write(struct ftdispi_context *fsc,
			const void *buf, uint16_t count, uint8_t gpo)
{
	return ftdispi_write_read(fsc, buf, count, 0, 0, gpo);
}

__dll int ftdispi_read(struct ftdispi_context *fsc,
		       void *buf, uint16_t count, uint8_t gpo)
{
	return ftdispi_write_read(fsc, 0, 0, buf, count, gpo);
}

__dll int ftdispi_setgpo(struct ftdispi_context *fsc, uint8_t gpo)
{
  if (!fsc) return FTDISPI_ERROR_CTX;
  if (fsc->stream_chunk || fsc->stream_error) return FTDISPI_ERROR_CMD;
	uint8_t buf[3];

	ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
	if ((fsc->bitini & BIT_P_GX) != (gpo & BIT_P_GX)) {
		fsc->bitini = ((fsc->bitini & BIT_P_GX) | (gpo & BIT_P_GX));
	}
	buf[0] = SET_BITS_LOW;
	buf[1] = fsc->bitini;
	buf[2] = BIT_DIR;
	FTDI_CHECK(spi_write_exact(fsc, buf, 3), "SETGPO", fsc->fc);
	return ftdispi_wait(fsc, BIT_P_GX, fsc->bitini, RETRY_MAX);
}

__dll int ftdispi_close(struct ftdispi_context *fsc, int close_ftdi)
{
	ASSERT_CHECK(!fsc, "CTX NOT INITIALIZED", FTDISPI_ERROR_CTX);
  int result = fsc->stream_error ? fsc->stream_error : FTDISPI_ERROR_NONE;
  if (fsc->stream_chunk || fsc->stream_error) {
    if (fsc->stream_pending) {
      fprintf(stderr, "SPI: aborting undrained response=%u bytes\n", fsc->stream_pending);
      if (!result) result = FTDISPI_ERROR_TO;
    }
    // Abort queued clocks before purging their USB responses. Re-enter MPSSE
    // with idle GPIOs so CS is high, not left asserted behind an unread command.
    uint8_t idle[] = {SET_BITS_LOW, fsc->bitini, BIT_DIR};
    if (ftdi_set_bitmode(&fsc->fc, 0, BITMODE_RESET) < 0 ||
        ftdi_tcioflush(&fsc->fc) < 0 ||
        ftdi_set_bitmode(&fsc->fc, 0, BITMODE_MPSSE) < 0 ||
        ftdi_write_data(&fsc->fc, idle, sizeof(idle)) != (int)sizeof(idle)) {
      fsc->stream_error = FTDISPI_ERROR_LIB;
      fprintf(stderr, "SPI: could not restore idle GPIO on close\n"); result = FTDISPI_ERROR_LIB;
    }
  }
	if (fsc->mem) {
		free(fsc->mem);
		fsc->mem = 0;
		fsc->memsize = 0;
	}
	if (close_ftdi) {
		ftdi_usb_close(&fsc->fc);
		ftdi_deinit(&fsc->fc);
	}
	return result;
}

static int ftdispi_realloc(struct ftdispi_context *fsc, size_t size)
{
	uint8_t *p;

	if (fsc->memsize < size) {
		if (!(p = realloc(fsc->mem, size))) {
			return FTDISPI_ERROR_MEM;
		}
		fsc->mem = p;
		fsc->memsize = size;
	}
	return FTDISPI_ERROR_NONE;
}

static int ftdispi_wait(struct ftdispi_context *fsc, uint8_t mask,
			uint8_t value, int maxtry)
{
  // One response per query. Status-only USB packets must not accumulate queries.
  struct timespec start, now;
  clock_gettime(CLOCK_MONOTONIC, &start);
  int saved_timeout = fsc->fc.usb_read_timeout;
  int saved_write_timeout = fsc->fc.usb_write_timeout;
  int result = FTDISPI_ERROR_TO;
  const char *reason = "deadline_no_response";
  for (int query = 0; query < maxtry; ++query) {
    clock_gettime(CLOCK_MONOTONIC, &now);
    int64_t write_left = 300000000LL - ((int64_t)(now.tv_sec-start.tv_sec)*1000000000LL + now.tv_nsec-start.tv_nsec);
    if (write_left <= 0) break;
    int write_timeout = (int)(write_left / 1000000);
    if (write_timeout < 1) write_timeout = 1;
    fsc->fc.usb_write_timeout = saved_write_timeout > 0 && saved_write_timeout < write_timeout ? saved_write_timeout : write_timeout;
    uint8_t command[] = {GET_BITS_LOW, 0x87};  // SEND_IMMEDIATE
    if (spi_write_exact(fsc, command, sizeof(command)) != (int)sizeof(command)) {
      reason = "short_or_failed_command_write"; result = FTDISPI_ERROR_LIB; break;
    }
    reason = "deadline_no_response";
    uint8_t response = 0;
    int received = 0;
    while (!received) {
      clock_gettime(CLOCK_MONOTONIC, &now);
      int64_t left = 300000000LL - ((int64_t)(now.tv_sec-start.tv_sec)*1000000000LL + now.tv_nsec-start.tv_nsec);
      if (left <= 0) goto done;
      int timeout = (int)(left / 1000000);
      if (timeout < 1) timeout = 1;
      fsc->fc.usb_read_timeout = saved_timeout > 0 && saved_timeout < timeout ? saved_timeout : timeout;
      errno = 0;
      received = ftdi_read_data(&fsc->fc, &response, 1);
      if (received == -7 || received == -10) received = 0; // libusb timeout/interrupted
      if (received < 0) {
        fprintf(stderr, "native stage=gpio_read failed rc=%d errno=%d libftdi=%s\n",
                received, errno, ftdi_get_error_string(&fsc->fc));
        reason = "fatal_read"; result = FTDISPI_ERROR_LIB; goto done;
      }
      if (!received) usleep(RETRY_TIME);
    }
    if ((response & mask) == (value & mask)) { reason = "matched"; result = 0; break; }
    reason = "mask_mismatch";
    fprintf(stderr, "native stage=gpio_compare observed=0x%02x mask=0x%02x expected=0x%02x\n", response, mask, value);
    clock_gettime(CLOCK_MONOTONIC, &now);
    if ((int64_t)(now.tv_sec-start.tv_sec)*1000000000LL + now.tv_nsec-start.tv_nsec >= 300000000LL) break;
  }
done:
  fsc->fc.usb_read_timeout = saved_timeout;
  fsc->fc.usb_write_timeout = saved_write_timeout;
  if (result) fsc->stream_error = result;
  int saved_errno = errno;
  fprintf(stderr, "native stage=gpio_response reason=%s rc=%d errno=%d strerror=%s libftdi=%s\n",
          reason, result, saved_errno, strerror(saved_errno), result ? ftdi_get_error_string(&fsc->fc) : "none");
  errno = saved_errno;
  return result;
}
