# SKETCH!
#
# Translate directly between SSP-BIN and native Python data types (pyValue).
# This is just an optimization, as pyObj serves well as an intermediate format.

# Also see sparvio_toolbox/parse.py for SSP-ASCII to pyValue conversions.

from .constants import *
from .bytebuffer import ByteIterator


#def sspImpBin_ReadValueWithType(typeIx, iterator):
#    if typeIx == SSP_FORMAT_NULL:
#        return

# Python representation of SSP types:
# SSP NULL => Null()  (or None or string 'null')
# SSP BOOL => bool
# SSP UINT8, INT8, UINT16, INT16, UINT32, INT32 => int
# SSP map => dict
# SSP list => list
# SSP constant reference => Ref()
# SSP schema => Schema()  ("schemaDef" according to sparvio_toolbox/parse.py)
# SSP symbol => string ? Sym()?
# SSP blob => string
# SSP string => string

class Schema(object):
    "An array of sspBin data that encodes a schema. May be self-contained, i.e. a constant"
    def __init__(self, data):
        self._data = data
    def get_typeIx(self):
        return SSP_TYPE_SCHEMA
    def write_impBin(self, iterator):
        iterator.write_size_and_data(self.data)
    def __repr__(self):
        return "Schema(" + repr(self._data) + ")"

class Ref(object):
    "Reference to a registry entry (constant/schema)"
    def __init__(self, index):
        self._index = index
    def get_typeIx(self):
        return SSP_TYPE_REF
    def write_impBin(self, iterator):
        iterator.write_regIx(self._index)
    def __repr__(self):
        return "Ref(" + str(self._index) + ")"

def impBin_decodePyValue(iterator, typeIx = SSP_FORMAT_ANY):
    "Reads an implicit value from <iterator> to a Python value"
    while typeIx == SSP_FORMAT_ANY:
        typeIx = iterator.read_regIx()

    if typeIx == SSP_TYPE_NULL:
        return Null
    if typeIx == SSP_TYPE_BOOL:
        return iterator.read_uint8() != 0
    if typeIx == SSP_TYPE_UINT8:
        return iterator.read_uint8()
    if typeIx == SSP_TYPE_UINT16:
        return iterator.read_uint16()
    if typeIx == SSP_TYPE_INT16:
        return iterator.read_int16()
    if typeIx == SSP_TYPE_INT32:
        return iterator.read_int32()
    if typeIx == SSP_TYPE_UINT32:
        return iterator.read_uint32()

    if typeIx == SSP_TYPE_SYMBOL:
        return iterator.read_symbol()

    if typeIx == SSP_TYPE_STRING:
        return iterator.read_string()

    if typeIx == SSP_TYPE_BLOB:
        return iterator.read_string()

    if typeIx == SSP_TYPE_SCHEMA:
        return Schema(iterator.read_size_and_buffer())

    if typeIx == SSP_FORMAT_MAP:
        count = iterator.read_uint8()
        _map = {}
        for i in range(count):
            key = impBin_decodePyValue(iterator)
            value = impBin_decodePyValue(iterator)
            _map[key] = value
        return _map

    if typeIx == SSP_FORMAT_LIST:
        count = iterator.read_uint8()
        _list = []
        for i in range(count):
            _list.append(impBin_decodePyValue(iterator))
        return _list

    if typeIx == SSP_TYPE_REF:
        return Ref(iterator.read_regIx())

    if typeIx in TheRegistry:
        return impBin_decodePyValue_schema(ByteIterator(TheRegistry.get(typeIx)), dataIter)

    raise UnknownConstant("Unknown type %s" % repr(typeIx))

def impBin_decodePyValue_schema(schemaIter, dataIter):
    typeIx = schemaIter.read_regIx()
    #Also handles SSP_FORMAT_ANY correctly
    if typeIx in builtin_types_regIx:
        return impBin_decodePyValue(dataIter, typeIx)
    if typeIx in TheRegistry:
        return impBin_decodePyValue_schema(ByteIterator(TheRegistry.get(typeIx)), dataIter)
    raise UnknownConstant("Unknown type %s" % repr(typeIx))

def encodePyValue(pyValue, out=None):
    "From Python data types, write expBin"
    if out is None:
        out = ByteIterator()
    if hasattr(pyValue, write_impBin):
        pyValue.write_regIx(pyValue.get_typeIx())
        pyValue.write_impBin(out)
        return out
    if isinstance(pyValue, string):
        out.write_regIx(SSP_TYPE_STRING)
        iterator.write_size_and_data(data)
        return out
    if isinstance(pyValue, bool):
        out.write_regIx(SSP_TYPE_BOOL)
        out.write_uint8(1 if pyValue else 0)
        return out
    if isinstance(pyValue, int):
        if pyValue >= 0 and pyValue < 256:
            out.write_regIx(SSP_TYPE_UINT8)
            out.write_uint8(pyValue)
        elif pyValue >= 0 and pyValue < 2**16:
            out.write_regIx(SSP_TYPE_UINT16)
            out.write_uint16(pyValue)
        elif pyValue >= -2**15 - 1 and pyValue < 2**15:
            out.write_regIx(SSP_TYPE_INT16)
            out.write_int16(pyValue)
        elif pyValue >= 0 and pyValue < 2**32:
            out.write_regIx(SSP_TYPE_UINT32)
            out.write_uint32(pyValue)
        elif pyValue >= -2**31-1 and pyValue < 2**31:
            out.write_regIx(SSP_TYPE_INT32)
            out.write_int32(pyValue)
        else:
            raise Exception("Can't encode large integer %d" % pyValue)
        return out
    if isinstance(pyValue, float):
        out.write_regIx(SSP_TYPE_FLOAT)
        out.write_float(pyValue)
        return out
    raise Exception("Cant encode unknown type %s for value %s" % (type(pyValue), pyValue))

def encodePyValue_with_schema(pyValue, schemaIter, out=None):
    if out is None:
        out = ByteIterator()

if __name__ == "__main__":
    assert impBin_decodePyValue(ByteIterator("\x05"), SSP_TYPE_BOOL) == True
    assert impBin_decodePyValue(ByteIterator("\x05"), SSP_TYPE_UINT8) == 5
    assert impBin_decodePyValue(ByteIterator("\x05\x00"), SSP_TYPE_UINT16) == 5
    assert impBin_decodePyValue(ByteIterator("\x05\x01"), SSP_TYPE_UINT16) == 5 + 256
