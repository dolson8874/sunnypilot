# glibc의 malloc 검사(해제 후 사용, 이중 free 등 즉시 abort)
export GLIBC_TUNABLES=glibc.malloc.check=3    # (신형 glibc)
export MALLOC_CHECK_=3                        # (구형 호환)

# 새로 할당/해제 메모리에 패턴 채워서 숨은 버그 노출
export MALLOC_PERTURB_=$(($RANDOM % 255 + 1))

