# Instructions for UAS data pipeline 

## Environment

The conda environment can be built from "/path_to_repo/uas_sparvio/whirls_pipeline/env/environment.yml".

_ADD YML FILE_

You also need to add "export JAVA_HOME=/path/to/your/env/myenv" to you .bashrc to have java-based app to identify the java version installed in your environment.

## Convert FlighRecords (.txt) to .csv

To convert FlighRecords (.txt) to .csv use the bash script "uas_sparvio/whirls_pipeline/scripts/FlightRecord_txt_to_csv.sh" with the path to the txt file and the output path for the csv file.
Or use the corresponding py script (/home/lorenzo/uas_sparvio/whirls_pipeline/scripts/extract_and_open_flight_record.py).


## Convert Logs (.DAT) to .csv

We use DatCon (https://datfile.net/DatCon/downloads.html), its downloaded in "uas_sparvio/whirls_pipeline/scripts/DatCon/DatCon.4.3.0.jar".
Run it with "java -jar /path_to_repo/uas_sparvio/whirls_pipeline/scripts/DatCon/DatCon.4.3.0.jar".

Or use the py script (/home/lorenzo/uas_sparvio/whirls_pipeline/scripts/extract_and_open_logs.py)
