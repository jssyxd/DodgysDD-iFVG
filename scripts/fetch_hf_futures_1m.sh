#!/usr/bin/env bash
# Fetch the multi-year NQ + ES 1-minute futures series from Hugging Face.
#
# Why these two:
#   mdelcristo/NQ-F_1min_OHLCV_Parquet -> NQ 1-minute OHLCV, one parquet per
#     year 2015..2025 (~50 MB total). The only multi-year CME 1-minute source found.
#   Khanhpham1992/es-futures-1m -> es_continuous_1m.parquet, the ES continuous
#     1-minute series (15 MB). The 267 MB `es_features_ready.parquet` is
#     pre-computed features we do not need.
#
# SEQUENTIAL on purpose: this host drops concurrent TLS connections (8 parallel
# requests all fail; one succeeds in ~5 s).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DEST=research/hf_futures
mkdir -p "$DEST"

fetch() {  # $1=repo_id  $2=file  $3=outdir
    local url="https://huggingface.co/datasets/$1/resolve/main/$2"
    local out="$DEST/$3/$2"
    mkdir -p "$(dirname "$out")"
    if [ -s "$out" ]; then echo "  have $out"; return 0; fi
    echo "  get $2"
    for a in 1 2 3 4 5 6 7 8; do
        if curl -sL --fail --retry 2 --retry-delay 3 -o "$out.part" "$url"; then
            mv "$out.part" "$out"; echo "  ok $2 ($(du -h "$out"|cut -f1))"; return 0
        fi
        sleep $((a*4))
    done
    rm -f "$out.part"; echo "  MISS $2"; return 1
}

echo "== ES continuous 1m =="
fetch Khanhpham1992/es-futures-1m es_continuous_1m.parquet ES

echo "== NQ 1m by year =="
for y in 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
    fetch mdelcristo/NQ-F_1min_OHLCV_Parquet "NQ_1min_$y.parquet" NQ
done
echo "== done =="
du -sh "$DEST"/* 2>/dev/null
