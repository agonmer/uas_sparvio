import os 
import subprocess
import argparse

parser = argparse.ArgumentParser()

parser.add_argument('-folder', action='store', dest='folder',
                    help='Folder containing the flight record .txt files to be converted to .csv')

parser.add_argument('-file', action='store', dest='file',
                    help='Flight record .txt to be converted to .csv')

args = parser.parse_args()

if args.folder is not None:
    for filename in os.listdir(args.folder):
        print(filename)
        if filename[-3:] != "txt":
            continue
        if not os.path.exists(os.path.join(args.folder+filename[:-3] + "csv")):
            print(f"Converting {filename}")
            file = os.path.join(args.folder, filename)

            # Extract flight record
            export_sh = "/home/lorenzo/uas_sparvio/whirls_pipeline/src/FlightRecord_txt_to_csv.sh"
            subprocess.run([export_sh, file[:-3] + "txt", file[:-3] + "csv"])


if args.file is not None:
    if not os.path.exists(args.file[:-3] + "csv"):

        # Extract flight record
        export_sh = "/home/lorenzo/uas_sparvio/whirls_pipeline/src/FlightRecord_txt_to_csv.sh"
        subprocess.run([export_sh, args.file[:-3] + "txt", args.file[:-3] + "csv"])
