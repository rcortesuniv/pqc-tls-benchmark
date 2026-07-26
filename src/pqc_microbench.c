#define _POSIX_C_SOURCE 200809L

#include <getopt.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#if OPENSSL_VERSION_NUMBER < 0x30500000L
#error "This benchmark requires OpenSSL 3.5.0 or newer"
#endif

static uint64_t monotonic_ns(void)
{
    struct timespec timestamp;
    clock_gettime(CLOCK_MONOTONIC, &timestamp);
    return (uint64_t)timestamp.tv_sec * 1000000000ULL + (uint64_t)timestamp.tv_nsec;
}

static EVP_PKEY *generate_key(const char *algorithm)
{
    EVP_PKEY_CTX *context = EVP_PKEY_CTX_new_from_name(NULL, algorithm, NULL);
    EVP_PKEY *key = NULL;
    if (context == NULL || EVP_PKEY_keygen_init(context) != 1 ||
        EVP_PKEY_generate(context, &key) != 1) {
        EVP_PKEY_free(key);
        key = NULL;
    }
    EVP_PKEY_CTX_free(context);
    return key;
}

static int mlkem_iteration(void)
{
    EVP_PKEY *key = generate_key("ML-KEM-768");
    EVP_PKEY_CTX *encapsulate = NULL;
    EVP_PKEY_CTX *decapsulate = NULL;
    unsigned char *ciphertext = NULL, *shared_secret = NULL, *recovered_secret = NULL;
    size_t ciphertext_length = 0, shared_secret_length = 0, recovered_secret_length = 0;
    int ok = 0;

    if (key == NULL || (encapsulate = EVP_PKEY_CTX_new(key, NULL)) == NULL ||
        EVP_PKEY_encapsulate_init(encapsulate, NULL) != 1 ||
        EVP_PKEY_encapsulate(encapsulate, NULL, &ciphertext_length, NULL, &shared_secret_length) != 1 ||
        (ciphertext = OPENSSL_malloc(ciphertext_length)) == NULL ||
        (shared_secret = OPENSSL_malloc(shared_secret_length)) == NULL ||
        EVP_PKEY_encapsulate(encapsulate, ciphertext, &ciphertext_length,
                             shared_secret, &shared_secret_length) != 1 ||
        (decapsulate = EVP_PKEY_CTX_new(key, NULL)) == NULL ||
        EVP_PKEY_decapsulate_init(decapsulate, NULL) != 1 ||
        EVP_PKEY_decapsulate(decapsulate, NULL, &recovered_secret_length,
                             ciphertext, ciphertext_length) != 1 ||
        (recovered_secret = OPENSSL_malloc(recovered_secret_length)) == NULL ||
        EVP_PKEY_decapsulate(decapsulate, recovered_secret, &recovered_secret_length,
                             ciphertext, ciphertext_length) != 1 ||
        recovered_secret_length != shared_secret_length ||
        CRYPTO_memcmp(shared_secret, recovered_secret, shared_secret_length) != 0) {
        goto cleanup;
    }
    ok = 1;

cleanup:
    OPENSSL_free(ciphertext);
    OPENSSL_free(shared_secret);
    OPENSSL_free(recovered_secret);
    EVP_PKEY_CTX_free(encapsulate);
    EVP_PKEY_CTX_free(decapsulate);
    EVP_PKEY_free(key);
    return ok;
}

static int x25519_iteration(void)
{
    EVP_PKEY *left = generate_key("X25519");
    EVP_PKEY *right = generate_key("X25519");
    EVP_PKEY_CTX *derive = NULL;
    unsigned char *shared_secret = NULL;
    size_t shared_secret_length = 0;
    int ok = 0;

    if (left == NULL || right == NULL || (derive = EVP_PKEY_CTX_new(left, NULL)) == NULL ||
        EVP_PKEY_derive_init(derive) != 1 || EVP_PKEY_derive_set_peer(derive, right) != 1 ||
        EVP_PKEY_derive(derive, NULL, &shared_secret_length) != 1 ||
        (shared_secret = OPENSSL_malloc(shared_secret_length)) == NULL ||
        EVP_PKEY_derive(derive, shared_secret, &shared_secret_length) != 1) {
        goto cleanup;
    }
    ok = 1;

cleanup:
    OPENSSL_free(shared_secret);
    EVP_PKEY_CTX_free(derive);
    EVP_PKEY_free(left);
    EVP_PKEY_free(right);
    return ok;
}

int main(int argc, char **argv)
{
    unsigned iterations = 1000;
    int option;
    static const struct option options[] = {
        {"iterations", required_argument, NULL, 'n'}, {NULL, 0, NULL, 0}
    };
    while ((option = getopt_long(argc, argv, "", options, NULL)) != -1) {
        if (option != 'n' || (iterations = (unsigned)strtoul(optarg, NULL, 10)) == 0) {
            fprintf(stderr, "Usage: %s [--iterations N]\n", argv[0]);
            return EXIT_FAILURE;
        }
    }

    for (const char *algorithm = "ML-KEM-768"; algorithm != NULL; algorithm = NULL) {
        uint64_t started = monotonic_ns();
        for (unsigned index = 0; index < iterations; index++) {
            if (!mlkem_iteration()) return EXIT_FAILURE;
        }
        uint64_t elapsed = monotonic_ns() - started;
        printf("{\"algorithm\":\"%s\",\"operation\":\"keygen_encapsulate_decapsulate\",\"iterations\":%u,\"elapsed_ns\":%llu}\n",
               algorithm, iterations, (unsigned long long)elapsed);
    }
    uint64_t started = monotonic_ns();
    for (unsigned index = 0; index < iterations; index++) {
        if (!x25519_iteration()) return EXIT_FAILURE;
    }
    printf("{\"algorithm\":\"X25519\",\"operation\":\"two_keygen_derive\",\"iterations\":%u,\"elapsed_ns\":%llu}\n",
           iterations, (unsigned long long)(monotonic_ns() - started));
    return EXIT_SUCCESS;
}
