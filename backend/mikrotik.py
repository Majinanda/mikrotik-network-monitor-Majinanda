import os
import routeros_api
import logging
import random
import paramiko
import subprocess
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("mikrotik")
# Use a relative path for the log file
# (This is a persistent connection pool with thread safety)
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snmp_debug.log")
fh = logging.FileHandler(log_path)
fh.setLevel(logging.ERROR)
logger.addHandler(fh)
# Note: we no longer depend on global env variables for the router credentials
# MIKROTIK_HOST, MIKROTIK_USER, etc., are now fetched from the database Router objects.

# Global cache for persistent API connections
_api_connections = {}
_api_locks = {}

def _get_api_connection(router):
    """
    Returns a persistent routeros_api Connection object and Mutex Lock for the given router.
    If the connection doesn't exist or is dropped, it establishes a new one.
    """
    global _api_connections, _api_locks
    router_id = router.id
    
    if router_id not in _api_locks:
        _api_locks[router_id] = threading.Lock()
    
    # Check if we already have an active connection
    if router_id in _api_connections:
        conn_obj = _api_connections[router_id]
        
        # Test if it's still alive with a lightweight command
        try:
            with _api_locks[router_id]:
                api = conn_obj.get_api()
                # If this doesn't raise, the connection is alive
                api.get_resource('/system/identity').get()
            return api, _api_locks[router_id]
        except Exception as e:
            logger.warning(f"Persistent API connection dropped for {router.name}, reconnecting: {e}")
            try:
                conn_obj.disconnect()
            except:
                pass
            del _api_connections[router_id]
            
    # Establish new connection
    try:
        connection = routeros_api.RouterOsApiPool(
            router.host,
            username=router.username,
            password=router.password,
            port=getattr(router, 'api_port', 8728),
            plaintext_login=True
        )
        api = connection.get_api()
        _api_connections[router_id] = connection
        return api, _api_locks[router_id]
    except Exception as e:
        raise Exception(f"Failed to establish persistent API connection: {e}")

# Helper parsing function for SSH output
def parse_ssh_key_value(output_text):
    records = []
    lines = output_text.strip().split('\n')
    current_record = {}
    
    import re
    # Simple regex to extract key="value" or key=value
    pattern = re.compile(r'([a-zA-Z0-9\-]+)=(".*?"|\S+)')
    
    # MikroTik print text has empty lines between records or no empty lines?
    for line in lines:
        line = line.strip()
        if not line:
            if current_record:
                records.append(current_record)
                current_record = {}
            continue
        
        matches = pattern.findall(line)
        for key, val in matches:
            # strip quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            current_record[key] = val
            
        # In RouterOS 'detail' or 'as-value', each item usually prints on a few lines, numbered
        # We'll just append if we see a number at start, but regex is safer.
        
    if current_record:
        records.append(current_record)
        
    return records

# Mock data state to simulate changes
mock_users = []

def generate_mock_users():
    global mock_users
    if not mock_users:
        for i in range(1, 21):
            is_active = random.choice([True, True, True, False]) # 75% chance active
            mock_users.append({
                "name": f"user{i}",
                "service": "pppoe",
                "caller-id": "",
                "address": f"10.0.0.{10+i}" if is_active else "",
                "uptime": f"{random.randint(0, 5)}d {random.randint(0, 23)}h {random.randint(0, 59)}m" if is_active else "",
                "status": "online" if is_active else "offline",
                "comment": f"Lat: {random.uniform(-10, 10):.4f}, Lng: {random.uniform(100, 120):.4f}" # Mock coordinates
            })
    else:
        # Randomly connect/disconnect someone for realistic mock UI updates
        if random.random() < 0.1: # 10% chance to toggle someone
            idx = random.randint(0, len(mock_users)-1)
            u = mock_users[idx]
            if u["status"] == "online":
                u["status"] = "offline"
                u["address"] = ""
                u["uptime"] = ""
            else:
                u["status"] = "online"
                u["address"] = f"10.0.0.{10+idx+1}"
                u["uptime"] = "0s"

    return mock_users

