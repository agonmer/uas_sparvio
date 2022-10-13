"""pyObjects.py: Represents SSP-BIN schemas and values with Python classes
Values in this format are called "pyObj".
This format doesn't use native Python data types.
"""

import traceback
import sys
import typing

from .constants import *
from .bytebuffer import *
from . import ontology
from .ontology import global_ontology
from .source import no_source

debug_decoding = False
indent = 0
def pr(*args):
    print(' ' * (indent*4), *args)

# All objects are immutable.

# All built-in types have their own Python class.
# All ontology-defined types and all values are Python objects.

# repr() of pyObjects returns SSP-ASCII

#TODO: SSP-BIN can't differentiate between empty value and null for
#strings and blobs. This implementation does. (Add this feature to
#SSP-BIN or remove it from here?)

#TODO: Bool null is also a hazy concept.

# Verbosity levels for to_sspAscii():
V_MINIMAL = 0  #exclude label, type. Structs exclude keys ({} encoded as []).
V_TERSE = 1  #exclude label and type. Decoding is expected to know the type. (used inside labelled struct). Structs include keys
V_NORMAL = 2  #include label if present (and exclude keys), or include type if ambigious
V_VERBOSE = 3  #always include type. Include label if present.

####################
## Helper classes and functions

class TypeException(Exception):
    "Mismatching types"
    pass

class BinaryFormatException(Exception):
    "Syntax error when parsing from SSP-BIN, or logical error when writing to SSP-BIN"
    pass

class UnknownRegIxException(Exception):
    "Raised when trying to handle (decode) a regIx that is unknown"
    #Can catch this exception to query for the regIx definition and try again
    def __init__(self, regIx):
        self.regIx = regIx

def is_null(val):
    if isinstance(val, SspPyObj):
        return val.is_null()
    return val is None

def is_close(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


####################
## SspPyObj

class SspPyObj(object):
    """Base class for Python Object representation of SSPT data.  This
    class may not be instantiated directly, always through a subclass.
    """
    def __init__(self, _type : typing.Optional["SspPyObj"],
                 regIx : int = None,
                 label : str = None,
                 c_name : str = None):
        """_type is a pyObj for the SSPT type of this data (or
           None). regIx is an integer, if there's a registry entry for
           this data."""
        self.regIx = regIx  #None if no regIx with this value is known
        self._type = _type
        self._label = label
        self.c_name = c_name
        self.source = no_source #Set to trace where this object was created from

    def get_regIx(self):
        "Returns the registry entry for this value, if there is any"
        #assert self._regIx
        return self.regIx
    def has_ref_string(self):
        return True if (self._label or self.regIx) else False
    def get_ref_string(self):
        if self._label:
            return self._label
        if self.regIx:
            return "REF%d" % self.regIx
        raise TypeException("No reference exists")
    def get_type(self):
        "Returns the SspPyObj representing the schema of this value"
        assert self._type is not None
        return self._type
    def get_null(self):
        raise Exception("get_null() not implemented for %s" % \
                        self.to_sspAscii(V_VERBOSE))
    def from_impBin(self, iterator):  #Probably overload for schemas
        "Factory method to create a pyObj of this type, by reading implicit SSP-BIN from <iterator> (implicitly with this schema)"
        #By default, assumes the value is a constant, so no decoding is necessary
        return self
    def to_expBin(self, iterator):
        #NullType overrides this
        if self.regIx is not None:
            iterator.write_regIx(SSP_TYPE_REF)
            iterator.write_regIx(self.regIx)
            return
        iterator.write_regIx(self.get_type().get_regIx())
        self.to_impBin(iterator)
    def to_impBin(self, iterator):    #Probably overload for values
        "Write this value as impBin with the current type"
        raise Exception("No encoding of %s defined" %
                        self.to_sspAscii(V_VERBOSE))
    def to_schemaBin(self, iterator):
        """schemaBin is the definition of the value (a regIx or a
           format type followed by complete parameters)"""
        raise Exception("Not implemented for %s" % self.to_sspAscii(V_VERBOSE))
    def from_pyValue(self, value):  #Probably overload for types
        "Create a pyObj with this pyObj as type, from a Python value"
        if isinstance(value, SspPyObj):
            return value.cast_to(self, require_expressible=False)
        raise Exception("No conversion from Python to %s defined" %
                        self.to_sspAscii(V_VERBOSE))
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        raise Exception("Creating from SSP-ASCII args not defined for %s" %
                        self.to_sspAscii(V_VERBOSE))
    def cast_to(self, schemaObj, source=no_source,
                require_expressible=False):
        "Casts this value to another schema, returning the cast value. <require_expressible> only allows casting that allow impBin with <schemaObj> as implied type (that is, "
        #Partially overload for values.
        if schemaObj == ref_type:
            if self.regIx is not None:
                return self  #All registry entries are usable as references
        if schemaObj == any_type:
            return self
        if self.equals(schemaObj):
            #No types can be encoded as impBin with themselves as implied type
            #(impBin can only express *values* of a type, not the type itself)
            if require_expressible and schemaObj.is_type():
                #(Null is allowed, but null is not 'type' in this sense.)
                raise source.error("Can't cast %s to %s with require_expressible" %
                                   (self.to_sspAscii(V_VERBOSE),
                                    schemaObj.to_sspAscii(V_VERBOSE)))
            return self
        if self.get_type() == schemaObj:
            return self  #No casting necessary
        if schemaObj.is_null() and self.is_null():
            return self
        raise source.error("No conversion defined to cast %s to schema %s" % \
                           (self.to_sspAscii(V_VERBOSE),
                            schemaObj.to_sspAscii(V_VERBOSE)))
    def to_pyValue(self):
        """Converts the value to a native Python value if possible. If not
           possible, in particular for types, the pyObject object is
           returned
        """
        return self  #If not overridden, continue to use pyObject also as native Python value
        #raise TypeException("No translation to Python value defined for %s" %
        #                    self.to_sspAscii(V_VERBOSE))

    def is_null(self):
        return False  #Override!
    def is_atomic_value(self):
        return False  #Override!
    def is_type(self):
        "If this pyObj is a type; meaning it requires datum to decode a value. In this sense, Null is not a type"
        return False  #Default to 'no'
    def is_atomic_type(self):
        "If objects with this pyObj as type are guaranteed atomic"
        return False  #Defaults to 'no'
    def is_structured_type(self):
        "If objects with this pyObj as type are structured (can resolve an index)"
        return False  #Default to 'no'
    def to_sspAscii(self, verbose=V_NORMAL):
        if self._label:
            return self._label
        return object.__repr__(self)
    def lookup(self, key):
        "For structured data, lookup a part (pyObj) by key (pyObj(?) or native)"
        #Override!
        raise Exception("No lookup possible in %s" % self.to_sspAscii(V_VERBOSE))
    def equals(self, obj):
        "Return true if structurally the same. <obj> may be pyObj or pyValue (but not SSP-ASCII or SSP-BIN). Don't compare label."
        if self == obj:
            return True
        if (isinstance(obj, SspPyObj) and
            self.regIx is not None and self.regIx == obj.regIx):
            return True
        return False  #Default to 'no'
    def __repr__(self):
        return self.to_sspAscii()

class TypePyObj(SspPyObj):
    "Superclass to all type objects (type = requires datum to decode value)"
    def to_expBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_CONSTANT)
        self.to_schemaBin()
    def is_null(self):
        return False  #No type is 'null' (except null itself)
    def to_impBin(self, iterator):
        "Write this value as impBin"
        #impBin with type 'schema' == schemaBin
        self.to_schemaBin(iterator)
    def to_schemaBin(self, iterator):
        "Write the type"
        # Schema for basic types is not stored in the registry, but
        # can be used in other places.
        # Override for format schemas.
        iterator.write_regIx(self.regIx)
    def is_type(self):
        return True

class BasicTypePyObj(TypePyObj):
    def is_atomic_value(self):
        return True

class FormatPyObj(SspPyObj):
    """Base class of formats. Formats require additional parameters (not
       included) to become a schema"""
    #Subclasses must define:
    #def from_sspAscii_args(self, string, bracket_char, source)
    def from_schemaBin(self, iterator):
        "Return a FormatSchemaPyObj by reading the parameters from iterator"
        raise Exception("Not implemented for this type")
    def to_expBin(self, iterator):
        raise Exception("Format can't occur in isolation in expBin")

class FormatSchemaPyObj(TypePyObj):
    "Base class for format schemas (format + specific parameters)"
    def to_schemaBin(self, iterator):
        "Write the type"
        #Override for each format schema to write the parameters!
        raise Exception("Override for format %s!" % self)

class ValuePyObj(SspPyObj):
    "Base class of non-type (fully specified) values"
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_CONSTANT)
        self.to_expBin(iterator)
    def from_pyValue(self, value):
        "For value object, this is the same as comparing values"
        if self.equals(value):
            return self
        raise Exception()

class AtomicValuePyObj(ValuePyObj):
    def is_atomic_value(self):
        return True

class StructuredValuePyObj(ValuePyObj):  #Replace by "non-hashable"?
    def is_null(self):
        return False


######################################################################

class NullClass(SspPyObj):
    "Null is a special case -- in SSP-BIN it is both a type and a value"
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_NULL, "Null", "SSP_TYPE_NULL")
    def to_impBin(self, iterator):
        return #No data
    def to_expBin(self, iterator):
        iterator.write_regIx(SSP_TYPE_NULL)
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_TYPE_NULL)
    def to_pyValue(self):
        return None  #SSPT Null is translated to Python None
    def from_pyValue(self, value):
        if isinstance(value, SspPyObj) and value.is_null():
            return null
        if value is None:
            return null
        raise TypeException("Expected None")
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        return schemaObj.get_null()
    def is_null(self):
        return True
    def is_atomic_value(self):
        return True
    def is_atomic_type(self):
        return False #?
    def equals(self, obj):
        return obj.is_null()
null = NullClass()  #No difference between type Null and value Null

