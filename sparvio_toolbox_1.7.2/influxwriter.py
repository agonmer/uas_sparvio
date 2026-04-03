"""Write Sparvio variable reports to InfluxDB using a separate thread

Updates are sent in batch every 0.5 seconds, maximum 30 Influx
measurements at a time (or a few more).

If the InfluxDB server is offline or goes offline, data up to 12 hours
old will be backwritten when the server comes online.

"""

import traceback
import datetime
import time
from requests.exceptions import ConnectionError, ReadTimeout
try:
    import influxdb
    from influxdb import InfluxDBClient
except:
    print('InfluxDB database manager not installed. Install with: "pip install influxdb"')
    influxdb = None

from reactive import eventthread
from reactive.eventthread import run_in_thread, CooldownScheduler
from reactive.observable import ListState
from sspt import pyObjects
from sspt import constants
from sspt.type_hints import *
from core.gis import log

instance = None
print_messages = False

class InfluxStub(object):
    def start(self):
        pass
    def stop(self):
        pass
    def write(self, dic, reception=None, timestamp=None):
        pass
    def launch_grafana(self):
        pass
    def register_get_component_name(self, get_component_name_fn):
        pass

def is_available(config):
    "If influx is available when using <config>"
    # Could report which variable i
    verbose = config['verbose']
    for x in ['influx_host', 'influx_port', 'influx_user',
              'influx_password', 'influx_database', 'influx_dbname']:
        if config.get(x, None) is None:
            if verbose:
                print('Influx: Not available due to ' + x)
            return False
    if influxdb is None:
        if verbose:
            print('Influx: Missing Python package influxdb')
        return False
    return True

def start(config, _log : log.ObjectsLog):
    if not is_available(config):
        return InfluxStub()

    global instance
    assert instance is None
    instance = Influx(config, _log).start()
    return instance

