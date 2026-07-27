#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <netdb.h>
#include <openssl/err.h>
#include <openssl/ssl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <poll.h>
#include <time.h>
#include <unistd.h>

#if OPENSSL_VERSION_NUMBER < 0x30500000L
#error "This benchmark requires OpenSSL 3.5.0 or newer"
#endif

typedef struct {
    uint64_t bytes_read;
    uint64_t bytes_written;
} io_counts;

typedef struct {
    const char *host;
    const char *port;
    const char *server_name;
    const char *ca_file;
    const char *group;
    const char *batch_id;
    const char *cell_id;
    unsigned attempts;
    unsigned warmups;
    unsigned timeout_ms;
} options;

static void usage(const char *program)
{
    fprintf(stderr,
        "Usage: %s --host HOST --port PORT --server-name NAME --ca-file FILE\\n"
        "          --group GROUP --batch-id ID --cell-id ID [options]\\n"
        "Options:\\n"
        "  --attempts N    Recorded handshakes (default: 100)\\n"
        "  --warmups N     Unrecorded warm-up handshakes (default: 20)\\n"
        "  --timeout-ms N  Socket timeout in milliseconds (default: 10000)\\n",
        program);
}

static bool parse_unsigned(const char *text, unsigned *value)
{
    char *end = NULL;
    unsigned long parsed;

    errno = 0;
    parsed = strtoul(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || parsed > UINT32_MAX) {
        return false;
    }
    *value = (unsigned)parsed;
    return true;
}

static bool parse_options(int argc, char **argv, options *opts)
{
    static const struct option long_options[] = {
        {"host", required_argument, NULL, 'h'},
        {"port", required_argument, NULL, 'p'},
        {"server-name", required_argument, NULL, 'n'},
        {"ca-file", required_argument, NULL, 'c'},
        {"group", required_argument, NULL, 'g'},
        {"batch-id", required_argument, NULL, 'b'},
        {"cell-id", required_argument, NULL, 'i'},
        {"attempts", required_argument, NULL, 'a'},
        {"warmups", required_argument, NULL, 'w'},
        {"timeout-ms", required_argument, NULL, 't'},
        {NULL, 0, NULL, 0}
    };
    int option;

    *opts = (options){
        .attempts = 100,
        .warmups = 20,
        .timeout_ms = 10000
    };

    while ((option = getopt_long(argc, argv, "", long_options, NULL)) != -1) {
        switch (option) {
        case 'h': opts->host = optarg; break;
        case 'p': opts->port = optarg; break;
        case 'n': opts->server_name = optarg; break;
        case 'c': opts->ca_file = optarg; break;
        case 'g': opts->group = optarg; break;
        case 'b': opts->batch_id = optarg; break;
        case 'i': opts->cell_id = optarg; break;
        case 'a':
            if (!parse_unsigned(optarg, &opts->attempts)) return false;
            break;
        case 'w':
            if (!parse_unsigned(optarg, &opts->warmups)) return false;
            break;
        case 't':
            if (!parse_unsigned(optarg, &opts->timeout_ms)) return false;
            break;
        default:
            return false;
        }
    }

    return opts->host && opts->port && opts->server_name && opts->ca_file &&
           opts->group && opts->batch_id && opts->cell_id &&
           opts->attempts > 0 && opts->timeout_ms > 0;
}

