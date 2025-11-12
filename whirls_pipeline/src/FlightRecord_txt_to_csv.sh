#!/bin/bash

# from https://github.com/lvauvillier/dji-log-parser
# Usage: FlightRecord_txt_to_csv.sh <input_file> <output_file>
#
# This script requires the API key to be provided via the
# UAS_SPARVIO_API_KEY environment variable. This keeps secrets out
# of command history and avoids files/args being used.

set -euo pipefail

if [ "$#" -lt 2 ]; then
	echo "Usage: $0 <input_file> <output_file>" >&2
	exit 2
fi

INPUT_FILE=$1
OUTPUT_FILE=$2

if [ -z "${UAS_SPARVIO_API_KEY-}" ]; then
	cat >&2 <<'EOF'
Error: UAS_SPARVIO_API_KEY environment variable is not set.

Set the API key in your environment and re-run, for example:
  export UAS_SPARVIO_API_KEY='your_api_key_here'
  ./FlightRecord_txt_to_csv.sh input.txt output.csv

Keeping the key in an environment variable avoids leaving it in shell
history or files. Protect your environment appropriately.
EOF
	exit 1
fi

exec /home/lorenzo/uas_sparvio/whirls_pipeline/src/dji-log --api-key "$UAS_SPARVIO_API_KEY" --csv "$OUTPUT_FILE" "$INPUT_FILE"