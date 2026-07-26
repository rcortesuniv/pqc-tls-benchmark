CC ?= cc
OPENSSL_PREFIX ?= /opt/openssl-3.5.7
OPENSSL_LIBDIR ?= $(firstword $(wildcard $(OPENSSL_PREFIX)/lib64 $(OPENSSL_PREFIX)/lib))
CPPFLAGS += -I$(OPENSSL_PREFIX)/include
CFLAGS ?= -O2 -g -std=c11 -Wall -Wextra -Wpedantic
LDFLAGS += -L$(OPENSSL_LIBDIR)
LDLIBS += -lssl -lcrypto
RPATH = -Wl,-rpath,$(OPENSSL_LIBDIR)

ifeq ($(shell uname -s),Linux)
CFLAGS += -fstack-protector-strong -fPIE -D_FORTIFY_SOURCE=3
LDFLAGS += -Wl,-z,relro,-z,now -pie
endif

.PHONY: all clean test

all: build/tls_bench_client build/pqc_microbench

build:
	mkdir -p build

build/tls_bench_client: src/tls_bench_client.c | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDFLAGS) $(RPATH) $(LDLIBS)

build/pqc_microbench: src/pqc_microbench.c | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDFLAGS) $(RPATH) $(LDLIBS)

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build
