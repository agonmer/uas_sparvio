# CsvLogger: Writes selected keys from a ValuesLog to a CSV file
# (CSV = Comma-Separated Values)

from datetime import datetime, timezone
import time
import os
from collections import abc

from sspt.type_hints import *
from .log import Log, ValuesLog, ObjectsLog
from reactive.eventthread import Scheduler, CooldownObservable
from reactive.observable import ListState
import version
#from sspt import pyObjects

"""Entries with timestamps closer in time than this will be merged
into one line when there's no overlap between the logged parameters"""
MAX_MERGE_TIME_DIFF = 1.0

def overlaps(row1, row2):
    for key in row2:
        if key == 0:
            continue
        if key in row1:
            return True
    return False

def merge(row1, row2):
    for (key, value) in row2.items():
        if key == 0:
            continue
        row1[key] = value

class CsvLogger:
    def __init__(self, path : str, log : ValuesLog,
                 columns : Sequence[Var],
                 scheduler : Scheduler,
                 write_delay_sec : float = 1,
                 write_interval_sec : float = 5):
        self._log = log
        self._processed_state = ListState()
        self.separator = '; '
        self.columns = columns  # List of symbols
        cooldown = CooldownObservable(cooldown_sec = write_interval_sec,
                                      delay_sec = write_delay_sec,
                                      flush_on_exit=True,
                                      observer=(scheduler,self._on_log_changed))
        self._log.add_observer(cooldown.get_job(), initial_notify=True)
        self.path = path
        # Could open the file if it exists and read the line with
        # column names to figure out what columns to use.

    def _on_log_changed(self):
        diff = self._log.update_state(self._processed_state)
        if diff.mutations:
            try:
                os.remove(self.path)
            except:
                pass
            diff = self._processed_state.as_diff() #Process the whole state
        if diff.is_empty():
            return

        rows = []
        #print('CsvLogger: {} new rows'.format(diff.number_of_new_entries()))
        for ix in diff.appended_indices():
            # Sort the values into the correct columns
            row = None
            for (key, value) in self._log.ix_to_data(ix).items():
                try:
                    column = self.columns.index(key)
                except ValueError:
                    continue
                if row is None:
                    row = [''] * len(self.columns)
                    if 'timestamp' in self.columns:
                        timestamp = self._log.ix_to_entry(ix).key
                        #TODO: Use Locale to format:
                        time_str = datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%dZ%H:%M:%S')
                        row[self.columns.index('timestamp')] = time_str
                row[column] = str(value)  #TODO: Use Locale to format
            if row is not None:
                rows.append(row)
            #else:
            #    print('CsvLogger nothing to log in', self._log.ix_to_data(ix))
        if rows != []:
            if os.path.isfile(self.path):
                f = open(self.path, 'a')
            else:
                #print('CsvLogger: Creating the file', self.path)
                f = open(self.path, 'w')
                f.write(self.separator.join([pad(s) for s in self.columns]))
                f.write('\n')
            #write_header = (not os.path.isfile(self.path))
            for row in rows:
                f.write(self.separator.join([pad(s) for s in row]))
                f.write('\n')
            #print('CsvLogger: Wrote {} rows to the file {}'.format(len(rows), self.path))
            f.close()
        else:
            #print('CsvLogger: No rows to log')
            pass

def pad(s):
    if len(s) < 2:
        s = ' ' + s
    if len(s) < 2:
        s = ' ' + s
    return s

default_metadata_variables = ['name', 'id', 'lTime', 'lLogTime', 'utcDate', 'utc',
                              'serNo', 'configParams',
                              'parent', 'fwVer', 'defParams', 'samplingInterval',
                              'app', 'logDo', 'neig', 'components', 'funcSigs',
                              'snsState']
default_metadata_variables += ['traceEvt', 'errorEvt']

def find_first_timestamp(_log: ObjectsLog):
    for entry in _log.all_entries():
        if entry.key:
            return entry.key
    return None

def timestamp_to_ascii(timestamp : Timestamp):
    if timestamp is None:
        return ''
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%H:%M:%S.%f')[:-3]
def default_to_ascii(value : Any):
    if isinstance(value, float):
        return str(round(value, 6))
    if isinstance(value, list):
        return '[' + ', '.join([default_to_ascii(v) for v in value]) + ']'
    if isinstance(value, str):
        if value == 'null':
            return ''
        return repr(value)  #Uses quotes and escapes unprintable ASCII codes
    if isinstance(value, dict):
        if 'verMajor' in value and 'verMinor' in value:
            return "%d.%d" % (value['verMajor'], value['verMinor'])
    return str(value)