def get_pppoe_users(router):
    # Mock data for testing when no real connection is available
    if not router.host or router.host == "mock":
        logger.info(f"Mocking MikroTik API Response for Router: {router.name}")
        return [
            {
                "id": f"*A{i}",
                "name": f"user{i}",
                "service": "pppoe",
                "caller-id": "00:11:22:33:44:55",
                "address": f"10.0.0.{i}",
                "uptime": f"{random.randint(1, 24)}h{random.randint(0, 59)}m",
                "encoding": "none",
                "session-id": "81300000",
                "limit-bytes-in": "0",
                "limit-bytes-out": "0",
                "status": "online" if random.choice([True, False, True, True]) else "offline",
                "router_id": router.id,
                "router_name": router.name
            } for i in range(1, 21)
        ]

    users = None
    last_error = ""

    # 1. Try API if enabled
    if getattr(router, 'use_api', True):
        try:
            api, lock = _get_api_connection(router)
            with lock:
                active_connections = api.get_resource('/ppp/active').get()
                secrets = api.get_resource('/ppp/secret').get()
            
            active_users = {conn.get('name'): conn for conn in active_connections}
            users = []
            for secret in secrets:
                username = secret.get('name')
                is_active = username in active_users
                user_data = {
                    "id": secret.get('.id'),
                    "name": username,
                    "service": secret.get('service', 'any'),
                    "status": "online" if is_active else "offline",
                    "router_id": router.id,
                    "router_name": router.name
                }
                if is_active:
                    ac = active_users[username]
                    user_data.update({
                        "caller-id": ac.get('caller-id', ''),
                        "address": ac.get('address', ''),
                        "uptime": ac.get('uptime', ''),
                        "encoding": ac.get('encoding', ''),
                        "session-id": ac.get('session-id', ''),
                        "limit-bytes-in": ac.get('limit-bytes-in', '0'),
                        "limit-bytes-out": ac.get('limit-bytes-out', '0'),
                    })
                if secret.get('comment'):
                    user_data['comment'] = secret.get('comment')
                users.append(user_data)
                
            return users
        except Exception as e:
            last_error = f"API Error: {e}"
            logger.warning(f"Router API failed for {router.name}: {e}. Falling back to next method if enabled.")

    # 2. Try SSH if API failed or disabled
    if getattr(router, 'use_ssh', False) and users is None:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_user = getattr(router, 'ssh_username', None) or router.username
            ssh_pass = getattr(router, 'ssh_password', None) or router.password
            
            client.connect(
                router.host, 
                port=getattr(router, 'ssh_port', 22), 
                username=ssh_user, 
                password=ssh_pass, 
                timeout=5
            )
            
            # Get active users
            stdin, stdout, stderr = client.exec_command("/ppp/active/print detail")
            active_text = stdout.read().decode('utf-8')
            active_records = parse_ssh_key_value(active_text)
            
            # Get secrets
            stdin, stdout, stderr = client.exec_command("/ppp/secret/print detail")
            secret_text = stdout.read().decode('utf-8')
            secret_records = parse_ssh_key_value(secret_text)
            
            client.close()
            
            active_users = {conn.get('name'): conn for conn in active_records if 'name' in conn}
            users = []
            
            for secret in secret_records:
                if 'name' not in secret: continue
                username = secret.get('name')
                is_active = username in active_users
                
                user_data = {
                    "id": secret.get('.id', username),
                    "name": username,
                    "service": secret.get('service', 'any'),
                    "status": "online" if is_active else "offline",
                    "router_id": router.id,
                    "router_name": router.name
                }
                
                if is_active:
                    ac = active_users[username]
                    user_data.update({
                        "caller-id": ac.get('caller-id', ''),
                        "address": ac.get('address', ''),
                        "uptime": ac.get('uptime', ''),
                        "encoding": ac.get('encoding', ''),
                        "session-id": ac.get('session-id', ''),
                        "limit-bytes-in": ac.get('limit-bytes-in', '0'),
                        "limit-bytes-out": ac.get('limit-bytes-out', '0'),
                    })
                if secret.get('comment'):
                    user_data['comment'] = secret.get('comment')
                users.append(user_data)
            
            return users
        except Exception as e:
            last_error = f"SSH Error: {e}"
            logger.error(f"Router SSH failed for {router.name}: {e}")

    if users is None:
        logger.error(f"Error connecting to MikroTik {router.name} (API & SSH failed). Last error: {last_error}")
        return []

