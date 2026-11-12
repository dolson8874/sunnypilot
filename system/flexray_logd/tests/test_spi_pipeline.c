#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ftdispi.h"
#include "flexray_reader.h"
#include "mocks/libusb.h"

static int device_count, open_result, selected_product, closed, deinitialized;
static int init_result, open_errno, cleanup_errno, gpio_error_once;
static enum ftdi_chip_type detected_type=TYPE_4232H;
static unsigned char mpsse_initial[4];
static int mpsse_initial_size;
static int gpio_empty = -1, gpio_value = 8, gpio_error, gpio_reads, gpio_queries;
static int fail_operation, operation_count;
static unsigned writes, bulk_calls, commands, outstanding, wire_position;
static int short_on_write, next_error, payload_limit = -1, modes, purges;
static unsigned char last_write[32];
static int last_size;
static unsigned last_timeout;
static volatile sig_atomic_t *stop_on_bulk;
static void reset_mock(void) {
  writes=bulk_calls=commands=outstanding=wire_position=0;
  short_on_write=next_error=modes=purges=0;payload_limit=-1;stop_on_bulk=NULL;last_timeout=0;
}
static void init(struct ftdispi_context *x) {
  memset(x,0,sizeof(*x));reset_mock();
  x->mem=malloc(64);x->memsize=64;x->rd_cmd=MPSSE_DO_READ;x->bitini=8;
  x->fc.type=TYPE_4232H;x->fc.usb_dev=(struct libusb_device_handle *)1;
  x->fc.readbuffer=malloc(64);x->fc.readbuffer_chunksize=32;x->fc.max_packet_size=8;
}
static void release(struct ftdispi_context *x) { free(x->mem);free(x->fc.readbuffer); }
int ftdi_write_data(struct ftdi_context *x, const unsigned char *data, int size) {
  (void)x;writes++;last_size=size;memcpy(last_write,data,size<32?size:32);
  if (!mpsse_initial_size && ((size==4 && data[0]==0x8a && data[1]==0x97) || (size==1 && data[0]==0x85))) {
    memcpy(mpsse_initial,data,size);mpsse_initial_size=size;
  }
  if (short_on_write==(int)writes) return size-1;
  if(size==2 && data[0]==GET_BITS_LOW){assert(data[1]==0x87);gpio_queries++;}
  if (size==6 && data[0]==SET_BITS_LOW && data[3]==MPSSE_DO_READ) {
    outstanding+=1+data[4]+((unsigned)data[5]<<8);commands++;
  }
  return size;
}
const char *libusb_error_name(int error) { (void)error;return "MOCK_USB_ERROR"; }
int libusb_bulk_transfer(struct libusb_device_handle *h, unsigned char ep,
                        unsigned char *data, int size, int *actual, unsigned timeout) {
  (void)h;(void)ep;last_timeout=timeout;bulk_calls++;
  if (stop_on_bulk) *stop_on_bulk=1;
  unsigned limit=outstanding;
  if (payload_limit>=0 && limit>(unsigned)payload_limit) limit=payload_limit;
  unsigned count=0,payload=0;
  while (count+2<=(unsigned)size && payload<limit) {
    data[count++]=0x01;data[count++]=0x60;
    for (int b=0;b<6 && count<(unsigned)size && payload<limit;b++) {
      data[count++]=(unsigned char)wire_position++;payload++;
    }
  }
  if (!count && size>=2) { data[0]=0x01;data[1]=0x60;count=2; }
  outstanding-=payload;*actual=count;
  int error=next_error;next_error=0;payload_limit=-1;return error;
}
static int operation(void) { return ++operation_count == fail_operation ? -9 : 0; }
int ftdi_init(struct ftdi_context *x) {
  memset(x,0,sizeof(*x)); x->type=detected_type;
  x->readbuffer=malloc(64);x->readbuffer_chunksize=32;x->max_packet_size=8;
  return init_result;
}
int ftdi_usb_find_all(struct ftdi_context *x, struct ftdi_device_list **list,int v,int p) {
  (void)x;assert(v==0x0403);selected_product=p;*list=NULL;
  for(int i=device_count;i>0;--i) {
    struct ftdi_device_list *item=malloc(sizeof(*item));
    item->dev=(struct libusb_device *)(uintptr_t)i;item->next=*list;*list=item;
  }
  return device_count;
}
void ftdi_list_free(struct ftdi_device_list **list) {
  while(*list) {struct ftdi_device_list *item=*list;*list=item->next;free(item);}
}
int ftdi_usb_get_strings(struct ftdi_context *x,struct libusb_device *d,char *m,int ml,char *desc,int dl,char *serial,int sl) {
  (void)x;(void)m;(void)ml;(void)desc;(void)dl;snprintf(serial,sl,"serial%u",(unsigned)(uintptr_t)d);return 0;
}
int ftdi_usb_open_dev(struct ftdi_context *x,struct libusb_device *d) {
  (void)d;errno=open_errno;if(!open_result)x->usb_dev=(struct libusb_device_handle *)1;return open_result;
}
int libusb_get_device_descriptor(struct libusb_device *d,struct libusb_device_descriptor *desc) {
  (void)d;desc->idVendor=0x0403;desc->idProduct=0x6011;desc->bcdDevice=0x1234;desc->bNumConfigurations=1;return 0;
}
int libusb_get_device_speed(struct libusb_device *d) { (void)d;return 3; }
unsigned char libusb_get_bus_number(struct libusb_device *d) {(void)d;return 2;}
unsigned char libusb_get_device_address(struct libusb_device *d) {(void)d;return 3;}
int libusb_get_port_numbers(struct libusb_device *d,unsigned char *p,int n) {(void)d;assert(n>=2);p[0]=1;p[1]=4;return 2;}
const char *ftdi_get_error_string(struct ftdi_context *x) { (void)x;return "mock"; }
int ftdi_read_data(struct ftdi_context *x,unsigned char *p,int n) {
  (void)x;assert(n==1);gpio_reads++;
  if(gpio_error_once){int result=gpio_error_once;gpio_error_once=0;return result;}
  if(gpio_error)return gpio_error;
  if(gpio_empty<0)return 0;
  if(gpio_empty>0){gpio_empty--;return 0;}
  *p=gpio_value;return 1;
}
int ftdi_set_interface(struct ftdi_context *x,enum ftdi_interface n) { assert(n==INTERFACE_B);x->interface=1;x->index=2;return operation(); }
int ftdi_usb_reset(struct ftdi_context *x) { (void)x;return operation(); }
int ftdi_set_latency_timer(struct ftdi_context *x,unsigned char n) { (void)x;(void)n;return operation(); }
int ftdi_set_bitmode(struct ftdi_context *x,unsigned char a,unsigned char b) { (void)x;(void)a;(void)b;modes++;return operation(); }
int ftdi_write_data_set_chunksize(struct ftdi_context *x,unsigned n) { (void)x;(void)n;return operation(); }
int ftdi_read_data_set_chunksize(struct ftdi_context *x,unsigned n) { (void)x;(void)n;return operation(); }
int ftdi_tcioflush(struct ftdi_context *x) { (void)x;purges++;return operation(); }
int ftdi_usb_close(struct ftdi_context *x) { x->usb_dev=NULL;closed++;errno=cleanup_errno;return 0; }
void ftdi_deinit(struct ftdi_context *x) { free(x->readbuffer);x->readbuffer=NULL;deinitialized++; }
static void bytes(const unsigned char *p,int n,unsigned *expected) {
  for (int i=0;i<n;i++) assert(p[i]==(unsigned char)(*expected)++);
}
int main(void) {
  struct ftdispi_context x;unsigned char data[128];unsigned expected;int n,error;
  init(&x);
  unsigned speeds[]={7500000,10000000,6000000,1000000,3750000,100,30000000,7000001,5999999,1234567};
  for (unsigned i=0;i<sizeof(speeds)/sizeof(speeds[0]);i++) {
    assert(ftdispi_setclock(&x,speeds[i])==0);
    assert(last_size==4 && last_write[0]==(speeds[i]>6000000?0x8a:0x8b));
    unsigned base=last_write[0]==0x8a?30000000:6000000;
    unsigned actual=base/(1+last_write[2]+((unsigned)last_write[3]<<8));
    assert(actual==x.actual_clock_hz && actual<=speeds[i]);
    assert((uint64_t)base <= (uint64_t)speeds[i] * (1+last_write[2]+((unsigned)last_write[3]<<8)));
  }
  short_on_write=writes+1;assert(ftdispi_setclock(&x,7500000)==FTDISPI_ERROR_LIB);
  assert(ftdispi_setclock(&x,1000000)==FTDISPI_ERROR_CMD);release(&x);
  init(&x);x.fc.type=TYPE_2232C;assert(ftdispi_setclock(&x,7500000)==FTDISPI_ERROR_CLK);
  assert(ftdispi_setclock(&x,1000000)==0 && last_size==3);release(&x);
  puts("SPI clock: H-class divide transitions, rounding, legacy limit, short write OK");

  init(&x);outstanding=100;expected=0;
  assert(ftdispi_read_usb_partial(&x.fc,data,4,&error)==4 && error==0);bytes(data,4,&expected);
  unsigned before=bulk_calls;
  n=ftdispi_read_usb_partial(&x.fc,data,128,&error);assert(n==20 && bulk_calls==before);bytes(data,n,&expected);
  next_error=LIBUSB_ERROR_TIMEOUT;payload_limit=3;
  n=ftdispi_read_usb_partial(&x.fc,data,128,&error);assert(n==3 && error==LIBUSB_ERROR_TIMEOUT);bytes(data,n,&expected);
  next_error=LIBUSB_ERROR_NO_DEVICE;payload_limit=3;
  n=ftdispi_read_usb_partial(&x.fc,data,128,&error);assert(n==3 && error==LIBUSB_ERROR_NO_DEVICE);bytes(data,n,&expected);
  release(&x);puts("SPI USB: status stripping, leftovers, partial timeout/fatal data OK");

  init(&x);expected=0;
  for (int i=0;i<200;i++) {
    n=ftdispi_stream_read_some(&x,data,16,0);assert(n>0);bytes(data,n,&expected);
    assert(x.stream_pending<=32 && commands==x.stream_commands);
    assert(outstanding+x.fc.readbuffer_remaining==x.stream_pending);
    assert(x.stream_usb_payload_bytes==wire_position && x.stream_bytes==expected);
  }
  assert(ftdispi_setclock(&x,7500000)==FTDISPI_ERROR_CMD);
  assert(ftdispi_cs_deassert(&x)==FTDISPI_ERROR_CMD);
  before=writes;
  assert(ftdispi_setgpo(&x,1)==FTDISPI_ERROR_CMD);
  assert(ftdispi_setmode(&x,1,0,0,0,0,0)==FTDISPI_ERROR_CMD);
  assert(ftdispi_setloopback(&x,1)==FTDISPI_ERROR_CMD);
  assert(ftdispi_read_stream(&x,data,16,0)==FTDISPI_ERROR_CMD);
  assert(ftdispi_write_read(&x,data,1,NULL,0,0)==FTDISPI_ERROR_CMD);
  assert(writes==before);
  before=commands;ftdispi_stream_finish(&x);
  while (x.stream_pending) { n=ftdispi_stream_read_some(&x,data,16,0);assert(n>0);bytes(data,n,&expected); }
  assert(ftdispi_stream_read_some(&x,data,16,0)==0 && commands==before && outstanding==0);
  assert(x.stream_bytes==expected);
  assert(ftdispi_close(&x,1)==0 && modes==2 && purges==1 && last_size==3 && last_write[1]==8);
  release(&x);puts("SPI pipeline: bounded window, exact order, no duplicate commands, finish/idle GPIO OK");

  init(&x);next_error=LIBUSB_ERROR_TIMEOUT;payload_limit=0;
  assert(ftdispi_stream_read_some(&x,data,16,0)==0 && commands==2);
  expected=0;n=ftdispi_stream_read_some(&x,data,16,0);assert(n>0);bytes(data,n,&expected);
  release(&x);
  init(&x);next_error=LIBUSB_ERROR_TIMEOUT;payload_limit=0;
  assert(ftdispi_stream_read_some(&x,data,16,0)==0);
  x.stream_progress.tv_sec-=2;next_error=LIBUSB_ERROR_TIMEOUT;payload_limit=0;
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_TO && commands==2);release(&x);
  init(&x);short_on_write=1;
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB);
  before=writes;assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && writes==before);release(&x);
  puts("SPI recovery: soft timeout resumes, no-progress bound, short command is not retried OK");

  init(&x);short_on_write=3;expected=0;
  n=ftdispi_stream_read_some(&x,data,16,0);assert(n==16);bytes(data,n,&expected);
  n=ftdispi_stream_read_some(&x,data,16,0);assert(n==8);bytes(data,n,&expected);
  before=writes;assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && writes==before);release(&x);
  init(&x);next_error=LIBUSB_ERROR_NO_DEVICE;payload_limit=3;
  n=ftdispi_stream_read_some(&x,data,16,0);assert(n==3);expected=0;bytes(data,n,&expected);
  before=writes;assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && writes==before);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,16,0)>0);
  ftdispi_stream_finish(&x);x.stream_drain_until.tv_sec-=2;before=commands;
  while ((n=ftdispi_stream_read_some(&x,data,16,0))>0) {}
  assert(n==FTDISPI_ERROR_TO && commands==before);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,65535,0)>0 && x.stream_pending<=131070);release(&x);
  puts("SPI faults: prefix preserved before fatal error, fixed drain bound, 16-bit maximum OK");
  struct flexray_reader reader={0};reader.type=FT_SPI;reader.spi_owned=true;
  init(&reader.spi);payload_limit=0;next_error=LIBUSB_ERROR_TIMEOUT;
  assert(flexray_reader_read(&reader,data,16)==0 && flexray_reader_pending(&reader));
  payload_limit=3;next_error=LIBUSB_ERROR_TIMEOUT;
  assert(flexray_reader_read(&reader,data,16)==3);
  before=commands;flexray_reader_finish(&reader);
  while (flexray_reader_pending(&reader)) assert(flexray_reader_read(&reader,data,16)>0);
  assert(commands==before);flexray_reader_close(&reader);release(&reader.spi);
  puts("SPI reader: partial return, soft idle, bounded pending drain integration OK");
  init(&x);expected=0;payload_limit=3;next_error=LIBUSB_ERROR_INTERRUPTED;
  n=ftdispi_stream_read_some(&x,data,16,0);assert(n==3 && x.stream_interrupts==1);bytes(data,n,&expected);
  n=ftdispi_stream_read_some(&x,data,16,0);assert(n>0);bytes(data,n,&expected);release(&x);
  init(&x);ftdispi_stream_finish(&x);assert(ftdispi_stream_read_some(&x,data,16,0)==0 && commands==0);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,16,0)==16);
  assert(x.fc.readbuffer_remaining==8);
  ftdispi_stream_finish(&x);x.stream_drain_until.tv_sec-=2;before=bulk_calls;
  assert(ftdispi_stream_read_some(&x,data,16,0)==8); // Buffered prefix only, no USB past deadline.
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_TO && bulk_calls==before);
  assert(ftdispi_close(&x,1)==FTDISPI_ERROR_TO);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,16,0)==16);
  assert(ftdispi_stream_read_some(&x,data,16,0)==8); // Empty local remainder.
  ftdispi_stream_finish(&x);
  clock_gettime(CLOCK_MONOTONIC,&x.stream_drain_until);
  x.stream_drain_until.tv_nsec+=20000000;
  if (x.stream_drain_until.tv_nsec>=1000000000) {x.stream_drain_until.tv_nsec-=1000000000;x.stream_drain_until.tv_sec++;}
  assert(ftdispi_stream_read_some(&x,data,16,0)>0 && last_timeout>0 && last_timeout<=20);release(&x);
  init(&x);volatile sig_atomic_t stop=0;x.stream_stop=&stop;stop_on_bulk=&stop;
  assert(ftdispi_stream_read_some(&x,data,16,0)>0);
  assert(x.stream_draining && commands==2);before=commands;
  while(x.stream_pending) assert(ftdispi_stream_read_some(&x,data,16,0)>0);
  assert(commands==before);release(&x);
  init(&x);short_on_write=1;
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && x.stream_pending==0);
  assert(ftdispi_close(&x,1)==FTDISPI_ERROR_LIB);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,16,0)==16);
  ftdispi_stream_finish(&x);
  assert(ftdispi_stream_read_some(&x,data,16,0)==8);
  assert(ftdispi_stream_read_some(&x,data,4,0)==4);
  assert(x.stream_pending==x.fc.readbuffer_remaining && outstanding==0);
  x.stream_drain_until.tv_sec-=2;before=bulk_calls;
  while(x.stream_pending) assert(ftdispi_stream_read_some(&x,data,16,0)>0);
  assert(bulk_calls==before && ftdispi_close(&x,1)==0);release(&x);
  init(&x);x.fc.readbuffer_remaining=1;
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && writes==0);release(&x);
  init(&x);assert(ftdispi_stream_read_some(&x,data,16,0)==16);
  x.stream_pending=4;x.stream_error=FTDISPI_ERROR_LIB;before=bulk_calls;
  assert(ftdispi_stream_read_some(&x,data,16,0)==4);
  assert(ftdispi_stream_read_some(&x,data,16,0)==FTDISPI_ERROR_LIB && bulk_calls==before);release(&x);
  init(&x);short_on_write=2;
  assert(ftdispi_setmode(&x,1,0,0,0,0,0)==FTDISPI_ERROR_LIB && writes==2);release(&x);
  init(&x);
  assert(ftdispi_setmode(&x,1,0,0,0,0,0)!=0 && writes==2); // Empty GPIO reply is not retried.
  release(&x);
  puts("SPI additional: command isolation, status-free USB counters, interrupted data, stop refill and hard deadlines OK");
  puts("TEST_SUMMARY spi_pipeline failures=0");return 0;
}
