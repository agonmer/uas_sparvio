from sspt.pyObjects import *
from sspt.ascii import to_pyObj

define_builtins()

#Needed for NameMap:
from sspt.ontology import global_ontology
global_ontology.add_file('ontology/all.txt')

SSPMESSAGE_REQUEST_REPLY_BIT = 0x80

SSPMESSAGE_CINFO = 4
SSPMESSAGE_NEW_ID = 5
SSPMESSAGE_REPLY = 6
SSPMESSAGE_ACK = 7
SSPMESSAGE_NACK = 8
SSPMESSAGE_REPORT = 11
#SSPMESSAGE_EVENT = 12
SSPMESSAGE_CALL = 14
SSPMESSAGE_UGET_VARIABLE_VALUE = 15
SSPMESSAGE_GET_VARIABLE_VALUE = 16
SSPMESSAGE_SET_VARIABLE_VALUE = 17
SSPMESSAGE_SUB = 18
SSPMESSAGE_UNSUB = 19
#SSPMESSAGE_GET_SYMBOL_FROM_ASCII = 25
SSPMESSAGE_GET_VARIABLES_LIST = 26
SSPMESSAGE_CALL_REPLY = SSPMESSAGE_CALL | SSPMESSAGE_REQUEST_REPLY_BIT
SSPMESSAGE_UGET_VARIABLE_VALUE_REPLY = SSPMESSAGE_UGET_VARIABLE_VALUE | \
                                       SSPMESSAGE_REQUEST_REPLY_BIT
SSPMESSAGE_GET_VARIABLES_LIST_REPLY = SSPMESSAGE_GET_VARIABLES_LIST | \
                                      SSPMESSAGE_REQUEST_REPLY_BIT
SSPMESSAGE_SET_VARIABLE_VALUE_REPLY = SSPMESSAGE_SET_VARIABLE_VALUE | \
                                      SSPMESSAGE_REQUEST_REPLY_BIT

cinfo_message_type = to_pyObj('Struct{a:cinfo, ver:Uint8, magicByte:Uint8, tk:Uint8, serial:Uint32, id:Uint8, parent:Uint8, prio:Uint8, profiles:Uint8, vocabulary:Uint8, name:String}')
cinfo_message_type._label = "CInfoMsg"

#'tk' is used as 'parent' for link-level newIds
newid_message_type = to_pyObj('Struct{a:newid, tk:Uint8, id:Uint8, prio:Uint8, name:String}')
newid_message_type._label = "NewidMsg"

reply_message_type = to_pyObj('Struct{a:reply, from:Uint8, tk:Uint8, b:Any}')
reply_message_type._label = "ReplyMsg"

ack_message_type = to_pyObj('Struct{a:ack, from:Uint8, tk:Uint8, b:Any}')
ack_message_type._label = "AckMsg"

nack_message_type = to_pyObj('Struct{a:nack, from:Uint8, tk:Uint8, code:Uint8}')
nack_message_type._label = "NackMsg"

#name_map_type = typed_map_format(symbol_type, any_type)
#name_map_type._label = "NameMap"
report_message_type = to_pyObj('Struct{a:rep, map:OidMap}')
report_message_type._label = 'RepMsg'

#Oneway command
call_message_type = to_pyObj('Struct{a:call, sym:Symbol, arg:Any}')
call_message_type._label = "CallMsg"

call_reply_message_type = to_pyObj('Struct{a:call, from:Uint8, tk:Uint8, sym:Symbol, arg:Any}')
call_reply_message_type._label = "CallMsgR"

get_message_type = to_pyObj('Struct{a:get, var:SymbolList}')
get_message_type._label = "GetMsg"

set_message_type = to_pyObj('Struct{a:set, map:NameMap}')
set_message_type._label = "SetMsg"

set_reply_message_type = to_pyObj('Struct{a:set, from:Uint8, tk:Uint8, map:NameMap}')
set_reply_message_type._label = "SetMsgR"

sub_message_type = to_pyObj('Struct{a:sub, from:Uint8, sym:SymbolList}')
sub_message_type._label = "SubMsg"

unsub_message_type = to_pyObj('Struct{a:unsub, from:Uint8, sym:SymbolList}')
unsub_message_type._label = "UnsubMsg"

uget_message_type = to_pyObj('Struct{a:uget, var:SymbolList}')
uget_message_type._label = "UGetMsg"

getvarlist_reply_message_type = to_pyObj('Struct{a:getVarList, from:Uint8, tk:Uint8}')
getvarlist_reply_message_type._label = 'GetVarListMsgR'

uget_reply_message_type = to_pyObj('Struct{a:uget, from:Uint8, tk: Uint8, var:SymbolList}')
uget_reply_message_type._label = "UGetMsgR"

options = map_type({SSPMESSAGE_CINFO: cinfo_message_type,
                    SSPMESSAGE_NEW_ID: newid_message_type,
                    SSPMESSAGE_REPLY: reply_message_type,
                    SSPMESSAGE_ACK: ack_message_type,
                    SSPMESSAGE_NACK: nack_message_type,
                    SSPMESSAGE_REPORT: report_message_type,
                    SSPMESSAGE_UGET_VARIABLE_VALUE: uget_message_type,
                    SSPMESSAGE_GET_VARIABLE_VALUE: get_message_type,
                    SSPMESSAGE_SET_VARIABLE_VALUE: set_message_type,
                    SSPMESSAGE_SUB: sub_message_type,
                    SSPMESSAGE_UNSUB: unsub_message_type,
                    SSPMESSAGE_CALL: call_message_type,
                    SSPMESSAGE_CALL_REPLY: call_reply_message_type,
                    SSPMESSAGE_UGET_VARIABLE_VALUE_REPLY: uget_reply_message_type,
                    SSPMESSAGE_GET_VARIABLES_LIST_REPLY: getvarlist_reply_message_type,
                    SSPMESSAGE_SET_VARIABLE_VALUE_REPLY: set_reply_message_type
})
options._label = "Msgs"

#Msg: The type of all messages
message_type = UnionTypeClass(options, uint8_type)

#ToMsg:
addressed_msg_type = struct_format([('to', uint8_type), ('msg', message_type)])

def test():
    print(newid_message_type)

    print(options)

    print(message_type)

    py_newid = {'a': 'get', 'parent': None, 'id': 8, 'prio':200, 'name':None}

    newid = newid_message_type.from_pyValue(py_newid)
    print(newid)
    print(newid.lookup('name'))
    print(newid.to_pyValue())

    msg = message_type.from_pyValue(py_newid)
    print(msg)
    print(msg.to_sspAscii(V_TERSE))
    print(msg.to_sspAscii(V_VERBOSE))