static uint64_t monotonic_ns(void)
{
    struct timespec timestamp;
    if (clock_gettime(CLOCK_MONOTONIC, &timestamp) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (uint64_t)timestamp.tv_sec * 1000000000ULL +
           (uint64_t)timestamp.tv_nsec;
}

static void utc_timestamp(char buffer[32])
{
    struct timespec now;
    struct tm utc;
    clock_gettime(CLOCK_REALTIME, &now);
    gmtime_r(&now.tv_sec, &utc);
    strftime(buffer, 32, "%Y-%m-%dT%H:%M:%S", &utc);
    snprintf(buffer + 19, 13, ".%03ldZ", now.tv_nsec / 1000000L);
}

static long count_io(BIO *bio, int operation, const char *argp, size_t len,
                     int argi, long argl, int ret, size_t *processed)
{
    io_counts *counts = (io_counts *)BIO_get_callback_arg(bio);
    (void)argp;
    (void)len;
    (void)argi;
    (void)argl;

    if (counts && (operation & BIO_CB_RETURN) && ret > 0 && processed) {
        /* BIO_CB_WRITE is 0x03 and therefore shares the BIO_CB_READ bit
         * (0x02). Match the complete operation code: testing bit membership
         * first would classify every successful write as a read. */
        switch (operation & ~BIO_CB_RETURN) {
        case BIO_CB_READ:
            counts->bytes_read += *processed;
            break;
        case BIO_CB_WRITE:
            counts->bytes_written += *processed;
            break;
        default:
            break;
        }
    }
    return ret;
}

static int connect_tcp(const options *opts, bool *timed_out)
{
    struct addrinfo hints = {0};
    struct addrinfo *addresses = NULL;
    struct addrinfo *address;
    struct timeval timeout;
    int socket_fd = -1;

    *timed_out = false;

    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(opts->host, opts->port, &hints, &addresses) != 0) {
        return -1;
    }

    timeout.tv_sec = opts->timeout_ms / 1000;
    timeout.tv_usec = (opts->timeout_ms % 1000) * 1000;
    for (address = addresses; address; address = address->ai_next) {
        socket_fd = socket(address->ai_family, address->ai_socktype,
                           address->ai_protocol);
        if (socket_fd < 0) continue;
        int original_flags = fcntl(socket_fd, F_GETFL, 0);
        if (original_flags < 0 || fcntl(socket_fd, F_SETFL, original_flags | O_NONBLOCK) != 0) {
            close(socket_fd);
            socket_fd = -1;
            continue;
        }
        setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(socket_fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        if (connect(socket_fd, address->ai_addr, address->ai_addrlen) == 0) {
            fcntl(socket_fd, F_SETFL, original_flags);
            break;
        }
        if (errno == EINPROGRESS) {
            struct pollfd descriptor = {.fd = socket_fd, .events = POLLOUT};
            int ready = poll(&descriptor, 1, (int)opts->timeout_ms);
            int socket_error = 0;
            socklen_t error_length = sizeof(socket_error);
            if (ready > 0 && getsockopt(socket_fd, SOL_SOCKET, SO_ERROR,
                                        &socket_error, &error_length) == 0 &&
                socket_error == 0) {
                fcntl(socket_fd, F_SETFL, original_flags);
                break;
            }
            if (ready == 0) *timed_out = true;
        }
        close(socket_fd);
        socket_fd = -1;
    }
    freeaddrinfo(addresses);
    return socket_fd;
}

static void json_string(FILE *output, const char *value)
{
    const unsigned char *cursor = (const unsigned char *)(value ? value : "");
    fputc('"', output);
    for (; *cursor; cursor++) {
        switch (*cursor) {
        case '"': fputs("\\\"", output); break;
        case '\\': fputs("\\\\", output); break;
        case '\n': fputs("\\n", output); break;
        case '\r': fputs("\\r", output); break;
        case '\t': fputs("\\t", output); break;
        default:
            if (*cursor < 0x20) {
                fprintf(output, "\\u%04x", *cursor);
            } else {
                fputc(*cursor, output);
            }
        }
    }
    fputc('"', output);
}

static void emit_result(const options *opts, unsigned sequence,
                        const char *timestamp, const char *status,
                        const char *phase, double latency_ms,
                        const char *negotiated_group, const char *cipher,
                        const io_counts *counts, unsigned long error_code)
{
    printf("{\"schema_version\":\"1.0\",\"batch_id\":");
    json_string(stdout, opts->batch_id);
    printf(",\"cell_id\":");
    json_string(stdout, opts->cell_id);
    printf(",\"sequence\":%u,\"timestamp_utc\":", sequence);
    json_string(stdout, timestamp);
    printf(",\"requested_group\":");
    json_string(stdout, opts->group);
    printf(",\"status\":");
    json_string(stdout, status);
    printf(",\"failure_phase\":");
    if (phase) json_string(stdout, phase); else printf("null");
    printf(",\"handshake_latency_ms\":");
    if (latency_ms >= 0.0) printf("%.6f", latency_ms); else printf("null");
    printf(",\"negotiated_group\":");
    if (negotiated_group) json_string(stdout, negotiated_group);
    else printf("null");
    printf(",\"cipher\":");
    if (cipher) json_string(stdout, cipher); else printf("null");
    printf(",\"tls_bytes_read\":%llu,\"tls_bytes_written\":%llu",
           (unsigned long long)counts->bytes_read,
           (unsigned long long)counts->bytes_written);
    printf(",\"openssl_error_code\":%lu}\n", error_code);
    fflush(stdout);
}

static bool run_handshake(SSL_CTX *context, const options *opts,
                          unsigned sequence, bool recorded)
{
    SSL *ssl = NULL;
    BIO *read_bio;
    BIO *write_bio;
    io_counts counts = {0};
    int socket_fd;
    int result;
    uint64_t started;
    uint64_t finished;
    char timestamp[32];
    const char *negotiated_group = NULL;
    const char *cipher = NULL;
    const char *status = "failed";
    const char *phase = "tcp_connect";
    double latency_ms = -1.0;
    unsigned long error_code = 0;
    bool tcp_timed_out = false;

    ERR_clear_error();
    socket_fd = connect_tcp(opts, &tcp_timed_out);
    utc_timestamp(timestamp);
    if (socket_fd < 0) {
        if (tcp_timed_out) status = "timeout";
        if (recorded) {
            emit_result(opts, sequence, timestamp, status, phase, latency_ms,
                        NULL, NULL, &counts, 0);
        }
        return false;
    }

    ssl = SSL_new(context);
    if (!ssl) {
        close(socket_fd);
        if (recorded) {
            emit_result(opts, sequence, timestamp, status, "ssl_initialise",
                        latency_ms, NULL, NULL, &counts, ERR_peek_last_error());
        }
        return false;
    }

    if (SSL_set_fd(ssl, socket_fd) != 1 ||
        SSL_set_tlsext_host_name(ssl, opts->server_name) != 1 ||
        SSL_set1_host(ssl, opts->server_name) != 1) {
        if (recorded) {
            emit_result(opts, sequence, timestamp, status, "ssl_initialise",
                        latency_ms, NULL, NULL, &counts, ERR_peek_last_error());
        }
        SSL_free(ssl);
        close(socket_fd);
        return false;
    }
    SSL_set_session(ssl, NULL);
    read_bio = SSL_get_rbio(ssl);
    write_bio = SSL_get_wbio(ssl);
    BIO_set_callback_arg(read_bio, (char *)&counts);
    BIO_set_callback_ex(read_bio, count_io);
    if (write_bio != read_bio) {
        BIO_set_callback_arg(write_bio, (char *)&counts);
        BIO_set_callback_ex(write_bio, count_io);
    }

    phase = "tls_handshake";
    errno = 0;
    started = monotonic_ns();
    result = SSL_connect(ssl);
    finished = monotonic_ns();
    latency_ms = (double)(finished - started) / 1000000.0;

    if (result == 1) {
        negotiated_group = SSL_get0_group_name(ssl);
        cipher = SSL_get_cipher_name(ssl);
        /* OpenSSL returns canonical group names in lowercase (for example,
         * "x25519") while the experiment config uses CLI spelling ("X25519"). */
        if (negotiated_group && strcasecmp(negotiated_group, opts->group) == 0) {
            status = "success";
            phase = NULL;
        } else {
            status = "group_mismatch";
            phase = "verification";
        }
    } else {
        int ssl_error = SSL_get_error(ssl, result);
        int system_error = errno;
        error_code = ERR_peek_last_error();
        if ((ssl_error == SSL_ERROR_SYSCALL || ssl_error == SSL_ERROR_WANT_READ ||
             ssl_error == SSL_ERROR_WANT_WRITE) &&
            (system_error == EAGAIN || system_error == EWOULDBLOCK ||
             system_error == ETIMEDOUT)) {
            status = "timeout";
        }
    }

    if (recorded) {
        emit_result(opts, sequence, timestamp, status, phase, latency_ms,
                    negotiated_group, cipher, &counts, error_code);
    }

    BIO_set_callback_ex(read_bio, NULL);
    BIO_set_callback_arg(read_bio, NULL);
    if (write_bio != read_bio) {
        BIO_set_callback_ex(write_bio, NULL);
        BIO_set_callback_arg(write_bio, NULL);
    }
    SSL_shutdown(ssl);
    SSL_free(ssl);
    close(socket_fd);
    return strcmp(status, "success") == 0;
}

int main(int argc, char **argv)
{
    options opts;
    SSL_CTX *context;
    unsigned index;

    if (!parse_options(argc, argv, &opts)) {
        usage(argv[0]);
        return EXIT_FAILURE;
    }

    /* A peer may close during a write; report the handshake failure instead of dying. */
    signal(SIGPIPE, SIG_IGN);

    OPENSSL_init_ssl(OPENSSL_INIT_LOAD_SSL_STRINGS |
                     OPENSSL_INIT_LOAD_CRYPTO_STRINGS, NULL);
    context = SSL_CTX_new(TLS_client_method());
    if (!context) {
        ERR_print_errors_fp(stderr);
        return EXIT_FAILURE;
    }
    SSL_CTX_set_min_proto_version(context, TLS1_3_VERSION);
    SSL_CTX_set_max_proto_version(context, TLS1_3_VERSION);
    SSL_CTX_set_session_cache_mode(context, SSL_SESS_CACHE_OFF);
    SSL_CTX_set_verify(context, SSL_VERIFY_PEER, NULL);

    if (SSL_CTX_load_verify_locations(context, opts.ca_file, NULL) != 1 ||
        SSL_CTX_set1_groups_list(context, opts.group) != 1) {
        ERR_print_errors_fp(stderr);
        SSL_CTX_free(context);
        return EXIT_FAILURE;
    }

    for (index = 0; index < opts.warmups; index++) {
        run_handshake(context, &opts, index, false);
    }
    for (index = 0; index < opts.attempts; index++) {
        run_handshake(context, &opts, index, true);
    }

    SSL_CTX_free(context);
    return EXIT_SUCCESS;
}