# Influx API documentation:
# http://influxdb-python.readthedocs.io/en/latest/api-documentation.html
class Influx(eventthread.EventThread):
    """Writes all entries of a log to an InfluxDB database. Gracefully
       handles if the InfluxDB server is not running."""
    def __init__(self, config, _log : log.ObjectsLog):
        eventthread.EventThread.__init__(self, name="Influx")
        self._client : 'influxdb.InfluxDBClient' = None
        self.config = config
        #Connecting:
        self._first_try = True
        self._connected = False
        self._connect_timer = eventthread.Timer(self, self.connect)
        #self._write_timer = eventthread.CooldownTimer(self,
        #                                              self._write_entries,
        #                                              delay_sec = 0.2,
        #                                              cooldown_sec = 1.0)


        #Processing:
        self._get_component_name_fn : Optional[Callable[[Oid], str]] = None
        self._log : log.ObjectsLog = _log
        # The part of the log that has been written to InfluxDB
        self._processed_state : ListState = ListState()
        self._cooldown = CooldownScheduler(self,
                                           eventthread.immediate_scheduler,
                                           delay_sec = 0.2,
                                           cooldown_sec = 1.0)

    def register_get_component_name(self, get_component_name_fn):
        self._get_component_name_fn = get_component_name_fn

    def setup(self):
        self.connect()
        self._connect_timer.start(5, recurring=True)
        # No initial_invoke, as connect will trigger write_entries
        # when successful
        self._log.add_observer((self._cooldown, self._write_entries))

    def _write_entries(self):
        if not self._alive or not self._connected:
            if print_messages:
                print('Influx: Cannot write since not connected')
            return
        if not self._get_component_name_fn:
            print('Influx: No _get_component_name_fn')
            return

        diff = self._log.diff(self._processed_state)
        self._processed_state.revision = self._log.revision.get()
        if diff.mutations:
            # Could at least support insertions
            # Use delete_series() to remove changed entries before adding the updates ones?
            # https://influxdb-python.readthedocs.io/en/latest/api-documentation.html
            print("Error: Influxwriter doesn't handle mutations to the log")
            return

        if diff.is_empty():
            return

        influx_data = []
        earliest_timestamp = time.time() - 12 * 60 * 60  #Twelve hours ago
        for newest_handled_ix in diff.appended_indices():
            entry = self._log.ix_to_entry(newest_handled_ix)
            if entry.key < earliest_timestamp:
                continue  #Ignore very old data

            dt = datetime.datetime.utcfromtimestamp(entry.key)
            for (oid, _map) in entry.data.items():
                if type(oid) is str:
                    name = oid
                else:
                    name = self._get_component_name_fn(oid)
                values = {} #_map.copy()
                for (key, value) in _map.items():
                    if key == 'lTime':
                        continue
                    if key in constants.config_symbols:  #Variables not exposed to InfluxDB
                        continue
                    if value == 'null':
                        continue
                    if key in constants.decimal_symbols and (value == '0' or value == 0):
                        values[key] = 0.0
                        continue
                    if isinstance(value, pyObjects.SspPyObj):
                        if print_messages:
                            print('Influx ignoring SspPyObj', value)
                        continue
                    if isinstance(value, str) or isinstance(value, bytes):
                        if print_messages:
                            print('Influx ignoring string')
                        continue
                    if isinstance(value, list):
                        #TODO: Tag with index?
                        #Write "time series bucket" measurement name format like:
                        #seconds_bucket(le=0.2)
                        #if print_messages:
                        #    print('Ignoring list', value)
                        continue

                    if name is None:
                        tags = {}
                    else:
                        tags = {"sensor": name}

                    if isinstance(value, dict):
                        for (index, index_value) in value.items():
                            tags = tags.copy()
                            tags["index"] = index
                            influx_data.append({"measurement": key,
                                                "time": dt,
                                                "tags": tags,
                                                "fields": {"value": index_value}})
                        continue
                    influx_data.append({"measurement": key,
                                        "time": dt,
                                        "tags": tags,
                                        "fields": {"value": value}})
                #if reception is not None:
                #influx_data.append({"measurement": "Reception",
                #                    "fields": {"value": reception}})
            if len(influx_data) > 30:
                break
        if not influx_data:
            # Avoid processing the same (empty) entries again next time
            self._processed_state.entry_count = newest_handled_ix + 1
            return

        try:
            self._client.write_points(influx_data, time_precision='ms')
        except influxdb.client.InfluxDBClientError as ex:
            # The InfluxDB Python library doesn't specify the meaning
            # of 'code', but let's assume that 400 always means the
            # type of a DB field doesn't match the value we attempted
            # to insert.
            if ex.code != 400:
                print('InfluxDB exception writing:', ex)
                #TODO: Tear down self._client ?
                self._connected = False
                return
        except ReadTimeout:
            if print_messages:
                print('InfluxDB ReadTimeout')
            self._connected = False
            return
        except influxdb.client.InfluxDBServerError:
            if print_messages:
                print('InfluxDB timeout')
            #self._connected = False  ?
            return
        except ConnectionError:
            #InfluxDB may be closed now
            print('InfluxDB disappeared?')
            return

        #print 'Influx wrote %d measurements' % len(influx_data)
        #Mark entries as processed only if we could write them
        self._processed_state.entry_count = newest_handled_ix + 1
        if diff.last_new_ix > newest_handled_ix:
            self.call_later(self._write_entries)

    ##########################
    ###  Public methods

    def launch_grafana(self):
        #This package can configure Grafana dashboards:
        #https://github.com/weaveworks/grafanalib
        #To launch Grafana:
        # sudo service grafana-server start
        #or:
        # systemctl start grafana-server

        if influxdb is None:
            print('Python influxdb package not installed -- will not view Grafana.')
            return

        print('Make sure Grafana is running. Start by: "sudo service grafana-server start"')

        #Check if the Grafana server is running:
        #systemctl status grafana-server
        import webbrowser
        port = self.config['grafana_port']
        db = self.config['influx_database'].lower()
        #webbrowser.open("http://127.0.0.1:%d" % port)

        # Launch the Grafana client:
        webbrowser.open("http://localhost:%d/dashboard/db/%s?refresh=1s&orgId=1" % (port, db))

    ###########################################
    ###  Private methods, invoked on own thread

    @run_in_thread
    def connect(self):
        #Check if the server is running:
        #service influxdb status

        if self._connected:
            return

        if influxdb is None:
            print('Python influxdb package not installed. Will not write to database.')
            self.stop()
            return

        if self._client is None:
            try:
                db = host = self.config['influx_database']
                host = self.config['influx_host']
                port = self.config['influx_port']
                user = self.config['influx_user']
                password = self.config['influx_password']
                # Use short timeout and only one retry, since we have
                # our own logics to retry that doesn't block if the
                # script needs to exit.
                self._client = influxdb.InfluxDBClient(host, port, user,
                                                       password, db,
                                                       timeout=0.3,
                                                       retries=1)
            except:
                print('Error setting up Influx DB:', traceback.print_exc())
                # Could try again, but this step seems to always
                # succeed, so unclear if retrying makes any difference
                self.stop()
                return

        try:
            self._client.switch_database(self.config['influx_dbname'])
        except:
            print('InfluxDB switch database failed')
            self.stop()
            return

        try:
            #If false is returned, it failed so try again
            success = self._create_db()
        except:
            print('Error setting up Influx DB:', traceback.print_exc())
            return
        if success:
            self._connected = True
            if print_messages:
                print('Connected to database')
            # Write any pending log entries
            self.call_later(self._write_entries)

    def _create_db(self):
        "Returns True on success. May also raise an exception."
        if self._client is None:
            return False
        #try:
        #    self._client.drop_database(self.config['influx_dbname'])
        #except InfluxDBClientError:
        #    pass
        try:
            self._client.create_database(self.config['influx_dbname'])
        except ConnectionError:
            if self._first_try:
                print("InfluxDB doesn't seem to be running. Will continue trying to connect.")
                self._first_try = False
            return False
        except ReadTimeout:
            if self._first_try:
                print("InfluxDB doesn't seem to be running (ReadTimeout). Will continue trying to connect.")
                self._first_try = False
            return False
        except:
            print('Error creating influxdb DB:', traceback.print_exc())
            return False
        #client.create_retention_policy('awesome_policy', '3d', 3, default=True)
        #self._client.switch_user(dbuser, dbuser_password)
        return True

    @run_in_thread
    def clear(self):
        if self._client is None:
            return
        self._client.drop_database(self.config['influx_dbname'])
        self._create_db()

    def _close(self):
        "Close the connection to the InfluxDB server"
        if self._client is None:
            return
        self._client.close()

    def on_stop(self):
        #Clean up
        self._close()
