import sqlite3
import re

db_path = "/home/ubuntu/dashboard/backend/mikrotik_dashboard.db"

def fix_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Check what columns exist
    c.execute("PRAGMA table_info(connection_logs)")
    cols = [col[1] for col in c.fetchall()]
    print("connection_logs columns:", cols)
    if "router_id" not in cols:
        print("Adding router_id to connection_logs...")
        c.execute("ALTER TABLE connection_logs ADD COLUMN router_id INTEGER REFERENCES routers(id)")
    
    c.execute("PRAGMA table_info(active_users_logs)")
    cols = [col[1] for col in c.fetchall()]
    if "router_id" not in cols:
        print("Adding router_id to active_users_logs...")
        c.execute("ALTER TABLE active_users_logs ADD COLUMN router_id INTEGER REFERENCES routers(id)")
        
    conn.commit()
    conn.close()
    print("Done")

if __name__ == "__main__":
    fix_db()