class BoolTypeClass(BasicTypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_BOOL, "Bool", "SSP_TYPE_BOOL")
        self._null = None
    def from_impBin(self, iterator):
        return Bool(iterator.read_uint8())
    def from_pyValue(self, value):
        if value is None:
            return self.get_null()
        if isinstance(value, int):
            if value < 0 or value > 1:
                raise TypeException()
            return Bool(value != 0)
        if not isinstance(value, bool):
            raise TypeException()
        return Bool(value)
    def get_null(self):
        if self._null is None:
            self._null = Bool(SSP_TYPE_BOOL_NULL)
        return self._null
    def is_atomic_type(self):
        return True
bool_type = BoolTypeClass()

class Bool(AtomicValuePyObj):
    def __init__(self, value):
        SspPyObj.__init__(self, bool_type)
        if value == SSP_TYPE_BOOL_NULL:
            self.value = SSP_TYPE_BOOL_NULL
        else:
            self.value = bool(value)
    def to_impBin(self, iterator):
        #Handle null?
        iterator.write_uint8(1 if self.value else 0)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if isinstance(schemaObj, IntTypeClass):
            if self.is_null():
                return schemaObj.get_null()
            return schemaObj.from_pyValue(1 if self.value else 0)
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        if self.is_null():
            return "null"
        return self.value
    def is_null(self):
        return self.value == SSP_TYPE_BOOL_NULL
    def equals(self, obj):
        if self.is_null():
            return is_null(obj)
        if isinstance(obj, bool):
            return self.value == obj
        if isinstance(obj, Bool):
            return self.value == obj.value
        #TODO: Should compare with integer 0 and 1 too
        return False
    def to_sspAscii(self, verbose=V_NORMAL):
        #Type of bool values is obvious
        if self.value == SSP_TYPE_BOOL_NULL:
            if verbose >= V_VERBOSE:
                return "Bool(null)"
            return "null"
        return "true" if self.value else "false"

class IntTypeClass(BasicTypePyObj):
    "Base class for integer types"
    def __init__(self, _min, _max, null, regIx, label, c_name):
        SspPyObj.__init__(self, None, regIx, label, c_name)
        self._min = _min
        self._max = _max
        self._null_value = null
        self._null_object = None
        self._instanceClass = None  #Can't init here -- circular reference
    def from_pyValue(self, value):
        if value is None:
            return self.get_null()
        if (not isinstance(value, int)) or value < self._min or value > self._max:
            raise TypeException("Can't create pyObj %s from %s" % \
                                (self._label, repr(value)))
        return self._instanceClass(value)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        if bracket_char != '(':
            raise source.error("%s only supports () argument" % token)
        num = StringIterator(string).read_numeric()
        if num is None:
            raise source.error("Error parsing %s value" % token)
        return self.from_pyValue(eval(num))
    def get_null(self):
        if self._null_object is None:
            self._null_object = self._instanceClass(self._null_value)
        return self._null_object
    def is_default_class_for(self, value):
        assert False  #Must override
    def is_atomic_type(self):
        return True

class Int(AtomicValuePyObj):
    "Must inherit this class for specific integer types"
    def __init__(self, typeClass, value):
        SspPyObj.__init__(self, typeClass)
        self.value = int(value)
    def to_impBin(self, iterator):
        self.get_type().encode_value_to(iterator, self.value)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if schemaObj == self.get_type():
            return self #No conversion
        if self.is_null():
            return schemaObj.get_null()
        if isinstance(schemaObj, IntTypeClass):
            #Try to cast -- raises exception if it fails
            return schemaObj.from_pyValue(self.value)
        if schemaObj == bool_type:
            if self.value == 0 or self.value == 1:
                return bool_type.from_pyValue(self.value)
            raise source.error("Cant cast value %d to bool" % self.value)
        if schemaObj == float_type:
            return Float(self.value)
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        if self.is_null():
            return "null"
        return self.value
    def is_null(self):
        return self.value == self.get_type()._null_value
    def equals(self, obj):
        if self.is_null():
            return is_null(obj)
        if isinstance(obj, Int) or isinstance(obj, Float) or \
           isinstance(obj, Fixpoint) or isinstance(obj, Scaled):
            return self.value == obj.to_pyValue()
        return self.value == obj
    def to_sspAscii(self, verbose=V_NORMAL):
        if self.is_null():
            if verbose > V_NORMAL:
                return self.get_type()._label + "(null)"
            return "null"
        elif verbose < V_NORMAL or \
             (verbose == V_NORMAL and \
              self.get_type().is_default_class_for(self.value)):
            return str(self.value)
        return self.get_type()._label + "(" + str(self.value) + ")"

class Uint8TypeClass(IntTypeClass):
    def __init__(self):
        IntTypeClass.__init__(self, 0, 255, SSP_TYPE_UINT8_NULL,
                              SSP_TYPE_UINT8, "Uint8", "SSP_TYPE_UINT8")
    def from_impBin(self, iterator):
        return self._instanceClass(iterator.read_uint8())
    def encode_value_to(self, iterator, value):
        iterator.write_uint8(value)
    def is_default_class_for(self, value):
        return value >= 0 and value < 255
uint8_type = Uint8TypeClass()
class Uint8(Int):
    def __init__(self, value):
        Int.__init__(self, uint8_type, value)
uint8_type._instanceClass = Uint8

class Uint16TypeClass(IntTypeClass):
    def __init__(self):
        IntTypeClass.__init__(self, 0, 2**16 - 1, SSP_TYPE_UINT16_NULL,
                              SSP_TYPE_UINT16, "Uint16", "SSP_TYPE_UINT16")
    def from_impBin(self, iterator):
        return self._instanceClass(iterator.read_uint16())
    def encode_value_to(self, iterator, value):
        iterator.write_uint16(value)
    def is_default_class_for(self, value):
        return value >= 255 and value < 65535
uint16_type = Uint16TypeClass()
class Uint16(Int):
    def __init__(self, value):
        Int.__init__(self, uint16_type, value)
uint16_type._instanceClass = Uint16

class Int16TypeClass(IntTypeClass):
    def __init__(self):
        IntTypeClass.__init__(self, -2**15, 2**15 - 1, SSP_TYPE_INT16_NULL,
                              SSP_TYPE_INT16, "Int16", "SSP_TYPE_INT16")
    def from_impBin(self, iterator):
        return self._instanceClass(iterator.read_int16())
    def encode_value_to(self, iterator, value):
        iterator.write_int16(value)
    def is_default_class_for(self, value):
        return value > -65536 and value < 0
int16_type = Int16TypeClass()
class Int16(Int):
    def __init__(self, value):
        Int.__init__(self, int16_type, value)
int16_type._instanceClass = Int16

class Uint32TypeClass(IntTypeClass):
    def __init__(self):
        IntTypeClass.__init__(self, 0, 2**32 - 1, SSP_TYPE_UINT32_NULL,
                              SSP_TYPE_UINT32, "Uint32", "SSP_TYPE_UINT32")
    def from_impBin(self, iterator):
        return self._instanceClass(iterator.read_uint32())
    def encode_value_to(self, iterator, value):
        iterator.write_uint32(value)
    def is_default_class_for(self, value):
        return value >= 65536
uint32_type = Uint32TypeClass()
class Uint32(Int):
    def __init__(self, value):
        Int.__init__(self, uint32_type, value)
uint32_type._instanceClass = Uint32

class Int32TypeClass(IntTypeClass):
    def __init__(self):
        IntTypeClass.__init__(self, -2**31, 2**31 - 1, SSP_TYPE_INT32_NULL,
                              SSP_TYPE_INT32, "Int32", "SSP_TYPE_INT32")
    def from_impBin(self, iterator):
        return self._instanceClass(iterator.read_int32())
    def encode_value_to(self, iterator, value):
        iterator.write_int32(value)
    def is_default_class_for(self, value):
        return value <= -65536
int32_type = Int32TypeClass()
class Int32(Int):
    def __init__(self, value):
        Int.__init__(self, int32_type, value)
int32_type._instanceClass = Int32

class FloatTypeClass(BasicTypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_FLOAT, "Float", "SSP_TYPE_FLOAT")
        self._null = FloatNull(self)
    def from_pyValue(self, value):
        return Float(value) #Might raise exception
    def from_impBin(self, iterator):
        return Float(iterator.read_float())
    def get_null(self):
        return self._null
    def is_atomic_type(self):
        return True

class FloatNull(AtomicValuePyObj):
    def __init__(self, float_type):
        SspPyObj.__init__(self, float_type)
    def to_impBin(self, iterator):
        iterator.write_float(SSP_TYPE_FLOAT_NULL)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        return schemaObj.get_null()
    def to_pyValue(self):
        return None
    def is_null(self):
        return True
    def equals(self, obj):
        return is_null(obj)
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose > V_NORMAL:
            return "Float(null)"
        return "null"

float_type = FloatTypeClass()

class Float(AtomicValuePyObj):
    def __init__(self, value):
        SspPyObj.__init__(self, float_type)
        try:
            self.value = float(value)
        except:
            raise TypeException("Can't convert %s to Float" % repr(value))
    def to_impBin(self, iterator):
        iterator.write_float(self.value)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #TODO: Fixpoints
        if isinstance(schemaObj, IntTypeClass):
            return schemaObj.from_pyValue(int(self.value))
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        if self.is_null():
            return "null"
        return self.value
    def equals(self, obj):
        try:  #try block, in case obj is not a number
            if isinstance(obj, SspPyObj):
                return is_close(self.value, obj.to_pyValue())
            return is_close(self.value, obj)
        except:
            return False
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose > V_NORMAL:
            return "Float(%s)" % repr(self.value)
        return str(float(self.value))