def get_router_status(router):
    if getattr(router, 'host', None) == "mock" or not getattr(router, 'host', None):
        return {
            "id": router.id,
            "name": router.name,
            "online": True,
            "board_name": "Mock Router",
            "cpu_load": f"{random.randint(5, 50)}%",
            "free_memory": "100MiB",
            "uptime": f"{random.randint(1, 10)}d 4h 2m"
        }
    
    status = None
    last_error = ""
    
    # 1. Try API if enabled
    if getattr(router, 'use_api', True):
        try:
            api, lock = _get_api_connection(router)
            
            with lock:
                resource = api.get_resource('/system/resource').get()[0]
            
            status = {
                "id": router.id,
                "name": router.name,
                "online": True,
                "board_name": resource.get('board-name', 'Unknown'),
                "cpu_load": f"{resource.get('cpu-load', '0')}%",
                "free_memory": f"{int(resource.get('free-memory', 0)) // 1048576}MiB",
                "uptime": resource.get('uptime', 'Unknown')
            }
            
            return status
        except Exception as e:
            last_error = f"API Error: {e}"
            logger.warning(f"Error fetching router status API for {router.name}: {e}")

    # 2. Try SSH if API failed or disabled
    if getattr(router, 'use_ssh', False) and status is None:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_user = getattr(router, 'ssh_username', None) or router.username
            ssh_pass = getattr(router, 'ssh_password', None) or router.password
            
            client.connect(
                router.host, 
                port=getattr(router, 'ssh_port', 22), 
                username=ssh_user, 
                password=ssh_pass, 
                timeout=5
            )
            
            stdin, stdout, stderr = client.exec_command("/system/resource/print detail")
            res_text = stdout.read().decode('utf-8')
            records = parse_ssh_key_value(res_text)
            client.close()
            
            if records:
                rec = records[0]
                # SSH values might be slightly different format. 'free-memory': '243MiB'
                status = {
                    "id": router.id,
                    "name": router.name,
                    "online": True,
                    "board_name": rec.get('board-name', 'Unknown'),
                    "cpu_load": f"{rec.get('cpu-load', '0')}%",
                    "free_memory": rec.get('free-memory', 'Unknown'),
                    "uptime": rec.get('uptime', 'Unknown')
                }
                return status
            else:
                last_error = "SSH Error: Could not parse resource output"
        except Exception as e:
            last_error = f"SSH Error: {e}"
            logger.error(f"Error fetching router status SSH for {router.name}: {e}")
            
    # 3. Try Native SNMP if SNMP enabled and others failed
    if getattr(router, 'use_snmp', False) and status is None:
        try:
            snmp_host = getattr(router, 'snmp_host', None) or router.host
            snmp_port = getattr(router, 'snmp_port', 161)
            community = getattr(router, 'snmp_community', 'public')
            version = getattr(router, 'snmp_version', 'v2c')
            version_flag = '-v' + version.replace('v', '') if 'v' in version else '-v2c'
            cmd = ['snmpget', version_flag]
            
            if version_flag == '-v3':
                # SNMPv3 logic
                v3_user = getattr(router, 'snmp_username', None) or community or "admin"
                auth_pass = getattr(router, 'snmp_auth_password', None)
                auth_proto = getattr(router, 'snmp_auth_protocol', 'SHA')
                priv_pass = getattr(router, 'snmp_priv_password', None)
                priv_proto = getattr(router, 'snmp_priv_protocol', 'AES')
                
                cmd.extend(['-u', v3_user])
                if priv_pass:
                    cmd.extend(['-l', 'authPriv', '-a', auth_proto, '-A', auth_pass, '-x', priv_proto, '-X', priv_pass])
                elif auth_pass:
                    cmd.extend(['-l', 'authNoPriv', '-a', auth_proto, '-A', auth_pass])
                else:
                    cmd.extend(['-l', 'noAuthNoPriv'])
            else:
                cmd.extend(['-c', community])
                
            cmd.extend([f"{snmp_host}:{snmp_port}", '1.3.6.1.2.1.1.1.0', '1.3.6.1.2.1.1.3.0'])
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=3).decode('utf-8')
            
            # Simple parsing
            lines = output.strip().split('\n')
            descr = "Unknown"
            uptime_str = "Unknown"
            
            for line in lines:
                if '1.3.6.1.2.1.1.1.0' in line or 'sysDescr.0' in line:
                    parts = line.split(' = STRING: ')
                    if len(parts) > 1: descr = parts[1].strip()
                elif '1.3.6.1.2.1.1.3.0' in line or 'sysUpTimeInstance' in line:
                    # format: Timeticks: (123456) 1:23:45.67
                    parts = line.split(')')
                    if len(parts) > 1: 
                        uptime_raw = parts[1].strip()
                        # Clean up formatting to match our frontend if needed
                        uptime_str = uptime_raw.split('.')[0] # removing milliseconds
            
            status = {
                "id": router.id,
                "name": router.name,
                "online": True,
                "board_name": descr[:50] + "..." if len(descr) > 50 else descr,
                "cpu_load": "N/A (SNMP)",
                "free_memory": "N/A (SNMP)",
                "uptime": uptime_str
            }
            return status
        except Exception as e:
            last_error = f"SNMP Error: {e}"
            logger.error(f"Error fetching router status SNMP native for {router.name}: {e}")

    # All methods failed
    return {
        "id": router.id,
        "name": router.name,
        "online": False,
        "error": last_error or "All connection attempts failed."
    }

