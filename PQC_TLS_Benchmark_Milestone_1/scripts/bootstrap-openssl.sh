#!/usr/bin/env bash
set -euo pipefail

version="${OPENSSL_VERSION:-3.5.7}"
prefix="${OPENSSL_PREFIX:-/opt/openssl-${version}}"
work_dir="${PQC_BUILD_DIR:-/tmp/pqc-openssl-build-${version}}"
archive="openssl-${version}.tar.gz"
base_url="https://github.com/openssl/openssl/releases/download/openssl-${version}"

if [[ "$(id -u)" -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

mkdir -p "${work_dir}"
cd "${work_dir}"
curl --fail --location --proto '=https' --tlsv1.2 \
  --output "${archive}" "${base_url}/${archive}"
curl --fail --location --proto '=https' --tlsv1.2 \
  --output "${archive}.sha256" "${base_url}/${archive}.sha256"
sha256sum --check "${archive}.sha256"
mkdir -p source
tar --extract --file "${archive}" --directory source --strip-components=1
cd source
./Configure linux-x86_64 shared \
  --prefix="${prefix}" \
  --openssldir="${prefix}/ssl"
make -j"$(nproc)"
make test
"${sudo_cmd[@]}" make install_sw install_ssldirs
"${prefix}/bin/openssl" version -a
