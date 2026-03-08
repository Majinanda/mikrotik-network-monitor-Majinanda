import sys
from pysnmp.hlapi import *

def test_snmp(host, community, iface='all'):
    print(f"Testing SNMP on {host} with community {community} and interface filter {iface}")
    
    auth_data = CommunityData(community, mpModel=1) # v2c
    
    iterator = nextCmd(
        SnmpEngine(),
        auth_data,
        UdpTransportTarget((host, 161), timeout=2, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.2')),  # ifDescr
        ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.10')), # ifInOctets
        ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.16')), # ifOutOctets
        lexicographicMode=False
    )
    
    total_in = 0
    total_out = 0
    
    for errorIndication, errorStatus, errorIndex, varBinds in iterator:
        if errorIndication:
            print(f"Error Indication: {errorIndication}")
            break
        elif errorStatus:
            print(f"Error Status: {errorStatus.prettyPrint()} at {errorIndex}")
            break
        else:
            print(f"Got varBinds length: {len(varBinds)}")
            for varBind in varBinds:
                print(' = '.join([x.prettyPrint() for x in varBind]))
                
            if len(varBinds) >= 3:
                if_descr = varBinds[0][1].prettyPrint().lower()
                print(f"Interface: {if_descr}")
                
                if iface != 'all':
                    if iface not in if_descr:
                        print("Skipped due to interface filter")
                        continue

                try:
                    in_bytes = int(varBinds[1][1])
                    out_bytes = int(varBinds[2][1])
                    total_in += in_bytes
                    total_out += out_bytes
                    print(f"Added In: {in_bytes}, Out: {out_bytes}")
                except Exception as e:
                    print(f"Exception parsing bytes: {e}")
            else:
                print("Not enough varbinds returned")
                
    print(f"Total In: {total_in}, Total Out: {total_out}")

if __name__ == '__main__':
    test_snmp('10.7.0.6', 'public')