def get_router_interfaces(router):
    interfaces = []
    last_error = None
    
    # 1. Try API first
    if getattr(router, 'use_api', True) and getattr(router, 'username', None):
        try:
            api, lock = _get_api_connection(router)
            with lock:
                ifaces = api.get_resource('/interface')
                iface_list = ifaces.get()
            
            for iface in iface_list:
                interfaces.append({"name": iface.get('name', 'unknown'), "type": iface.get('type', 'unknown')})
            return interfaces
        except Exception as e:
            last_error = f"API Error: {e}"
            logger.error(f"Router API failed for {router.name} (Interfaces): {e}")

    # 2. Try SSH fallback
    if getattr(router, 'use_ssh', False) and getattr(router, 'ssh_username', None):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                router.host,
                port=getattr(router, 'ssh_port', 22),
                username=router.ssh_username,
                password=router.ssh_password,
                timeout=5,
                look_for_keys=False,
                allow_agent=False
            )
            stdin, stdout, stderr = ssh.exec_command('/interface print terse')
            output = stdout.read().decode('utf-8')
            ssh.close()
            
            lines = output.strip().split('\n')
            for line in lines:
                parts = line.split()
                name = "unknown"
                typ = "unknown"
                for p in parts:
                    if p.startswith('name='):
                        name = p.split('=', 1)[1]
                    elif p.startswith('type='):
                        typ = p.split('=', 1)[1]
                if name != "unknown":
                    interfaces.append({"name": name, "type": typ})
            return interfaces
        except Exception as e:
            last_error = f"SSH Error: {e}"
            logger.error(f"Router SSH failed for {router.name} (Interfaces): {e}")

    # 3. Try SNMP fallback
    if getattr(router, 'use_snmp', False):
        try:
            snmp_host = getattr(router, 'snmp_host', None) or router.host
            snmp_port = getattr(router, 'snmp_port', 161)
            community = getattr(router, 'snmp_community', 'public')
            version = getattr(router, 'snmp_version', 'v2c')
            version_flag = '-v' + version.replace('v', '') if 'v' in version else '-v2c'
            walk_cmd = 'snmpwalk' if version_flag == '-v1' else 'snmpbulkwalk'
            
            cmd = [walk_cmd, version_flag]
            if version_flag == '-v3':
                v3_user = getattr(router, 'snmp_username', None) or community or "admin"
                auth_pass = getattr(router, 'snmp_auth_password', None)
                auth_proto = getattr(router, 'snmp_auth_protocol', 'SHA')
                priv_pass = getattr(router, 'snmp_priv_password', None)
                priv_proto = getattr(router, 'snmp_priv_protocol', 'AES')
                
                cmd.extend(['-u', v3_user])
                if priv_pass:
                    cmd.extend(['-l', 'authPriv', '-a', auth_proto, '-A', auth_pass, '-x', priv_proto, '-X', priv_pass])
                elif auth_pass:
                    cmd.extend(['-l', 'authNoPriv', '-a', auth_proto, '-A', auth_pass])
                else:
                    cmd.extend(['-l', 'noAuthNoPriv'])
            else:
                cmd.extend(['-c', community])
                
            cmd.extend(['-Onq', f"{snmp_host}:{snmp_port}", '1.3.6.1.2.1.2.2.1.2'])
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=5).decode('utf-8')
            
            lines = output.strip().split('\n')
            for line in lines:
                if '.1.3.6.1.2.1.2.2.1.2.' in line:
                    parts = line.split(' ', 1)
                    if len(parts) > 1:
                        name = parts[1].replace('"', '').strip()
                        interfaces.append({"name": name, "type": "snmp_detected"})
            return interfaces
        except Exception as e:
            last_error = f"SNMP Error: {e}"
            logger.error(f"Router SNMP failed for {router.name} (Interfaces): {e}")

    logger.error(f"Error connecting to MikroTik {router.name} for interfaces. Last error: {last_error}")
    return []