class SymbolTypeClass(BasicTypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_SYMBOL, "Symbol", "SSP_TYPE_SYMBOL")
    def from_impBin(self, iterator):
        symIx = iterator.read_symbol()
        if symIx == 0:
            raise Exception('Error decoding symbol 0')
        if symIx == SYMBOL_ASCII:
            name = iterator.read_string()
            symObj = global_ontology.name_to_symbol(name, create=False)
            if symObj is None:
                raise Exception('Cannot decode unknown symbol "%s" from ASCII',
                                name)
            return symObj
        symObj = global_ontology.ix_to_symbol(symIx)
        if symObj is None:
            raise Exception('Cannot decode unknown symbol %d' % symIx)
        return symObj
    def from_pyValue(self, value):
        if isinstance(value, Symbol):
            return value
        # Assumes <value> is a string
        return global_ontology.name_to_symbol(value)
    def is_atomic_type(self):
        return True
symbol_type = SymbolTypeClass()

# Improve performance for commonly used strings. If loaded from an
# ontology file, the strings are not interned as constant strings
# would be, so do it explicitly.
def intern(string_or_none):
    if string_or_none is not None:
        return sys.intern(string_or_none)
    return None

class Symbol(AtomicValuePyObj):
    "Only create a Symbol object from the ontology or the first time encountering a symbol, to make Symbols singletons. Either index, name or both must be specified."
    def __init__(self, index=None, name=None, _type=None,
                 unit=None, long_name=None, doc=None):
        "None values for optional parameters mean that the values are unknown, not empty"
        assert index is not None or name is not None
        if index is not None:
            assert type(index) is int
        SspPyObj.__init__(self, symbol_type)
        self.index = index
        self.name = intern(name)
        self.symbol_type = intern(_type)
        self.unit = intern(unit)
        self.long_name = long_name
        self.doc = doc
    def add_info(self, symbol):
        "Copy the metadata from <symbol> to this symbol"
        if symbol.index is not None:
            self.index = symbol.index
        self.name = symbol.name
        if symbol.symbol_type:
            self.symbol_type = symbol.symbol_type
        if symbol.unit:
            self.unit = symbol.unit
        if symbol.long_name:
            self.long_name = symbol.long_name
        if symbol.doc:
            self.doc = symbol.doc
        if symbol.c_name:
            self.c_name = symbol.c_name
    def to_impBin(self, iterator):
        if self.index is None:
            raise self.source.error("Symbol %s lacks index" % self)
        iterator.write_symbol(self.index)
    def to_pyValue(self):
        if self.name is not None:
            return self.name
        return "SYM%d" % self.index
    def is_null(self):
        return False  #Could use SSPSYMBOL_NULL
    def equals(self, obj):
        if isinstance(obj, Symbol):
            if self.index is not None and self.index == obj.index:
                return True
            return self.name == obj.name
        if isinstance(obj, str):
            if obj.startswith("SYM"):
                return self.index == int(obj[3:])
            return self.name == obj
        return False
    def to_sspAscii(self, verbose=V_NORMAL):
        if self.name is not None:
            if verbose > V_NORMAL:
                if self.index is not None:
                    return "Symbol(%d,%s)" % (self.index, self.name)
                return 'Symbol(%s)' % (self.name)
            return self.name
        return "SYM%d" % self.index

class StringTypeClass(BasicTypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, self, SSP_TYPE_STRING, "String", "SSP_TYPE_STRING")
    def from_impBin(self, iterator):
        return String(iterator.read_string())
    def from_pyValue(self, value):
        return String(str(value))
    def is_atomic_type(self):
        return True
    def __call__(self, data):
        "Create a String"
        return String(data)
string_type = StringTypeClass()

class String(AtomicValuePyObj):
    def __init__(self, _string, regIx=None):
        SspPyObj.__init__(self, string_type, regIx)
        assert isinstance(_string, str)
        self._string = _string
    def to_impBin(self, iterator):
        #If UTF-8, calculate byte count differently?
        iterator.write_uint8(len(self._string))
        iterator.write(self._string)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if schemaObj == blob_type:
            return blob_type(self._string)
        if schemaObj == symbol_type:
            val = symbol_type.from_pyValue(self._string)
            if val is None:
                print("Warning: Can't convert string '%s' to symbol" %
                      self._string)
            if val is not None:
                return val
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        return self._string
    def is_null(self):
        return self._string == None  #TODO: null string is not well-defined
    def equals(self, obj):
        if isinstance(obj, SspPyObj):
            if self.regIx is not None and self.regIx == obj.regIx:
                return True
            if isinstance(obj, Blob):
                return self._string == obj.data
            return (isinstance(obj, String) and self._string == obj._string)
        if isinstance(obj, str):
            return self._string == obj
        return False
    def to_sspAscii(self, verbose=V_NORMAL):
        #Enclose string in "" to distinguish between strings and
        #symbols. This is in line with converting from sspAscii but
        #looks odd when printed as an isolated Python value, as Python
        #adds an extra '' around the value.
        return '"%s"' % repr(self._string)

def parse_hex(ascii):
    ascii = ascii.lstrip()
    if ascii[:2] != '0x':
        raise Exception()
    ascii = ascii[2:]  #Remove '0x'
    #Warning: The result will look like a string but is actually binary data
    val = bytearray()
    while True:
        if len(ascii) < 2:
            return (bytes(val), ascii)
        try:
            val.append(int(ascii[:2], 16))
        except:
            return (bytes(val), ascii)
        ascii = ascii[2:]

class BlobTypeClass(BasicTypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, self, SSP_TYPE_BLOB, "Blob", "SSP_TYPE_BLOB")
    def __call__(self, data):
        "Create a Blob"
        return Blob(data)
    def from_pyValue(self, value):
        if isinstance(value, bytes):
            return Blob(value) # <value> is already raw bytes
        if not isinstance(value, str):
            raise TypeException()
        if not value.startswith("0x"):
            return Blob(value)  #String
        (data, rest) = parse_hex(value)
        if rest:
            raise TypeException()  #Couldn't parse all bytes
        return Blob(data)
    def from_impBin(self, iterator):
        return Blob(bytes(iterator.read_size_and_buffer()))
    def is_atomic_type(self):
        return True
blob_type = BlobTypeClass()

class Blob(AtomicValuePyObj):
    "Stores binary data as a string" #Watch out for UTF-8!
    def __init__(self, data : bytes, regIx=None):
        SspPyObj.__init__(self, blob_type, regIx)
        assert isinstance(data, bytes)
        self.data : bytes = data
    def to_impBin(self, iterator):
        #If UTF-8, calculate byte count differently?
        iterator.write_uint8(len(self.data))
        iterator.write(self.data)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if schemaObj == string_type:
            return String(self.data)
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        return self.data  #Casts to string.. oh well
    def is_null(self):
        return self.data == None  #TODO: null blob is not well-defined
    def equals(self, obj):
        if isinstance(obj, SspPyObj):
            if self.regIx is not None and self.regIx == obj.regIx:
                return True
            if isinstance(obj, Blob):
                return self.data == obj.data
            if isinstance(obj, String):
                return self.data == obj._string
            return False
        if isinstance(obj, str):
            return self.data == obj
        return False
    def to_sspAscii(self, verbose=V_NORMAL):
        return '0x%s' % ''.join(['%02x' % x for x in self.data])

#SCHEMA
class SchemaTypeClass(BasicTypePyObj):
    "The singleton 'Schema'. Instances of SchemaType are not special objects in pyObj, but expressed as other types. Schema is only needed for SSP-BIN."
    def __init__(self):
        SspPyObj.__init__(self, self, SSP_TYPE_SCHEMA, "Schema", "SSP_TYPE_SCHEMA")
    #Can't create schema from Python value, as there's no mapping
    #between Python values and SSP schemas
    def from_impBin(self, iterator):
        #Read the schema of any SSP-BIN
        return from_schemaBin(iterator)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        "Create a schema (type object) given a sspAscii argument"
        from . import ascii
        element_iter = StringIterator(string)
        #Schema objects are natively supported as pyObj, so there's no
        #explicit Schema wrapper object:
        args = ascii.list_to_pyObj(element_iter, source=source)
        if len(args) > 1:
            raise source.error("Only one Schema element allowed")
        return args[0]
    def is_atomic_type(self):
        return True
schema_type = SchemaTypeClass()


class RefTypeClass(BasicTypePyObj):
    "The singleton 'REF' type"
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_REF, "Ref", "SSP_TYPE_REF")
    def from_pyValue(self, value):
        if isinstance(value, SspPyObj):
            if value.regIx is None:
                raise TypeException("pyObj %s doesn't have regIx" % value.to_sspAscii(V_VERBOSE))
            return value
        if isinstance(value, str):
            pyObj = global_ontology.label_to_registry_entry(value)
            if pyObj is None:
                raise TypeException()
            return pyObj
        return BasicTypePyObj.from_pyValue(value)
    def from_impBin(self, iterator):
        regIx = iterator.read_regIx()
        pyObj = global_ontology.get_by_regIx(regIx)
        if pyObj is None:
            raise UnknownRegIxException(regIx)
        return pyObj
    def to_sspAscii(self, verbose=V_NORMAL):
        return "Ref"
ref_type = RefTypeClass()

class Ref(SspPyObj):  #Should inherit from ValuePyObj? Can be either value or type
    "A reference to the registry, where the definition isn't necessarily known"
    # Not necessary to use for named registry entries, as those
    # pyObjects can be used directly
    def __init__(self, regIx):
        # The regIx of *this* object is not the same as the regIx it
        # refers to. This enables aliases to make semantic
        # distinctions
        SspPyObj.__init__(self, ref_type, regIx=None)
        self.refRegIx = regIx
    def to_impBin(self, iterator):
        self.to_schemaBin(iterator)
    def to_schemaBin(self, iterator):
        # The definition of a ref is the regIx that it refers to
        iterator.write_regIx(self.refRegIx)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #No casting defined
        #TODO: If definition is known, try to cast the definition instead
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def from_impBin(self, iterator):
        obj = global_ontology.get_by_regIx(self.refRegIx)
        #If this is a Ref to a type, decode with that type.
        if obj.is_type():
            value = obj.from_impBin(iterator)
            return RefInstance(self, value)
        #Otherwise, no decoding is necessary; return this object itself
        return self
    #def to_pyValue(self):
    def is_null(self):
        return self.refRegIx == 0
    def is_atomic_value(self):
        return False  #Doesn't necessarily refer to atomic value... but the ref itself is atomic, isn't it...?
    def from_pyValue(self, value):
        obj = global_ontology.get_by_regIx(self.refRegIx)
        return RefInstance(self, obj.from_pyValue(value))
    def to_sspAscii(self, verbose=V_NORMAL):
        if self.is_null():
            return "null"
        #if self.regIx:
        #    return "%d:REF%d" % (self.regIx, self.refRegIx)
        if self._label:
            return self._label
        return "REF%d" % self.refRegIx

