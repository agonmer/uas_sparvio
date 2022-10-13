VERSION = "1.5.0"
# Versioning adhers to Semantic Versioning: https://semver.org/spec/v2.0.0.html

"""
Version history:

1.5.0  2022-03-15
       Add Aeris MIRA CO2/N2O.
       Rename aeris_mira_pico.
       Add compassCalibrate.
       call.py support any number of function arguments, also none.

1.4.7  2022-01-26 SspAsciiLineProtocol ignore leading and trailing null bytes

1.4.6  2022-01-11 Guard against calling a local SSP function that doesn't exist

1.4.5  2022-01-07 Fix in get.py. Support Licor LI-850.

1.4.4  2021-09-23 Fix bridge.py.

1.4.3  2021-09-11 Add symbol 'resetDisplay'

1.4.2  2021-08-27 Fix install of 3D visualization.

1.4.1  2021-06-30 Add symbol for nitrous oxide.
       Catch parse errors in txt_receiver.

1.4.0  2021-05-26 Support 3D view with Cesium. system_log is MutableObjectsLog.
       Rename InvasiveChange to Mutation. New symbols.

1.3.1  2021-04-12 Fix for read_log.py. Include environment.yml.

1.3.0  2021-03-30 First support for 3D visualization with Cesium.
       Fixes installation compared to 1.2.0.
       Adds support for Python 3.9.

1.2.0  2021-03-29 More symbols and sensors.
       Moving towards using Observable etc. CSV output supports
       configuration parameters. Support telemetry from SKH1.
       Split config.py into config_interactive.py and config_noninteractive.py.

1.1.3  2020-12-16 Include missing files in installation and fix 'verbose' flag

1.1.2  2020-12-10
       Bugfixes and more features for read_log.py

1.1.1  2020-11-27
       Add new symbols.
       Bugfix writing dicts to InfluxDB with multiple 'index' tags

1.1.0  2020-08-29
       Support read_log.py and upgrade.py with latest SSP 3.

1.0.0  2020-06-15
       Migrate to Python 3
       Compatible with SSP 3 (not devices with firmware SSP 2)
       Add data model
       Support KML

0.10.0  2020-01-30. Add call.py. Visualize match GPS coordinates.
        Add new applications.
        upgrade.py print more information to the user

0.9.0  Add interactive.py --sub.
       bridge.py now supports Ctrl+C and Ctrl+D in Windows.
       Bugfix visualize.py --bind.
       Bugfix get.py and InfluxDB connection.
       Add Plantower PMS7003 and Atlas T3.

0.8.2  Check for Python 2
       Add Figaro TGS 2611
       Updated installation instructions

0.8.1  Include the fixed yet-unreleased ptpython module

0.8.0  Add visualize.py --bind

0.7.1  Fixes. read_log.py --optimize is default.
       upgrade.py -app can list all applications.
       Polished manual.

0.7.0  upgrade.py accepts multiple --verbose and defaults to --writelatest.
       upgrade.py --write accepts an URL.
       get.py --all prints all parameters of all modules.

0.6.2  Updated the manual.

0.6.1  Fix upgrade.py matching the firmware file

0.6.0  Change obligatory port argument to optional --port, and default_port.txt
       Change upgrade.py to work with different applications
       Add a first Grafana dashboard to grafana/

0.5.0  Use InfluxDB tag 'sensor'.
       Fix bug in serial comm under Windows.
       Catch some other errors.

0.4.3  Handle RR2 reception quality. set_multi().
       Dont use exponential form for floats.

0.4.2  Minor.

0.4.1  React to dynamically added components
       Print application id as string
       Add read_log.py argument 'dir'
       Speed up firmware upgrade from 6 min to 30 seconds

0.4.0  Add get.py, set.py and visualize.py
       Make serialconn.py work with Pyserial < 3
       Various small fixes

0.3.3  Continue with next file in case of error.
       Dont do cancel_read() in order to write to serial (experiment)
       Longer timeout when reading line

0.3.2  Debug with retry for read_log

0.3.1  Debug

0.3.0  Option to write the latest firmware detected over internet

"""
