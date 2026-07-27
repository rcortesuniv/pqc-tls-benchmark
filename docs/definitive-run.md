# Definitive-run checklist

The completed `pqc-tls-pilot-*` directories remain pilot evidence. Do not rename,
overwrite or combine them with a definitive collection.

## Freeze before collection

The draft [`config/definitive-experiment.json`](../config/definitive-experiment.json)
uses 20 complete batches (720 batch-cells and 72,000 recorded handshakes) and
pre-specifies one primary comparison:

`X25519MLKEM768 − X25519` at 50 ms RTT and 0% per-direction loss.

Its 100 handshakes within each cell estimate a cell median; the 20 paired batch
medians are the independent observations for the primary inference. The other
network conditions and all other group comparisons are exploratory and retain
Holm adjustment. The primary report has no multiplicity adjustment because it
is one comparison specified before collection.

Before running it, obtain the required supervisor and ethics approval, confirm
that this primary condition and 20-batch design are appropriate, and commit the
frozen configuration and pre-analysis plan. Any later change creates a new
protocol version and must not be merged into the original result directory.

## Container calibration

Rebuild after this update so the fixed-resource image contains `ping`, then
start the lab and apply a profile for calibration:

```bash
docker build --tag pqc-tls-bench:3.5.7 .
scripts/container-lab-down.sh
scripts/container-lab-up.sh
scripts/container-apply-netem.sh 50 0.5
python3 scripts/calibrate-network.py --container \
  --expected-rtt-ms 50 --expected-loss-percent 0.5 \
  --output runtime/calibration-container-rtt50-loss0p5.json
```

Repeat and retain a calibration JSON file for each profile used in the definitive
collection. The calibration is ICMP evidence for the applied netem profile; it
does not replace the TLS workload or prove transport-layer byte counts.

## Run and analyse

After freeze and calibration only:

```bash
python3 scripts/run-experiment.py --backend container \
  --config config/definitive-experiment.json
```

Use the literal directory printed by the runner. Then run:

```bash
analysis/summarise.py "$(ls -1dt results/pqc-tls-definitive-*/ | head -n 1)"
python3 analysis/dashboard.py "$(ls -1dt results/pqc-tls-definitive-*/ | head -n 1)"
```

The summary now includes p95 and p99 cell latency. Inspect these alongside
median and reliability results before claiming that loss has no tail effect.