# An alternative to RefInstance would be to make every other object
# have an 'alias' field. For example Id(3) is Uint8(3) but uses
# alias=Id. But that could make it difficult to implement custom
# handling of some reference types.
class RefInstance(SspPyObj):
    """A RefInstance is a value of a Ref type. The Ref type refers to some
       other SspPyObj type object (an alias)."""
    def __init__(self, ref : Ref, value : SspPyObj):
        super().__init__(_type = ref)
        self._value = value
    def cast_to(self, schemaObj, source=no_source,
                require_expressible=False):
        if schemaObj == any_type:
            return self
        return self._value.cast_to(schemaObj, source, require_expressible)
    def to_impBin(self, iterator):
        self._value.to_impBin(iterator)
    def to_pyValue(self):
        return self._value.to_pyValue()
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose >= V_VERBOSE:
            return self._type.to_sspAscii() + '(' + \
                self._value.to_sspAscii(V_MINIMAL) + ')'
        return self._value.to_sspAscii(verbose)


######################################################################
## Parameter format types

# These format types are never handled in their general form. Instead
# a ..TypeClass is created with parameters, from factory functions.

#SSP_FORMAT_CONSTANT
# Constants are natively represented as pyObjects, thus there's no
# need for objects. This class only decodes from schemaBin.
class _TheConstantTypeClass(FormatPyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_FORMAT_CONSTANT, "Const", "SSP_FORMAT_CONSTANT")
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_CONSTANT:
            raise Exception()
        #For format schemas, this creates an anonymous pyObj (not in the registry)
        typeObj = from_schemaBin(iterator)
        return typeObj.from_impBin(iterator)
constant_format = _TheConstantTypeClass()

#SSP_FORMAT_TYPED_MAP
class _TheTypedMapTypeClass(FormatPyObj):
    "Singleton: The format 'TypedMap'"
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_FORMAT_TYPED_MAP, "TypedMap", "SSP_FORMAT_TYPED_MAP")
    def __call__(self, key_type, value_type):
        "Create a TypedMap type"
        return TypedMapTypeClass(key_type, value_type)
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_TYPED_MAP:
            raise Exception()
        key_type = from_regIx(iterator)
        value_type = from_regIx(iterator)
        return TypedMapTypeClass(key_type, value_type)

    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        "Takes two arguments: key type and value type"
        from . import ascii
        if bracket_char != '(':
            raise source.error("TypedMap only supports () argument")
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source=source)
        if len(args) != 2:
            raise source.error("TypedMap requires two arguments")
        return TypedMapTypeClass(args[0], args[1])
typed_map_format = _TheTypedMapTypeClass()

class TypedMapTypeClass(FormatSchemaPyObj):
    "A particular map type"
    def __init__(self, key_type, value_type, regIx = None):
        "elements is list of tuples (name, type) where name is Symbol and type is a pyObj"
        SspPyObj.__init__(self, None, regIx)
        self._key_type = key_type
        self._value_type = value_type
    def from_impBin(self, iterator):
        count = iterator.read_uint8()
        if debug_decoding:
            pr("TypedMap %s with %d elements" %
               (self.to_sspAscii(V_TERSE), count))
            global indent
            indent += 1
        values = []
        for i in range(count):
            if debug_decoding:
                pr("TypedMap will decode key of type", self._key_type)
                iterator.push_savepoint()
            key = self._key_type.from_impBin(iterator)
            if debug_decoding:
                pr("%s => TypedMap index %d (max %d) key = %s" %
                   (iterator.pop_savepoint_hex(), i, count-1,
                    key.to_sspAscii(V_TERSE)))
                pr("TypedMap will decode value of type ",
                   self._value_type.to_sspAscii(V_VERBOSE))
                iterator.push_savepoint()
            value = self._value_type.from_impBin(iterator)
            if debug_decoding:
                pr("%s => TypedMap index %d (max %d) value = %s" %
                   (iterator.pop_savepoint_hex(), i, count-1,
                    value.to_sspAscii(V_TERSE)))
            values.append( (key, value) )
        if debug_decoding:
            indent -= 1
        return TypedMap(self, values)
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_TYPED_MAP)
        if self._key_type.get_regIx() is None:
            raise BinaryFormatException("TypedList to_schemaBin() not possible when member key type %s doesn't have a regIx" % self._key_type.to_sspAscii(V_VERBOSE))
        iterator.write_regIx(self._key_type.get_regIx())
        if self._value_type.get_regIx() is None:
            raise BinaryFormatException("TypedList to_schemaBin() not possible when member value type doesn't have a regIx")
        iterator.write_regIx(self._value_type.get_regIx())
    def __call__(self, fields, regIx = None):
        obj = self.from_pyValue(fields)
        obj.regIx = regIx
        return obj
    def from_pyValue(self, value):
        "value is a Python dictionary of Python values"
        if not isinstance(value, dict):
            raise TypeException("Can only cast dictionaries to TypedMap")
        lst = []  #List of tuples of pyObjects
        for (key,val) in value.items():
            cast_key = self._key_type.from_pyValue(key)
            cast_value = self._value_type.from_pyValue(val)
            lst.append( (cast_key, cast_value) )
        return TypedMap(self, lst)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        element_iter = StringIterator(string)
        keys_are_symbols = (self._key_type == symbol_type)
        args = ascii.dict_to_pyObj(element_iter,
                                   keys_are_symbols=keys_are_symbols,
                                   source=source)
        for i in range(len(args)):
            (key, val) = args[i]
            args[i] = (key.cast_to(self._key_type, source),
                       val.cast_to(self._value_type, source,
                                   require_expressible=True))
        return TypedMap(self, args)
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose <= V_NORMAL and self._label:
            return self.get_ref_string()
        return "TypedMap(%s, %s)" % (self._key_type.to_sspAscii(verbose), self._value_type.to_sspAscii(verbose))
    def is_structured_type(self):
        return True

class TypedMap(StructuredValuePyObj):
    "Since SSP maps are ordered, Python dict is not used"
    def __init__(self, typeObj, items, regIx=None):
        "<typeObj> is a TypedMapTypeClass. <items> is a python list of tuples of (pyObj key, pyObj, value)"
        SspPyObj.__init__(self, typeObj, regIx)
        assert isinstance(items, list)
        self._items = items
    def to_impBin(self, iterator):
        iterator.write_uint8(len(self._items))
        for (key, value) in self._items:
            to_impBin(key, self.get_type()._key_type, iterator)
            to_impBin(value, self.get_type()._value_type, iterator)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #TODO: Casting between MAP types
        if isinstance(schemaObj, TypedMapTypeClass):
            if (schemaObj._key_type == self.get_type()._key_type and
                schemaObj._value_type == self.get_type()._value_type):
                return TypedMap(schemaObj, self._items)  #Could we return self?
            lst = [(key.cast_to(schemaObj._key_type, source),
                    val.cast_to(schemaObj._value_type, source,
                                require_expressible=True))
                   for (key,val) in self._items]
            return TypedMap(schemaObj, lst)
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        #This loses the element order
        dic = {}
        for (key, value) in self._items:
            dic[key.to_pyValue()] = value.to_pyValue()
        return dic
    def is_atomic_value(self):
        return False
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose >= V_TERSE:
            s = '{' + ', '.join([key.to_sspAscii(V_NORMAL) + ': ' +
                                 val.to_sspAscii(verbose)
                                 for (key,val) in self._items]) + '}'
        else:
            s = '[' + ', '.join([val.to_sspAscii(verbose)
                                 for (key,val) in self._items]) + ']'
        if verbose >= V_NORMAL:
            if self.get_type().has_ref_string():
                ref_str = self.get_type().get_ref_string()
                if verbose > V_NORMAL or ref_str != "Map":
                    return self.get_type().get_ref_string() + s
                return s
            elif verbose > V_NORMAL:
                return self.get_type().to_sspAscii(verbose) + s
        return s
    def lookup(self, key):
        #Slow. An optimized version could use a map with native keys
        for (item_key, item_value) in self._items:
            if item_key.equals(key):
                return item_value
        raise KeyError("No key " + repr(key) + " in TypedMap " +
                       self.to_sspAscii(V_TERSE))
    def get(self, key, default=Exception):
        try:
            return self.lookup(key)
        except Exception as ex:
            if default == Exception:
                raise ex
            return default
    def find_union_match(self, value, debug=False):
        "Returns (key, pyObj)"
        #The items are assumed to be types
        for (_key, _type) in self._items:
            try:
                pyObj = _type.from_pyValue(value)
                return (_key, pyObj)
            except Exception as ex:
                if debug:
                    print('Not union match since: ' + str(ex))
                pass
        raise KeyError("No match in TypedMap %s for %s" %
                       (self.to_sspAscii(V_TERSE), repr(value)))


