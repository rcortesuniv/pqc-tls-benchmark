FROM ubuntu:24.04 AS builder

ARG OPENSSL_VERSION=3.5.7
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/openssl
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      --output openssl.tar.gz \
      "https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VERSION}/openssl-${OPENSSL_VERSION}.tar.gz" \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output openssl.tar.gz.sha256 \
      "https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VERSION}/openssl-${OPENSSL_VERSION}.tar.gz.sha256" \
    && sha256sum --check openssl.tar.gz.sha256 \
    && tar --extract --file openssl.tar.gz --strip-components=1 \
    && ./Configure linux-x86_64 shared --prefix=/opt/openssl --openssldir=/opt/openssl/ssl \
    && make -j"$(nproc)" \
    && make test \
    && make install_sw install_ssldirs

WORKDIR /src
COPY src/tls_bench_client.c /src/
RUN cc -O2 -g -std=c11 -Wall -Wextra -Wpedantic \
      -fstack-protector-strong -fPIE -D_FORTIFY_SOURCE=3 \
      -I/opt/openssl/include tls_bench_client.c \
      -L/opt/openssl/lib64 -L/opt/openssl/lib \
      -Wl,-rpath,/opt/openssl/lib64 -Wl,-rpath,/opt/openssl/lib \
      -Wl,-z,relro,-z,now -pie \
      -lssl -lcrypto -o /usr/local/bin/tls_bench_client

FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates iproute2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/openssl /opt/openssl
COPY --from=builder /usr/local/bin/tls_bench_client /usr/local/bin/tls_bench_client
ENV PATH="/opt/openssl/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/openssl/lib64:/opt/openssl/lib"
ENTRYPOINT ["/usr/local/bin/tls_bench_client"]
