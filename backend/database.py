import os
from sqlalchemy import create_engine, text, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mikrotik_dashboard.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Router(Base):
    __tablename__ = "routers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    host = Column(String)
    username = Column(String)
    password = Column(String)
    is_active = Column(Boolean, default=True)
    
    # Connection Protocols
    use_api = Column(Boolean, default=True)
    api_port = Column(Integer, default=8728)
    
    # Isolated SSH Settings
    use_ssh = Column(Boolean, default=False)
    ssh_port = Column(Integer, default=22)
    ssh_username = Column(String, nullable=True) # Defaults to global username if not set
    ssh_password = Column(String, nullable=True) # Defaults to global password if not set
    
    # Isolated SNMP Settings
    use_snmp = Column(Boolean, default=False)
    snmp_host = Column(String, nullable=True) # Defaults to router host if not set
    snmp_port = Column(Integer, default=161)
    snmp_version = Column(String, default="v2c") # v1, v2c, v3
    snmp_community = Column(String, nullable=True) # For v1/v2c
    snmp_interface = Column(String, default="all") # Specific IF to monitor (e.g. ether1)
    
    # SNMPv3 Settings
    snmp_username = Column(String, nullable=True)
    snmp_auth_password = Column(String, nullable=True)
    snmp_auth_protocol = Column(String, default="SHA") # MD5, SHA
    snmp_priv_password = Column(String, nullable=True) # For v3
    snmp_priv_protocol = Column(String, default="AES") # DES, AES

class ConnectionLog(Base):
    __tablename__ = "connection_logs"
    id = Column(Integer, primary_key=True, index=True)
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=True)
    username = Column(String, index=True)
    event = Column(String) # "connected" or "disconnected"
    timestamp = Column(DateTime, default=datetime.utcnow)
    router = relationship("Router")

class ActiveUsersLog(Base):
    __tablename__ = "active_users_logs"
    id = Column(Integer, primary_key=True, index=True)
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    active_count = Column(Integer)
    router = relationship("Router")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="viewer") # e.g. "admin", "viewer"
    is_active = Column(Boolean, default=True)

def init_db():
    Base.metadata.create_all(bind=engine)
    # SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS easily via SQLAlchemy
    # So we do a raw sql check and alter
    with engine.connect() as conn:
        try:
            # Check connection_logs
            rs = conn.execute(text("PRAGMA table_info(connection_logs)"))
            cols = [row[1] for row in rs]
            if "router_id" not in cols:
                conn.execute(text("ALTER TABLE connection_logs ADD COLUMN router_id INTEGER REFERENCES routers(id)"))
                
            # Check active_users_logs
            rs = conn.execute(text("PRAGMA table_info(active_users_logs)"))
            cols = [row[1] for row in rs]
            if "router_id" not in cols:
                conn.execute(text("ALTER TABLE active_users_logs ADD COLUMN router_id INTEGER REFERENCES routers(id)"))
                
            # Check users for role
            rs = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in rs]
            if "role" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'viewer'"))
            if "is_active" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            
            # Check routers for new protocols
            rs = conn.execute(text("PRAGMA table_info(routers)"))
            cols = [row[1] for row in rs]
            if "use_api" not in cols:
                conn.execute(text("ALTER TABLE routers ADD COLUMN use_api BOOLEAN DEFAULT 1"))
                conn.execute(text("ALTER TABLE routers RENAME COLUMN port TO api_port"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN use_ssh BOOLEAN DEFAULT 0"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN ssh_port INTEGER DEFAULT 22"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN use_snmp BOOLEAN DEFAULT 0"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_port INTEGER DEFAULT 161"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_community VARCHAR DEFAULT 'public'"))
                
            if "snmp_host" not in cols:
                # Add the isolated SNMP fields
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_host VARCHAR"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_version VARCHAR DEFAULT 'v2c'"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_username VARCHAR"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_auth_password VARCHAR"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_auth_protocol VARCHAR DEFAULT 'SHA'"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_priv_password VARCHAR"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_priv_protocol VARCHAR DEFAULT 'AES'"))
                
            if "snmp_interface" not in cols:
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_interface VARCHAR DEFAULT 'all'"))
                
            if "snmp_auth_protocol" not in cols:
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_auth_protocol VARCHAR DEFAULT 'SHA'"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN snmp_priv_protocol VARCHAR DEFAULT 'AES'"))
            
            if "ssh_username" not in cols:
                # Add the isolated SSH fields
                conn.execute(text("ALTER TABLE routers ADD COLUMN ssh_username VARCHAR"))
                conn.execute(text("ALTER TABLE routers ADD COLUMN ssh_password VARCHAR"))

            conn.commit()
                
        except Exception as e:
            print(f"Error during migration: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