#SSP_FORMAT_STRUCT
class _TheStructTypeClass(FormatPyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_FORMAT_STRUCT,
                          "Struct", "SSP_FORMAT_STRUCT")
    def __call__(self, fields, regIx = None):
        "Fields is array of tuples (string name, pyObj type)"
        fields = fields[:]
        for i in range(len(fields)):
            _type = fields[i][1]
            assert isinstance(_type, SspPyObj)
            fields[i] = (global_ontology.name_to_symbol(fields[i][0],
                                                        create=True), _type)
        return StructTypeClass(fields, regIx)
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_STRUCT:
            raise Exception()
        element_count = iterator.read_uint8()
        elements = []
        for i in range(element_count):
            symbol = global_ontology.ix_to_symbol(iterator.read_symbol())
            value_type = from_regIx(iterator)
            elements.append( (symbol, value_type) )
        return StructTypeClass(elements)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        element_iter = StringIterator(string)
        args = ascii.dict_to_pyObj(element_iter, keys_are_symbols=True,
                                   source=source)
        return StructTypeClass(args)
struct_format = _TheStructTypeClass()

class StructTypeClass(FormatSchemaPyObj):
    "A particular Struct type"
    def __init__(self, elements, regIx = None):
        "<elements> is list of tuples (name, type) where name is Symbol and type is a pyObj"
        SspPyObj.__init__(self, None, regIx)
        self._elements = elements
    def __call__(self, *values):
        "Create a struct instance. <values> is Python list of pyObjects or Python values that adhere to the respective struct field type."
        return self.from_pyValue(values)
    def from_impBin(self, iterator):
        values = []
        for (name, _type) in self._elements:
            if debug_decoding:
                print("Struct element '%s' has type %s" % \
                      (name, _type.to_sspAscii(V_TERSE)))
                iterator.push_savepoint()
            values.append(_type.from_impBin(iterator))
            if debug_decoding:
                print('  %s => %s: %s' % (iterator.pop_savepoint_hex(),
                                          name, values[-1].to_sspAscii(V_TERSE)))
        return Struct(self, values)
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_STRUCT)
        iterator.write_uint8(len(self._elements))
        for (symbol,value_type) in self._elements:
            symbol.to_impBin(iterator)
            if value_type.get_regIx() is None:
                raise BinaryFormatException("Struct to_schemaBin() not possible when member type doesn't have a regIx")
            iterator.write_regIx(value_type.get_regIx())
    def from_pyValue(self, values):
        """Create a struct instance. <values> is either
           1) Python list of pyObjects or Python values, matched by position
           2) Python dictionary with native or pyObject keys and values
           The values must adhere to the respective struct field type."""
        if len(values) != len(self._elements):
            raise TypeException("Wrong number of arguments to struct %s (wanted %d, got %d)" % (self.to_sspAscii(), len(self._elements), len(values)))
        lst = []
        if isinstance(values, dict):
            for i in range(len(self._elements)):
                (_key, _type) = self._elements[i]
                if _key in values:
                    val = values[_key]
                elif _key.name in values:
                    val = values[_key.name]
                else:
                    raise TypeException("Key %s not found in %s when instantiating struct" % (_key.name, repr(values)))
                # Typecheck the element
                cast_val = from_pyValue(val).cast_to(_type)
                lst.append(cast_val)
            return Struct(self, lst)

        if isinstance(values, list) or isinstance(values, tuple):
            for i in range(len(self._elements)):
                _type = self._elements[i][1]
                if isinstance(values[i], SspPyObj):
                    lst.append(values[i].cast_to(_type,
                                                 require_expressible=True))
                else:
                    lst.append(_type.from_pyValue(values[i]))
            return Struct(self, lst)
        raise TypeException()

    def to_sspAscii(self, verbose=V_NORMAL):
        return "Struct{%s}" % \
            ', '.join([name.to_pyValue() + ": " + repr(type) for (name,type) in self._elements])
    def is_structured_type(self):
        return True
    def lookup(self, key):
        #Not common to use? Looks up the type of a field
        for (item_key, item_type) in self._elements:
            if item_key.equals(key):
                return item_type
        raise KeyError

class Struct(StructuredValuePyObj):
    "A particular instance of a struct data type"
    #Since SSP maps are ordered, representation doesn't use Python dict
    def __init__(self, typeObj, values, regIx=None):
        "<typeObj> is a StructTypeClass. <values> is a python list of pyObj elements"
        SspPyObj.__init__(self, typeObj, regIx)
        assert isinstance(values, list)
        assert len(typeObj._elements) == len(values)
        self._values = values  #List of pyObjects that ahere to the type in the corresponding tuple in _schema._elements
    def to_impBin(self, iterator):
        for i in range(len(self._values)):
            _type = self.get_type()._elements[i][1]
            value = self._values[i]
            to_impBin(value, _type, iterator)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if isinstance(schemaObj, StructTypeClass):
            if len(schemaObj._elements) != len(self._values):
                raise source.error("Wrong number of elements")
            lst = []
            for (key, val_type) in range(len(schemaObj._elements)):
                try:
                    my_val = self[key]
                except KeyError:
                    raise source.error("Required key %s is not present" % key)
                lst.append(my_val.cast_to(val_type, source, require_expressible=True))
            return schemaObj.from_pyValue(lst)
        #if isinstance(schemaObj, TypedListClass):
        #TODO: Cast to list and tuple types
        #TODO: Casting between MAP types
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        #This loses the element order
        dic = {}
        for i in range(len(self._values)):
            dic[self.get_type()._elements[i][0].to_pyValue()] = self._values[i].to_pyValue()
        return dic
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose == V_MINIMAL:
            return '[%s]' % ', '.join([x.to_sspAscii(V_MINIMAL) for x in self._values])
        exclude_keys = False
        s = ""
        if self.get_type().has_ref_string() and verbose > V_TERSE:
            s = self.get_type().get_ref_string()
            if verbose < V_VERBOSE:
                exclude_keys = True
        if exclude_keys:
            s += "["
        else:
            s += '{'
        lst = []
        for i in range(len(self._values)):
            key = self.get_type()._elements[i][0]
            value = self._values[i]
            if exclude_keys:
                lst.append(value.to_sspAscii(verbose))
            else:
                lst.append(key.to_sspAscii(verbose) + ": " + value.to_sspAscii(verbose))
        s += ', '.join(lst)
        if exclude_keys:
            s += ']'
        else:
             s += '}'
        return s
    def lookup(self, key):
        #Slow. An optimized version could use a map with native keys
        for i in range(len(self._values)):
            _key = self.get_type()._elements[i][0]
            if _key.equals(key):
                return self._values[i]
        raise KeyError
    def __getitem__(self, key):
        return self.lookup(key)
    def __contains__(self, key):
        for i in range(len(self._values)):
            _key = self.get_type()._elements[i][0]
            if _key.equals(key):
                return True
        return False


#SSP_FORMAT_TUPLE
class _TheTupleFormatClass(FormatPyObj):
    def __init__(self):
        "The singleton for Tuple parameterized format, without parameters"
        SspPyObj.__init__(self, None, SSP_FORMAT_TUPLE,
                          "Tuple", "SSP_FORMAT_TUPLE")
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_TUPLE:
            raise Exception()
        count = iterator.read_uint8()
        types = []
        for i in range(count):
            types.append(from_regIx(iterator))
        return TupleTypeClass(types)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source=source)
        return TupleTypeClass(args)
tuple_format = _TheTupleFormatClass()

class TupleTypeClass(FormatSchemaPyObj):
    "Each object of this class is a specific tuple type"
    def __init__(self, element_types, regIx = None):
        SspPyObj.__init__(self, None, regIx)
        self._element_types = element_types
    def from_impBin(self, iterator):
        lst = []
        for _type in self._element_types:
            lst.append(_type.from_impBin(iterator))
        return Tuple(self, lst)
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_TUPLE)
        iterator.write_uint8(len(self._element_types))
        for _type in self._element_types:
            if _type.get_regIx() is None:
                raise BinaryFormatException("Tuple to_schemaBin() not possible when member type doesn't have a regIx")
            iterator.write_regIx(_type.get_regIx())
    def from_pyValue(self, value):
        if len(value) != len(self._element_types):
            raise TypeException("from_pyValue wrong number of elements")
        #Cast all elements to the corresponding type
        return Tuple(self, [self._element_types[ix].from_pyValue(value[ix]) for ix in range(len(value))])
    def to_sspAscii(self, verbose=V_NORMAL):
        return "Tuple(%s)" % \
            ', '.join([x.to_sspAscii(verbose) for x in self._element_types])
    def is_structured_type(self):
        return True
    def lookup(self, key):
        #Special: lookup type of an regIx
        pyKey = key.to_pyValue()
        if not isinstance(pyKey, int) or pyKey < 0 or pyKey >= len(self._element_types):
            raise KeyError
        return self._element_types[pyKey]
    def find_union_match(self, value):
        "Returns (key, pyObj)"
        #The items are assumed to be types
        for i in range(len(self._element_types)):
            _type = self._element_types[i]
            try:
                pyObj = _type.from_pyValue(value)
                return (i, pyObj)
            except:
                pass
        raise KeyError

class Tuple(StructuredValuePyObj):
    "A particular data instance of some tuple type"
    def __init__(self, schema, lst, regIx=None):
        SspPyObj.__init__(self, schema, regIx)
        assert isinstance(lst, list)
        #TODO: transcode lst to the typeObj element types?
        self._list = lst #List of pyObj(?) values
    def to_impBin(self, iterator):
        for i in range(len(self._list)):
            _type = self.get_type()._element_types[i]
            value = self._list[i]
            to_impBin(value, _type, iterator)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #TODO: Casting to another tuple type and to list types
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        return [x.to_pyValue() for x in self._list]
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose <= V_TERSE:
            '[%s]' % ', '.join([x.to_sspAscii(verbose) for x in self._list])
        return '%s[%s]' % (self.get_type().get_ref_string(), ', '.join([x.to_sspAscii(verbose) for x in self._list]))
    def lookup(self, key):
        #Lookup value from regIx
        pyKey = key.to_pyValue()
        if not isinstance(pyKey, int) or pyKey < 0 or pyKey >= len(self._list):
            raise KeyError
        return self._list[pyKey]
    def find_union_match(self, value):
        "Returns (key, pyObj)"
        #The items are assumed to be types
        #Tuples use index as key for unions
        for i in range(len(self._list)):
            _type = self._list[i]
            try:
                pyObj = _type.from_pyValue(value)
                return (i, pyObj)
            except:
                pass
        raise KeyError

