// Exercise the real reader, ftdispi_open and setmode against deterministic USB mocks.
#define main pipeline_regression_main
#include "test_spi_pipeline.c"
#undef main
#include <errno.h>

static void reset_initialization(void) {
  reset_mock();device_count=1;open_result=0;closed=deinitialized=0;
  gpio_empty=0;gpio_value=8;gpio_error=gpio_reads=gpio_queries=0;
  fail_operation=operation_count=0;init_result=open_errno=cleanup_errno=gpio_error_once=0;
  unsetenv("FLEXRAY_FTDI_PRODUCT");unsetenv("FLEXRAY_FTDI_SERIAL");
}
int main(void) {
  struct flexray_reader r;
  reset_initialization();gpio_empty=2;
  assert(flexray_reader_open(&r,NULL,false)==0);
  assert(r.type==FT_SPI && selected_product==0x6011 && r.spi.actual_clock_hz==7500000);
  assert(gpio_reads==3 && gpio_queries==1 && modes==2);
  unsigned char data[32];assert(flexray_reader_read(&r,data,sizeof(data))>0 && r.received_data);
  flexray_reader_finish(&r);while(flexray_reader_pending(&r))assert(flexray_reader_read(&r,data,sizeof(data))>0);
  assert(flexray_reader_close(&r)==0 && closed==1 && deinitialized==1);
  assert(!r.initialized && !r.spi_owned);

  reset_initialization();device_count=0;
  assert(flexray_reader_open(&r,NULL,false)<0 && errno==ENODEV && deinitialized==1 && operation_count==0);
  reset_initialization();open_result=-5;
  assert(flexray_reader_open(&r,NULL,false)<0 && deinitialized==1 && operation_count==1);
  reset_initialization();device_count=2;
  assert(flexray_reader_open(&r,NULL,false)<0 && errno==EBUSY && operation_count==0);
  reset_initialization();device_count=2;setenv("FLEXRAY_FTDI_SERIAL","serial2",1);
  assert(flexray_reader_open(&r,NULL,false)==0);assert(flexray_reader_close(&r)==0);
  reset_initialization();setenv("FLEXRAY_FTDI_SERIAL","missing",1);
  assert(flexray_reader_open(&r,NULL,false)<0 && errno==ENODEV);
  reset_initialization();setenv("FLEXRAY_FTDI_PRODUCT","6010",1);
  assert(flexray_reader_open(&r,NULL,false)==0 && r.type==FT_FASTSERIAL && selected_product==0x6010);
  assert(flexray_reader_close(&r)==0 && deinitialized==1);

  // Every actual setup operation, including copied-context ownership failures.
  for(int fail=1;fail<=9;fail++) {
    reset_initialization();fail_operation=fail;
    assert(flexray_reader_open(&r,NULL,false)<0);
    assert(deinitialized==1 && closed==1 && !r.spi_owned && !r.initialized);
  }
  reset_initialization();init_result=-2;
  assert(flexray_reader_open(&r,NULL,false)<0 && deinitialized==1 && closed==0);
  for(int code=-4;code>=-8;code--) {
    reset_initialization();open_result=code;open_errno=EBUSY;cleanup_errno=EINVAL;
    assert(flexray_reader_open(&r,NULL,false)<0 && errno==EBUSY && deinitialized==1 && closed==1);
  }
  reset_initialization();gpio_error_once=-7;
  assert(flexray_reader_open(&r,NULL,false)==0 && gpio_queries==1 && gpio_reads==2);
  assert(flexray_reader_close(&r)==0);
  for(int short_command=1;short_command<=5;short_command++) {
    reset_initialization();short_on_write=short_command;
    assert(flexray_reader_open(&r,NULL,false)<0 && deinitialized==1 && closed==1);
  }
  reset_initialization();short_on_write=3;
  assert(flexray_reader_open(&r,NULL,false)<0 && deinitialized==1 && gpio_queries==0);
  reset_initialization();gpio_error=-4;
  assert(flexray_reader_open(&r,NULL,false)<0 && gpio_reads==1 && gpio_queries==1 && deinitialized==1);
  reset_initialization();gpio_empty=-1;
  struct timespec before,after;clock_gettime(CLOCK_MONOTONIC,&before);
  assert(flexray_reader_open(&r,NULL,false)<0 && gpio_queries==1 && deinitialized==1);
  clock_gettime(CLOCK_MONOTONIC,&after);
  double elapsed=after.tv_sec-before.tv_sec+(after.tv_nsec-before.tv_nsec)/1e9;
  assert(elapsed>=0.29 && elapsed<0.7);
  reset_initialization();gpio_value=0;
  assert(flexray_reader_open(&r,NULL,false)<0 && gpio_queries==10 && gpio_reads==10 && deinitialized==1);
  puts("TEST_SUMMARY reader_initialization failures=0");return 0;
}
