# This file must match ssp_lib/include/applications.h

#TODO: Move appIds to text file instead, to be able to publish to http
#and update the list dynamically

#Mapping from appId to (long app name, dfu filename string, alias)
#Filename string is unique for that hwModel, so HW is superfluous to include
#appId 0 matches anything when finding a firmware to upgrade with
appIds = {0: ('default/unspecified', '', ''),
          1: ('default', '', ''),
          2: ('S2', 's2', ''),
          3: ('SKH1', 'skh1', ''),
          4: ('generic', 'generic', ''),
          5: ('K30', 'senseair_k30', 'SKS6'),
          6: ('HPP', 'senseair_hpp', 'SKS61'),
          7: ('SKC1', 'rfm22b', ''),
          8: ('PMOD_DPG1', 'pmod_dpg1', ''),
          9: ('Trisonica', 'trisonica', 'SKS3'),
          10: ('Omron D6F-P00', 'omron_d6f_p00', ''),
          11: ('Alphasense OPC-N2', 'alphasense_opc_n2', 'SKS8'),
          12: ('Aeroqual SM50', 'aeroqual_sm50', 'SKS4'),
          13: ('Figaro TGS 2611', 'figaro_tgs2611', ''),
          14: ('Atlas Scientific Tentacle T3', 'atlas_tentacle_t3', ''),
          15: ('Plantower PMS7003', 'plantower_pms7003', ''),
          16: ('Aeris MIRA CH4', 'aeris_mira_ch4', ''),
          17: ('SKC1 for S2', 'rfm22b_s2', 'skc1_s2'),
          18: ('Trisonica WS', 'trisonica_ws', 'SKS31'),
          19: ('Alphasense OPC-R1', 'alphasense_opc_r1', 'SKS81'),
          20: ('DigiPicco Basic', 'digipicco_basic', 'SKSXX'),
          21: ('Rotronic HC2A S3', 'rotronic_hc2a_s3', 'SKS11'),
          22: ('Sparkfun LSM9DS1', 'sparkfun_lsm9ds1', 'LSM9DS1'),
          23: ('RFM26W', 'rfm26w', 'RFM26W'),
          24: ('OLED', 'oled', ''),
          25: ('S2S', 's2s', ''),  #Single-use S2
          26: ('S2R', 's2r', ''),  #Reusable S2 (with cutdown, speaker, power LED)
          27: ('Alphasense OPC-N3', 'alphasense_opc_n3', 'SKS82'),
          28: ('SKS21', 'sks21', 'SKS21'),
          29: ('DJI adapter', 'dji', 'DJI'),
          30: ('Aeris MIRA CO', 'aeris_mira_co', ''),
          31: ('SenseAir K96', 'senseair_k96', 'SKS62'),
          32: ('Licor LI-850', 'licor850', ''),
          33: ('Aeris MIRA CO2/N2O', 'aeris_mira_co2_n2o', ''),
}

def id_to_long_name(_id):
    if _id in appIds.keys():
        return appIds[_id][0]
    return None

def filestring_to_id(filestring):
    filestring = filestring.lower()
    for (_id, (name, s, alias)) in appIds.items():
        if s == filestring:
            return _id
    return None

def deduce_id(string):
    "Return id, if there is a single application that matches <string> in some way"
    #Test for complete filestring
    match = filestring_to_id(string)
    if match is not None:
        return match
    #Test for number
    for (_id, (name, s, alias)) in appIds.items():
        if str(_id) == string:
            return _id
    #Test for partial filestring
    string = string.lower()
    match = None
    for (_id, (name, s, alias)) in appIds.items():
        new_match = False
        if string in name.lower():
            if string == name.lower():
                return _id  #Exact match
            new_match = True
        elif s != '' and string in s.lower():
            if string == s.lower():
                return _id  #Exact match
            new_match = True
        elif alias != '' and string in alias.lower():
            if string == alias.lower():
                return _id  #Exact match
            new_match = True
        if new_match:
            if match is not None:
                print('Error: Multiple matches for "%s"' % string)
                return None
            match = _id

    return match  #Returns None if no match