#SSP_FORMAT_TYPED_LIST
#SSP_FORMAT_TYPED_LIST_FIXEDSIZE
class _TypedListFormatClass(FormatPyObj):
    "Two instances exist: TYPED_LIST and TYPED_LIST_FIXEDSIZE, both creating TypedListTypeClass instances"
    def __init__(self, regIx, label):
        SspPyObj.__init__(self, None, regIx, label)
    def __call__(self, elementType, count=None, regIx=None):
        return TypedListTypeClass(elementType, count, regIx)
    def from_schemaBin(self, iterator):
        _regIx = iterator.read_regIx()
        if _regIx == SSP_FORMAT_TYPED_LIST:
            element_count = None
        elif _regIx == SSP_FORMAT_TYPED_LIST_FIXEDSIZE:
            element_count = iterator.read_uint8()
        else:
            raise Exception()
        element_type = from_regIx(iterator)
        return TypedListTypeClass(element_type, element_count=element_count)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        if bracket_char != '(':
            raise source.error("TypedList only supports () arguments")
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source)
        if len(args) == 1:
            return TypedListTypeClass(args[0])
        if len(args) == 2:
            count = args[0].to_pyValue()
            return TypedListTypeClass(args[1], count)
        raise source.error("TypedList only supports one or two arguments")
typed_list = _TypedListFormatClass(SSP_FORMAT_TYPED_LIST, "TypedList")
#The label TypedListFixedSize doesn't need to be used; TypedList works too.
typed_list_fixedsize = _TypedListFormatClass(SSP_FORMAT_TYPED_LIST_FIXEDSIZE,
                                             "TypedListFixedSize")

class TypedListTypeClass(FormatSchemaPyObj):
    "A TypedList type of either unbounded size, or constant size"
    def __init__(self, element_type, element_count = None,
                 regIx = None):
        if element_count is None:
            schema = typed_list
        else:
            schema = typed_list_fixedsize
        SspPyObj.__init__(self, schema, regIx)
        self._element_type = element_type
        self._element_count = element_count
    def __call__(self, elements):
        "Create a list of this type"
        return self.from_pyValue(elements)
    def from_impBin(self, iterator):
        if self._element_count is None:
            count = iterator.read_uint8()
        else:
            count = self._element_count
        lst = []
        if debug_decoding:
            print('TypedList decode %d elements of type %s' % \
                (count, self._element_type.to_sspAscii(V_VERBOSE)))
        for i in range(count):
            if debug_decoding:
                print("List %s element %d" % (self.to_sspAscii(V_TERSE), i))
            lst.append(self._element_type.from_impBin(iterator))
            if debug_decoding:
                print('TypedList decoded %s' % lst[-1].to_sspAscii(V_VERBOSE))
        return TypedList(self, lst)
    def to_schemaBin(self, iterator):
        iterator.write_regIx(self.get_type().get_regIx())
        if self._element_count is not None:
            iterator.write_uint8(self._element_count)
        if self._element_type.get_regIx() is None:
            raise BinaryFormatException("TypedList to_schemaBin() not possible when member type doesn't have a regIx")
        iterator.write_regIx(self._element_type.get_regIx())
    def from_pyValue(self, value):
        if not (isinstance(value, list) or isinstance(value, tuple)):
            raise TypeException("Not a list or tuple")
        if self._element_count is not None and len(value) != self._element_count:
            raise TypeException("Wrong number of elements")

        return TypedList(self, [self._element_type.from_pyValue(x)
                                for x in value])
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        from . import ascii
        if bracket_char != '[':  #bracket_char
            raise source.error("TypedList only supports [] arguments")
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source=source)
        if self._element_count is not None and len(args) != self._element_count:
            raise source.error("Wrong number of list elements (should be %d)" %\
                               self._element_count)
        args = [arg.cast_to(self._element_type, source, require_expressible=True) for arg in args]
        return TypedList(self, args)
    def to_sspAscii(self, verbose=V_NORMAL):
        if self._label:
            return self._label
        if self._element_count is None:
            return "TypedList(%s)" % self._element_type.to_sspAscii()
        else:
            return "TypedList(%d, %s)" % \
                (self._element_count, self._element_type.to_sspAscii())
    def is_structured_type(self):
        return True

class TypedList(StructuredValuePyObj):
    "A specific instance of a TypedListTypeClass"
    def __init__(self, schema, lst, regIx=None):
        "lst is a Python list of pyObj objects"
        SspPyObj.__init__(self, schema, regIx)
        assert isinstance(lst, list)
        assert isinstance(schema, TypedListTypeClass)
        self._list = lst #Element types are assumed to conform to typeObj
    def to_impBin(self, iterator):
        implicit_count = self.get_type()._element_count
        if implicit_count is None:
            iterator.write_uint8(len(self._list))
        _type = self.get_type()._element_type
        for el in self._list:
            to_impBin(el, _type, iterator)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if schemaObj == self.get_type():
            return self
        if schemaObj == list_type:
            return list_type(self._list) #No typecasting necessary
        if isinstance(schemaObj, TypedListTypeClass):
            if schemaObj._element_count is not None:
                if len(self._list) != schemaObj._element_count:
                    raise source.error("Wrong number of list elements")
            new_elements = [el.cast_to(schemaObj._element_type, source, require_expressible=True) for el in self._list]
            return TypedList(schemaObj, new_elements)
        #TODO: Casting to other list types, and possibly to dict types
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        return [x.to_pyValue() for x in self._list]
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose < V_NORMAL:
            schemaStr = ''
        elif self.get_type().has_ref_string():
            schemaStr = self.get_type().get_ref_string()
            if schemaStr == 'List':
                schemaStr = ''
        else:
            schemaStr = self.get_type().to_sspAscii(verbose)
        # Include element types if different from the type already
        # stated for list elements
        el_str = []
        for x in self._list:
            if x.get_type() == self.get_type()._element_type:
                el_str.append(x.to_sspAscii(V_TERSE))
            else:
                el_str.append(x.to_sspAscii(verbose))
        return '%s[%s]' % (schemaStr, ', '.join(el_str))
    def lookup(self, key):
        #Lookup value from regIx
        pyKey = key.to_pyValue()
        if not isinstance(pyKey, int) or pyKey < 0 or pyKey >= len(self._list):
            raise KeyError
        return self._list[pyKey]
    def __getitem__(self, key):
        return self.lookup(key)
    def __contains__(self, key):
        pyKey = key.to_pyValue()
        return pyKey in self._list
    def find_union_match(self, value):
        "Returns (key, pyObj)"
        #List uses index as key for unions
        for i in range(len(self._list)):
            _type = self._list[i]
            try:
                pyObj = _type.from_pyValue(value)
                return (i, pyObj)
            except:
                pass
        raise KeyError


#SSP_FORMAT_CONCATERNATED_DATA

#SSP_FORMAT_FIXPOINT
class _FixpointFormatClass(FormatPyObj):
    "The type of all fixpoint types"
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_FORMAT_FIXPOINT,
                          "Fixpoint", "SSP_FORMAT_FIXPOINT")
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_FIXPOINT:
            raise Exception()
        is_two_complement = iterator.read_uint8()
        bits = iterator.read_uint8()
        decimal_count = iterator.read_uint8()
        return FixpointTypeClass(is_two_complement, bits, decimal_count)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        if bracket_char != '(':
           raise source.error("Fixpoint requires parentheses")
        try:
            args = eval(string)
        except:
            raise source.error("Can't eval Fixpoint args")
        if len(args) != 3:
            raise source.error("Fixpoint wrong number of args")
        return FixpointTypeClass(args[0], args[1], args[2])
fixpoint_format = _FixpointFormatClass()

class FixpointTypeClass(FormatSchemaPyObj):
    "A fixpoint type (specification of number of bits)"
    def __init__(self, is_two_complement, bits, decimal_count,
                 regIx = None):
        SspPyObj.__init__(self, None, regIx)
        assert type(is_two_complement) is bool \
            or is_two_complement == 0 or is_two_complement == 1
        assert bits in [8, 16, 32]
        assert decimal_count >= 0 and decimal_count < 32
        self._is_two_complement = bool(is_two_complement)
        self._bits = bits
        self._decimal_count = decimal_count
        if self._is_two_complement:
             #Most negative value is used as null
            self._raw_null_value = -(2 ** (self._bits - 1))
        else:
            #Most positive value is used as null
            self._raw_null_value = 2 ** (self._bits) - 1

    def __call__(self, raw_value, regIx = None):
        return Fixpoint(self, raw_value, regIx)

    def from_impBin(self, iterator):
        if self._is_two_complement:
            if self._bits == 16:
                return Fixpoint(self, iterator.read_int16())
            if self._bits == 32:
                return Fixpoint(self, iterator.read_int32())
            raise Exception("Not implemented")
        if self._bits == 8:
            return Fixpoint(self, iterator.read_uint8())
        if self._bits == 16:
            return Fixpoint(self, iterator.read_uint16())
        if self._bits == 32:
            return Fixpoint(self, iterator.read_uint32())
        raise Exception("Not implemented")
    def to_impBin(self, iterator):
        raise Exception()
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_FIXPOINT)
        iterator.write_uint8(1 if self._is_two_complement else 0)
        iterator.write_uint8(self._bits)
        iterator.write_uint8(self._decimal_count)

    def _value_to_impBin(self, iterator, raw_value):
        if self._is_two_complement:
            if self._bits == 16:
                iterator.write_int16(raw_value)
            elif self._bits == 32:
                iterator.write_int32(raw_value)
            else:
                raise Exception("Not implemented")
            return
        if self._bits == 8:
            iterator.write_uint8(raw_value)
        elif self._bits == 16:
            iterator.write_uint16(raw_value)
        elif self._bits == 32:
            iterator.write_uint32(raw_value)
        else:
            raise Exception("Not implemented")

    def from_pyValue(self, value):
        if value is None:
            raw_value = self._raw_null_value
        else:
            if not self._is_two_complement and value < 0:
                raise TypeException("Unsigned fixpoint type can't encode negative value")
            raw_value = int(value * (10 ** self._decimal_count))
        return Fixpoint(self, raw_value)

    def to_sspAscii(self, verbose=V_NORMAL):
        if self._is_two_complement:
            sign = "1"
        else:
            sign = "0"
        return "Fixpoint(%s,%d,%d)" % \
            (sign, self._bits, self._decimal_count)
    def is_atomic_type(self):
        return True