def get_router_traffic(router, override_iface=None):
    if not getattr(router, 'use_snmp', False):
        raise Exception("SNMP is not enabled for this router")
        
    snmp_host = getattr(router, 'snmp_host', None) or router.host
    snmp_port = getattr(router, 'snmp_port', 161)
    
    total_in = 0
    total_out = 0
    
    try:
        snmp_iface = override_iface if override_iface else (getattr(router, 'snmp_interface', 'all') or 'all')
        snmp_iface = snmp_iface.lower()
        community = getattr(router, 'snmp_community', 'public')
        version = getattr(router, 'snmp_version', 'v2c')
        version_flag = '-v' + version.replace('v', '') if 'v' in version else '-v2c'
        walk_cmd = 'snmpwalk' if version_flag == '-v1' else 'snmpbulkwalk'
        
        # We will use native snmpbulkwalk which fetches large tables 100x faster than standard walk
        cmd = [walk_cmd, version_flag]
        if version_flag == '-v3':
            v3_user = getattr(router, 'snmp_username', None) or community or "admin"
            auth_pass = getattr(router, 'snmp_auth_password', None)
            auth_proto = getattr(router, 'snmp_auth_protocol', 'SHA')
            priv_pass = getattr(router, 'snmp_priv_password', None)
            priv_proto = getattr(router, 'snmp_priv_protocol', 'AES')
            
            cmd.extend(['-u', v3_user])
            if priv_pass:
                cmd.extend(['-l', 'authPriv', '-a', auth_proto, '-A', auth_pass, '-x', priv_proto, '-X', priv_pass])
            elif auth_pass:
                cmd.extend(['-l', 'authNoPriv', '-a', auth_proto, '-A', auth_pass])
            else:
                cmd.extend(['-l', 'noAuthNoPriv'])
        else:
            cmd.extend(['-c', community])
            
        cmd.extend(['-Onq', f"{snmp_host}:{snmp_port}", '1.3.6.1.2.1.2.2.1'])
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=5).decode('utf-8')
        
        # Parse the snmpwalk output
        # Format for -Onq: .1.3.6.1.2.1.2.2.1.2.1 "ether1"
        lines = output.strip().split('\n')
        
        # First gather interface indices
        if_map = {} # ifIndex -> name
        
        for line in lines:
            # ifDescr = 1.3.6.1.2.1.2.2.1.2
            if '.1.3.6.1.2.1.2.2.1.2.' in line:
                try:
                    parts = line.split(' ', 1)
                    idx = parts[0].split('.')[-1]
                    name = parts[1].replace('"', '').strip().lower()
                    if_map[idx] = name
                except: pass
                
        # Now gather traffic for those indices
        for line in lines:
            # ifInOctets = 1.3.6.1.2.1.2.2.1.10
            if '.1.3.6.1.2.1.2.2.1.10.' in line:
                try:
                    parts = line.split(' ')
                    idx = parts[0].split('.')[-1]
                    val = int(parts[-1])
                    
                    iface_name = if_map.get(idx, "")
                    if snmp_iface == 'all' or snmp_iface in iface_name:
                        total_in += val
                except: pass
                
            # ifOutOctets = 1.3.6.1.2.1.2.2.1.16
            elif '.1.3.6.1.2.1.2.2.1.16.' in line:
                try:
                    parts = line.split(' ')
                    idx = parts[0].split('.')[-1]
                    val = int(parts[-1])
                    
                    iface_name = if_map.get(idx, "")
                    if snmp_iface == 'all' or snmp_iface in iface_name:
                        total_out += val
                except: pass
                
    except Exception as e:
        logger.error(f"Native snmpwalk failed for {router.name}: {e}")
        
    return {
        "router_id": router.id,
        "name": router.name,
        "rx_bytes": total_in,
        "tx_bytes": total_out,
        "timestamp": datetime.utcnow().isoformat()
    }

