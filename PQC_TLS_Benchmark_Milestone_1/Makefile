CC ?= cc
OPENSSL_PREFIX ?= /opt/openssl-3.5.7
CPPFLAGS += -I$(OPENSSL_PREFIX)/include
CFLAGS ?= -O2 -g -std=c11 -Wall -Wextra -Wpedantic
LDFLAGS += -L$(OPENSSL_PREFIX)/lib64 -L$(OPENSSL_PREFIX)/lib
LDLIBS += -lssl -lcrypto
RPATH = -Wl,-rpath,$(OPENSSL_PREFIX)/lib64 -Wl,-rpath,$(OPENSSL_PREFIX)/lib

.PHONY: all clean test

all: build/tls_bench_client

build:
	mkdir -p build

build/tls_bench_client: src/tls_bench_client.c | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDFLAGS) $(RPATH) $(LDLIBS)

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build