class Fixpoint(AtomicValuePyObj):
    "A specific value, expressed as an instance of a fixpoint type"
    def __init__(self, _type : "FixpointTypeClass", raw_value : int, regIx=None):
        "raw_value is the signed integer"
        SspPyObj.__init__(self, _type, regIx)
        assert isinstance(raw_value, int)
        assert isinstance(_type, FixpointTypeClass)
        #Could be more efficient to store as native Python float?
        self._raw_value = raw_value
    def to_impBin(self, iterator):
        self.get_type()._value_to_impBin(iterator, self._raw_value)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #TODO: Casting to fixpoints and other numeric types
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        if self.is_null():
            return "null"
        return float(self._raw_value) / (10 ** self.get_type()._decimal_count)
    def is_null(self):
        return self._raw_value == self._type._raw_null_value
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose <= V_TERSE:
            if self.get_type()._decimal_count == 0:
                return str(self._raw_value)
            #Hack to output the correct number of decimals
            return ("%%.%df" % self.get_type()._decimal_count) % self.to_pyValue()
        return '%s(%d)' % (self.get_type().get_ref_string(), self._raw_value)
    def equals(self, obj):
        if isinstance(obj, SspPyObj):
            if self.regIx is not None and self.regIx == obj.regIx:
                return True
            val = obj.to_pyValue()
        else:
            val = obj
        try:
            return is_close(self.to_pyValue(), val)
        except:
            return False

#SSP_FORMAT_SCALED
class _ScaledFormatClass(FormatPyObj):
    "The type of all 'scaled number' types"
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_FORMAT_SCALED,
                          "Scaled", "SSP_FORMAT_SCALED")
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_SCALED:
            raise Exception()
        bits = iterator.read_uint8()
        is_two_complement = iterator.read_uint8()
        scale = iterator.read_float()
        offset = iterator.read_float()
        return ScaledTypeClass(bits, is_two_complement, scale, offset)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        if bracket_char != '(':
           raise source.error("Scaled requires parentheses")
        try:
            args = eval(string)
        except:
            raise source.error("Can't eval Scaled args")
        if len(args) != 4:
            raise source.error("Scaled wrong number of args")
        return ScaledTypeClass(args[0], args[1], args[2], args[3])
scaled_format = _ScaledFormatClass()

def _count_decimals(number):
    string = str(number)
    if not '.' in string or string.endswith('.0'):
        return 0
    else:
        return len(string) - string.find('.') - 1

class ScaledTypeClass(FormatSchemaPyObj):
    "A scaled number type (specifies a type with scale and offset)"
    def __init__(self, bits : int, is_two_complement : bool,
                 scale : float, offset : float, regIx = None):
        SspPyObj.__init__(self, None, regIx)
        assert type(is_two_complement) is bool \
            or is_two_complement == 0 or is_two_complement == 1
        assert bits in [8, 16, 32]
        assert scale != 0
        self._is_two_complement = bool(is_two_complement)
        self._bits = bits
        self._scale = scale  # The smallest non-zero value
        self._offset = offset
        self._decimal_count = max(_count_decimals(scale),
                                  _count_decimals(offset))

        if self._is_two_complement:
             #Most negative value is used as null
            self._raw_null_value = -(2 ** (self._bits - 1))
        else:
            #Most positive value is used as null
            self._raw_null_value = 2 ** (self._bits) - 1

    def __call__(self, raw_value, regIx = None):
        return Scaled(self, raw_value, regIx)

    def from_impBin(self, iterator):
        if self._is_two_complement:
            if self._bits == 16:
                return Scaled(self, iterator.read_int16())
            if self._bits == 32:
                return Scaled(self, iterator.read_int32())
            raise Exception("Not implemented")
        if self._bits == 8:
            return Scaled(self, iterator.read_uint8())
        if self._bits == 16:
            return Scaled(self, iterator.read_uint16())
        if self._bits == 32:
            return Scaled(self, iterator.read_uint32())
        raise Exception("Not implemented")
    def to_impBin(self, iterator):
        raise Exception()
    def to_schemaBin(self, iterator):
        iterator.write_regIx(SSP_FORMAT_SCALED)
        iterator.write_uint8(self._bits)
        iterator.write_uint8(1 if self._is_two_complement else 0)
        iterator.write_float(self._scale)
        iterator.write_float(self._offset)

    def _value_to_impBin(self, iterator, raw_value):
        if self._is_two_complement:
            if self._bits == 16:
                iterator.write_int16(raw_value)
            elif self._bits == 32:
                iterator.write_int32(raw_value)
            else:
                raise Exception("Not implemented")
            return
        if self._bits == 8:
            iterator.write_uint8(raw_value)
        elif self._bits == 16:
            iterator.write_uint16(raw_value)
        elif self._bits == 32:
            iterator.write_uint32(raw_value)
        else:
            raise Exception("Not implemented")

    def encode_value(self, value : float):
        if value is None:
            return self._raw_null_value
        return int(round((value - self._offset) / self._scale))

    def decode_value(self, raw_value : int):
        if raw_value == self._raw_null_value:
            return "null"
        return (raw_value * self._scale) + self._offset

    def from_pyValue(self, value):
        if value is None:
            raw_value = self._raw_null_value
        else:
            raw_value = self.encode_value
            if not self._is_two_complement and raw_value < 0:
                raise TypeException("Unsigned scaled type can't encode negative value")
        return Scaled(self, raw_value)

    def to_sspAscii(self, verbose=V_NORMAL):
        if self._is_two_complement:
            sign = "1"
        else:
            sign = "0"
        if self._offset == 0:
            offset = "0"
        else:
            offset = "%f" % self._offset
        return "Scaled(%d,%s,%f,%s)" % \
            (self._bits, sign, self._scale, offset)
    def is_atomic_type(self):
        return True

class Scaled(AtomicValuePyObj):
    "A specific value, expressed as an instance of a 'scaled number' type"
    def __init__(self, _type : "ScaledTypeClass", raw_value : int, regIx=None):
        "<raw_value> is the scaled value, an integer"
        SspPyObj.__init__(self, _type, regIx)
        assert isinstance(raw_value, int)
        assert isinstance(_type, ScaledTypeClass)
        self._raw_value = raw_value
        self._value = _type.decode_value(raw_value)
    def to_impBin(self, iterator):
        self.get_type()._value_to_impBin(iterator, self._raw_value)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        #TODO: Casting to numeric types
        return SspPyObj.cast_to(self, schemaObj, source, require_expressible)
    def to_pyValue(self):
        if self.is_null():
            return "null"
        return self._value
    def is_null(self):
        return self._raw_value == self._type._raw_null_value
    def to_sspAscii(self, verbose=V_NORMAL):
        if verbose <= V_TERSE:
            if self.get_type()._decimal_count == 0:
                return "%d" % self._value
            return ("%%.%df" % self.get_type()._decimal_count) % self._value
        return '%s(%d)' % (self.get_type().get_ref_string(), self._raw_value)
    def equals(self, obj):
        if isinstance(obj, SspPyObj):
            if self.regIx is not None and self.regIx == obj.regIx:
                return True
            val = obj.to_pyValue()
        else:
            val = obj
        try:
            return is_close(self._value, val)
        except:
            return False

#(SSP_FORMAT_EXTEND -- never in stored data)

#SSP_FORMAT_UNION
class _TheUnionFormatClass(FormatPyObj):
    def __init__(self):
        "The singleton for Union parameterized format, without parameters"
        SspPyObj.__init__(self, None, SSP_FORMAT_UNION,
                          "Union", "SSP_FORMAT_UNION")
    def from_schemaBin(self, iterator):
        if iterator.read_regIx() != SSP_FORMAT_UNION:
            raise Exception()
        options = from_regIx(iterator)
        key_type = from_regIx(iterator)
        return UnionTypeClass(options, key_type)
    def from_sspAscii_args(self, string, bracket_char, source=no_source):
        if bracket_char != '(':
           raise source.error("Union requires parentheses")
        from . import ascii
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source=source)
        if len(args) != 2:
            raise source.error("Union requires two arguments")
        options, key_type = args
        if not options.is_structured_type():
            raise source.error("Union requires lookup in a structured type")
        if not key_type.is_atomic_type():
            raise source.error("Union key type must be atomic")
        return UnionTypeClass(options, key_type)
    #def __call(self, options, key_type):
    #    return UnionTypeClass(options, key_type)


union_format = _TheUnionFormatClass()

