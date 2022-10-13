# constants.py: values hardcoded in the SSP-BIN specification

SSP_VERSION = 3
SSP_MAGIC_BYTE = 0xA6

######################################################################
## Built-in type definitions

SSP_TYPE_NULL = 0
SSP_TYPE_BOOL = 1
SSP_TYPE_UINT8 = 2
SSP_TYPE_UINT16 = 3
SSP_TYPE_INT16 = 4
SSP_TYPE_INT32 = 5
SSP_TYPE_UINT32 = 6
SSP_TYPE_FLOAT = 7
SSP_TYPE_SYMBOL = 8
SSP_TYPE_STRING = 9
SSP_TYPE_BLOB = 10
SSP_TYPE_SCHEMA = 11

SSP_FORMAT_UNION = 250  #Temp!

basic_types_regIx = [
SSP_TYPE_NULL, SSP_TYPE_BOOL, SSP_TYPE_UINT8, SSP_TYPE_UINT16, SSP_TYPE_INT16, SSP_TYPE_INT32, SSP_TYPE_UINT32, SSP_TYPE_FLOAT, SSP_TYPE_SYMBOL, SSP_TYPE_STRING, SSP_TYPE_BLOB, SSP_TYPE_SCHEMA]

basic_types_c_names = [
    'SSP_TYPE_NULL', 'SSP_TYPE_BOOL', 'SSP_TYPE_UINT8', 'SSP_TYPE_UINT16', 'SSP_TYPE_INT16', 'SSP_TYPE_INT32', 'SSP_TYPE_UINT32', 'SSP_TYPE_FLOAT', 'SSP_TYPE_SYMBOL', 'SSP_TYPE_STRING', 'SSP_TYPE_BLOB', 'SSP_TYPE_SCHEMA']

#Parameter format types:
SSP_FORMAT_CONSTANT = 12
SSP_FORMAT_TYPED_MAP = 13
SSP_FORMAT_STRUCT = 14
SSP_FORMAT_TUPLE = 15
SSP_FORMAT_TYPED_LIST = 16
SSP_FORMAT_TYPED_LIST_FIXEDSIZE = 17
SSP_FORMAT_CONCATERNATED_DATA = 18
SSP_FORMAT_FIXPOINT = 19
SSP_FORMAT_EXTEND = 20
SSP_FORMAT_SCALED = 23

formats_regIxs = [SSP_FORMAT_CONSTANT,
                  SSP_FORMAT_TYPED_MAP,
                  SSP_FORMAT_STRUCT,
                  SSP_FORMAT_TUPLE,
                  SSP_FORMAT_TYPED_LIST,
                  SSP_FORMAT_TYPED_LIST_FIXEDSIZE,
                  SSP_FORMAT_CONCATERNATED_DATA,
                  SSP_FORMAT_FIXPOINT,
                  SSP_FORMAT_EXTEND,
                  SSP_FORMAT_SCALED]

formats_regIxs_c_names = [
    'SSP_FORMAT_CONSTANT',
    'SSP_FORMAT_TYPED_MAP',
    'SSP_FORMAT_STRUCT',
    'SSP_FORMAT_TUPLE',
    'SSP_FORMAT_TYPED_LIST',
    'SSP_FORMAT_TYPED_LIST_FIXEDSIZE',
    'SSP_FORMAT_CONCATERNATED_DATA',
    'SSP_FORMAT_FIXPOINT',
    'SSP_FORMAT_EXTEND',
    'SSP_FORMAT_SCALED',
    'SSP_FORMAT_ANY',
    'SSP_FORMAT_MAP',
    'SSP_FORMAT_LIST']

SSP_TYPE_ANY = 21
SSP_TYPE_MAP = 22
SSP_TYPE_LIST = 25

builtin_types_regIx = basic_types_regIx + [SSP_TYPE_ANY, SSP_TYPE_MAP, SSP_TYPE_LIST]

##########################################
## Experimental support, not final value
SSP_TYPE_REF = 26
builtin_types_regIx += [SSP_TYPE_REF]


SSP_FIRST_GSCHEMA = 32


SSP_TYPE_BOOL_NULL = 0xFF
SSP_TYPE_UINT8_NULL = 0xFF
SSP_TYPE_UINT16_NULL = 0xFFFF
SSP_TYPE_INT16_NULL = -32768  #((int16_t)0x8000)
SSP_TYPE_INT32_NULL = -2147483648  #((int32_t)0x80000000)
SSP_TYPE_UINT32_NULL = 0xFFFFFFFF
SSP_TYPE_FLOAT_NULL = float('Inf')  #Actually should just look at the byte sequence

#This symbol code means the name follows as verbatim ASCII string
SYMBOL_ASCII = 1


##################################################
## Error codes

COR_OK = 0
COR_FAIL = 1
COR_OUT_OF_MEMORY = 2
COR_BUSY = 3
COR_NOT_DELIVERED = 4
COR_UNKNOWN_VARIABLE = 5
COR_ARGUMENT_ERROR = 6
COR_DATA_ERROR = 7

ERROR_CODES = {0: 'OK',
               1: 'Unspecified failure',
               2: 'Out of memory',
               3: 'Busy',
               4: 'Not delivered',
               5: 'Unknown variable',
               6: 'Argument error',
               7: 'Data error (data seems to be corrupted)',
               8: 'Blocked (unmet prerequisites)',
               9: 'Unknown definition',
               10: 'External error',
               11: 'Logical error',
               12: 'Unknown object',
               13: 'Too big data',
               14: 'Feature not supported',
               15: 'Text parsing error',
               16: 'Timeout',
               17: 'End of data',
               18: 'Out of resources',

               # These values are not error codes:
               127: 'Yield',
               128: 'OK Pending'}

##################################################
## Symbol metadata

# Configuration variables (not measurements).
# Variables not exposed to InfluxDB.
config_symbols = ['vars', 'funcs', 'events', 'funcSigs', 'components', 'name', 'serNo', 'class', 'parent', 'neig', 'autoSubs']

# Variables that are decimal numbers. All values for a variable sent
# to InfluxDB must be either integers or decimal numbers. Therefore,
# an integer must be converted to float if decimal numbers may follow
# later:
decimal_symbols = ['o3ppm']
