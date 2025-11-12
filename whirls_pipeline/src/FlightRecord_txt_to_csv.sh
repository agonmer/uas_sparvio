#!/bin/bash

# from https://github.com/lvauvillier/dji-log-parser
INPUT_FILE=$1
OUTPUT_FILE=$2
/home/lorenzo/uas_sparvio/whirls_pipeline/src/dji-log --api-key 63aada608d30dd4a71fa97cf62006c3 --csv $OUTPUT_FILE $INPUT_FILE