def write_snapshot(_log: ObjectsLog, path="", separator = '; '):
    """Collects column names from all objects of <_log> and uses them to
       create the <path> CSV file."""
    file = open(path, 'w')

    log_start = find_first_timestamp(_log)

    ###############################################
    # WRITE CSV FILE HEADER
    if log_start:
        date = timestamp_to_ascii(log_start)
        file.write("# Sparvio %s log file. Logging started at %s UTC.\n" %
                   (version.VERSION, date))
        global_timestamps = True
    else:
        file.write("# Sparvio %s log file. Unknown start time.\n" %
                   version.VERSION)
        global_timestamps = False
        # Revert to using the time of logging as timestamps for now
    metadata_variables = default_metadata_variables.copy()

    file.write('# Logged components:\n')
    # Initialize CSV and write header
    object_names = {}  # Map from OID to string name

    for oid in _log.all_objects():
        if oid == 'logger':
            continue
        valueslog = _log.get_valueslog(oid)
        if valueslog is None:
            continue
        name = valueslog.most_recent_value('name')
        if name is None:
            name = str(oid)
            file.write("# " + name + ": \n")
        else:
            file.write("# %s (id=%d): \n" % (name, oid))
        object_names[oid] = name
        file.write("#   Serial number%s%s\n" % (separator, str(valueslog.most_recent_value('serNo', '?'))))
        file.write("#   App and version%s%s%s%s\n" % (separator,
                                                      str(valueslog.most_recent_value('app', '?')),
                                                      separator,
                                                     str(valueslog.most_recent_value('fwVer', '?'))))
        configParams = valueslog.most_recent_value('configParams')
        if configParams:
            for param in configParams:
                value = valueslog.most_recent_value(param)
                if value:
                    file.write("#   %s%s%s\n" % (param, separator, default_to_ascii(value)))
                if param not in metadata_variables:
                    # Hack -- hides the parameter for *all*
                    # components, not just the one where it's a
                    # configuration parameter
                    metadata_variables.append(param)

    file.write("\n")

    # Map from column name (eg. string "SKH1.pr") to column number
    column_name_to_ix = {}
    if global_timestamps:
        column_name_to_ix['timestamp'] = 0
        sorted_column_names = ["Time (UTC)"]
        column_formatters = {0: timestamp_to_ascii}
    else:
        column_name_to_ix['timestamp'] = 0
        sorted_column_names = ["Relative time (sec)"]
        column_formatters = {0: lambda value: "%.03f" % value}

    ###############################################
    # CALCULATE LOG LINES

    # List of all lines to write. Each line is a dictionary from column
    # index to the value of that cell.
    rows : List = []

    def add_values(prefix, value, row):
        """Add entries to <row>, transforming nested dictionaries in <value>
           to the form x.y.z"""
        if isinstance(value, abc.ItemsView) or isinstance(value, dict):
            for (key, subvalue) in value.items():
                if key in metadata_variables:
                    continue  # Exclude these from the CSV file
                if subvalue == 'null':
                    continue
                #if pyObjects.is_null(value):
                #    continue
                add_values(prefix + '.' + key, subvalue, row)
            return

        nonlocal column_name_to_ix
        column_ix = column_name_to_ix.get(prefix, None)
        if column_ix is None:
            column_ix = len(column_name_to_ix)
            column_name_to_ix[prefix] = column_ix
            sorted_column_names.append(prefix)
        row[column_ix] = value

    prev_timestamp = None
    timestamp = None
    for entry in _log.all_entries():
        prev_timestamp = timestamp
        # Sort the data of an entry into the columns
        if global_timestamps:
            row = {0: entry.key}
            timestamp = entry.key
        else:
            timestamp = entry.data['logger']['lLogTime']
            row = {0: timestamp - _log[0].data['logger']['lLogTime']}
        for (oid, valuemap) in entry.data.items():
            if oid in object_names:
                add_values(object_names[oid], valuemap, row)
        # Try to merge with the previous row
        merged = False
        if prev_timestamp is not None:
            if timestamp - prev_timestamp < MAX_MERGE_TIME_DIFF and \
               not overlaps(row, rows[-1]):
                merge(rows[-1], row)
                merged = True
                # Only merge additional lines if they are within
                # MAX_MERGE_TIME_DIFF of the first merged line
                timestamp = prev_timestamp
        if not merged:
            rows.append(row)

    ###############################################
    # WRITE LOG LINES TO FILE

    # By now all column names are collected
    file.write(separator.join(sorted_column_names) + "\n")

    timestamp_column_indices = []
    for (name, ix) in column_name_to_ix.items():
        if name == 'timestamp' or name.split('.')[-1] == 'lTime':
            timestamp_column_indices.append(ix)

    # Write the collected columns as a CSV line
    for row in rows:
        if row == {}:
            continue
        # Find if the line contains any non-timestamp columns
        include_line = False
        for ix in row.keys():
            if ix not in timestamp_column_indices:
                include_line = True
                break
        if not include_line:
            continue  # A line with only timestamp(s)
        biggest_column_ix = max(row.keys())
        for column_ix in range(0, biggest_column_ix + 1):
            if column_ix != 0:
                file.write(separator)
            if column_ix in row:
                formatter = column_formatters.get(column_ix, default_to_ascii)
                file.write(formatter(row[column_ix]))
        file.write("\n")

    file.close()
