#! /bin/bash

source /home/agostino/miniconda3/etc/profile.d/conda.sh
conda activate ssp
sudo service influxdb start
sudo service grafana-server start
python ./telemetry.py --port /dev/ttyACM0