class UnionTypeClass(FormatSchemaPyObj):
    "A Union type combining a set of types"
    def __init__(self, options, key_type, regIx=None):
        SspPyObj.__init__(self, union_format, regIx=regIx)
        #Options is structured pyObj; if list or tuple, index is used as key
        self._options = options
        self._key_type = key_type
    def __call__(self, key):
        "Instantiate the union, choosing one of the possible types"
        return self.from_pyValue(key)
    def from_impBin(self, iterator, dereference=True):
        #Resolve both the type choice and the value of that type
        key = self._key_type.from_impBin(iterator)
        if dereference:
            chosen_type = self._options.lookup(key)
            if debug_decoding:
                print('Union will decode with key %s (type %s)' % \
                    (repr(key), chosen_type.to_sspAscii(V_MINIMAL)))
            return chosen_type.from_impBin(iterator)
        raise Exception("Not implemented")
    def to_schemaBin(self, iterator):
        iterator.write_regIx(self.get_type().get_regIx())  #"union"
        if self._options.get_regIx() is None:
            raise BinaryFormatException("Union to_schemaBin() not possible when the options list doesn't have a regIx")
        iterator.write_regIx(self._options.get_regIx())
        if self._key_type.get_regIx() is None:
            raise BinaryFormatException("Union to_schemaBin() not possible when the key type doesn't have a regIx")
        iterator.write_regIx(self._key_type.get_regIx())
    def from_pyValue(self, value):
        "Find a union member that matches <value> and cast <value> to that type"
        pyObj = None
        (key, pyObj) = self._options.find_union_match(value)
        key = from_pyValue(key).cast_to(self._key_type, require_expressible=True)
        return UnionClass(self, key, pyObj)
    def from_sspAscii_args(self, string, bracket_char, source, dereference=True):
        from . import ascii
        if bracket_char != '[':  #bracket_char
            raise source.error("UnionType only supports [] arguments")
        element_iter = StringIterator(string)
        args = ascii.list_to_pyObj(element_iter, source=source)
        if len(args) != 1:
            raise source.error("Only one argument to UnionType is allowed")
        key = args[0].cast_to(self._key_type, require_expressible=True)
        if dereference:
            return self._options.lookup(key)
        else:
            return UnionClass(self, key)
    def to_sspAscii(self, verbose=V_NORMAL):
        if self._label:
            return self._label
        return "Union(%s, %s)" % (self._options.get_ref_string(),
                                  self._key_type.get_ref_string())
    def is_structured_type(self):
        return True #It's a type, but is it structured?
    def lookup(self, key):
        return self._options.lookup(key)
    def __getitem__(self, key):
        return self._options.lookup(key)
    def __contains__(self, key):
        try:
            self._options.lookup(key)
            return True
        except KeyError as ex:
            return False

class UnionClass(StructuredValuePyObj):
    """A specific instance of a union type (UnionTypeClass). This wraps
       the reduced form (the "value") with metadata on union and
       chosen key. A UnionClass object doesn't add any information to
       the value; it only affects the encoding as impBin.
    """
    def __init__(self, union_type, key, value, *args, **kwargs):
        SspPyObj.__init__(self, union_type, *args, **kwargs)
        assert isinstance(union_type, UnionTypeClass)
        assert value.get_type().equals(union_type.lookup(key))  # Use this? Or cast?
        #<key> is the key in the union to retrieve the type of <value>
        self._key = from_pyValue(key).cast_to(union_type._key_type,
                                              require_expressible=True)
        self._value = value
    def to_impBin(self, iterator):
        #The type of this union will be implicit in the encoding, but
        #the choice of type of the value is not.

        #TODO: encode key
        #The type of the key index is implicit as it's a part of the UnionType
        self._key.to_impBin(iterator)
        self._value.to_impBin(iterator)
    def cast_to(self, schemaObj, source=no_source, require_expressible=False):
        if schemaObj == self.get_type():
            return self
        return self._value.cast_to(schemaObj, source, require_expressible)
    def to_pyValue(self):
        return self._value.to_pyValue()
    def to_sspAscii(self, verbose=V_NORMAL):
        return self.get_type().to_sspAscii(verbose) + "(%s, %s)" % (self._key.to_sspAscii(verbose), self._value.to_sspAscii(verbose))
    def lookup(self, key):
        return self._value.lookup(key)


######################################################################
## Parameterless format types

class AnyTypeClass(TypePyObj):
    def __init__(self):
        SspPyObj.__init__(self, None, SSP_TYPE_ANY, "Any",
                          c_name="SSP_FORMAT_ANY")
    def from_pyValue(self, value):
        return from_pyValue(value)
    def from_impBin(self, iterator):
        #impBin with type Any == expBin
        return from_expBin(iterator)
    def get_null(self):
        return null
any_type = AnyTypeClass()
#There's no actual object of type "Any"!


######################################################################

#SSP_TYPE_MAP
#Rename to "AnyMap"
map_type = TypedMapTypeClass(any_type, any_type, SSP_TYPE_MAP)
map_type._label = "Map"
map_type.c_name = "SSP_FORMAT_MAP"

#SSP_TYPE_LIST
#Rename to "AnyList"
list_type = typed_list(any_type, regIx=SSP_TYPE_LIST)
list_type._label = "List"
list_type.c_name = "SSP_FORMAT_LIST"

formats : typing.List[SspPyObj] = \
    [constant_format, tuple_format, struct_format, typed_map_format,
     typed_list, typed_list_fixedsize, fixpoint_format, scaled_format]

numeric_types : typing.List[SspPyObj] = \
    [bool_type, uint8_type, uint16_type, int16_type,
     int32_type, uint32_type, float_type]

nonnumeric_types : typing.List[SspPyObj] = \
    [null, symbol_type, string_type, blob_type, schema_type, ref_type]

reducible_types : typing.List[SspPyObj] = [any_type, map_type, list_type]

builtin_types : typing.List[SspPyObj] = numeric_types + nonnumeric_types + reducible_types + formats

builtins_are_defined = False
def define_builtins():
    global builtins_are_defined
    if builtins_are_defined:
        return
    builtin_ontology = ontology.inherit_ontology()
    for x in builtin_types:
        builtin_ontology.add_entry(x.regIx, x)


######################################################################

def to_impBin(pyObj, typeObj, iterator):
    "Writes <pyObj> as impBin with a specific implied type <typeObj>"
    if pyObj.equals(typeObj):
        return  #The type includes all info. Don't write anything!
    if typeObj == any_type:
        pyObj.to_expBin(iterator)
        return
    if typeObj == ref_type:
        if pyObj.get_regIx() is None:
            raise BinaryFormatException("No regIx when writing to impBin as Ref")
        iterator.write_regIx(pyObj.get_regIx())
        return
    if pyObj.get_type() == typeObj:
        pyObj.to_impBin(iterator)
        return
    pyObj.cast_to(typeObj, require_expressible=True).to_impBin(iterator)

def to_expBin(pyObj, iterator):
    "Writes SSP-BIN with type to ByteIterator <iterator>"
    iterator.write_regIx(pyObj.get_type().get_regIx())
    sspPy.to_impBin(iterator)

#def from_impBin(iterator, typeIx = SSP_TYPE_ANY):
#    """Read a pyObj with implicit typeIx from
#       ByteIterator <iterator>
#    """
#    while typeIx == SSP_TYPE_ANY:
#        typeIx = iterator.read_regIx()
#    schemaType = global_ontology.get_by_regIx(typeIx)
#    return schemaType.from_impBin(iterator)

def from_expBin(iterator):
    "Read a pyObj from ByteIterator <iterator>"
    schemaType = from_schemaBin(iterator)
    if debug_decoding:
        print('Decode expBin with type %s' % schemaType.to_sspAscii(V_VERBOSE))
    value = schemaType.from_impBin(iterator)
    if debug_decoding:
        print('... => %s' % value.to_sspAscii(V_NORMAL))
    return value

def from_regIx(iterator):
    "Read a regIx from ByteIterator <iterator> and lookup the pyObject. Doesn't allow formats."
    typeIx = iterator.read_regIx()
    schemaType = global_ontology.get_by_regIx(typeIx)
    if isinstance(schemaType, FormatPyObj):
        raise BinaryFormatException("Expected type regIx, found format %d" % typeIx)
    return schemaType

def from_schemaBin(iterator):
    typeIx = iterator.read_regIx()
    while typeIx == SSP_TYPE_ANY:
        typeIx = iterator.read_regIx()
    schemaType = global_ontology.get_by_regIx(typeIx)
    if schemaType is None:
        if debug_decoding:
            print('Can not decode schema with unknown type regIx=%d' % typeIx)
        raise UnknownRegIxException(typeIx)
    if isinstance(schemaType, FormatPyObj):
        #Push back the regIx as the format object will use it:
        iterator.push_regIx(typeIx)
        return schemaType.from_schemaBin(iterator)
    return schemaType

def from_pyValue(value):
    "Encodes an arbitrary Python value (or structure) to pyObj. Elements that are already pyObj are not changed."
    if value is None or value == "null":
        return null
    if isinstance(value, SspPyObj):
        return value  #Already pyObj
    if isinstance(value, bool):
        return bool_type.from_pyValue(value)
    if isinstance(value, int):
        for _class in [uint8_type, uint16_type, int16_type,
                       uint32_type, int32_type]:
            try:
                return _class.from_pyValue(value)
            except:
                #Just try next class
                pass
        raise TypeException("No Int type for %d" % value)
    if isinstance(value, str):
        if value.startswith("0x"):
            return blob_type.from_pyValue(value)
        if value.startswith("SYM"):
            index = int(value[3:])
            return global_ontology.ix_to_symbol(index)
        if value.startswith("REF"):
            regIx = int(value[3:])
            return Ref(regIx)
        #TODO: This will strip "" from any Python string. Ambiguous!
        if value.startswith('"'):
            if not value.endswith('"'):
                raise Exception
            return String(value[1:-1])
        sym = global_ontology.name_to_symbol(value)
        if sym:
            return sym
        return String(value)

    if isinstance(value, float):
        return float_type.from_pyValue(value)
    if isinstance(value, list) or isinstance(value, tuple):
        return list_type.from_pyValue(value)

    if isinstance(value, dict):
        return map_type.from_pyValue(value)

    #TODO
    raise TypeException("No pyObject translation for %s %s" % \
                        (type(value), repr(value)))

def to_pyValue(value):
    "Any value not a pyObject is just passed through"
    if isinstance(value, SspPyObj):
        return value.to_pyValue()
    return value

if __name__ == "__main__":
    it = ByteIterator()
    a = from_pyValue([5000, -12, True])
    a.to_expBin(it)
