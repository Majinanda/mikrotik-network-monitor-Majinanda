import os
import logging
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from sqlalchemy.orm import Session
from database import init_db, get_db, ConnectionLog, ActiveUsersLog, User, Router
from mikrotik import get_pppoe_users, get_router_status, get_router_traffic, get_router_interfaces
from notifier import send_notification
from datetime import datetime, timedelta
from auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    verify_password,
    get_password_hash,
    get_current_active_user,
    get_user,
    get_current_admin_user
)
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MikroTik Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
init_db()

# Global state for monitoring changes
# Stores {router_id: {username: status}}
previous_state = {}

# --- Background Monitoring Task ---
async def monitoring_loop_task():
    global previous_state
    while True:
        logger.info("Starting monitoring loop iteration...")
        try:
            with next(get_db()) as db:
                routers = db.query(Router).filter(Router.is_active == True).all()
                
                for router in routers:
                    current_router_users = {}
                    try:
                        users = get_pppoe_users(router)
                        active_count = 0
                        
                        for user in users:
                            username = user['name']
                            status = user['status']
                            current_router_users[username] = status
                            
                            if status == "online":
                                active_count += 1
                            
                            # Check previous state to generate logs/notifications
                            prev_status = previous_state.get(router.id, {}).get(username)
                            
                            if prev_status != status:
                                # State changed!
                                if prev_status is not None: # Only log/notify if it's a change from a known previous state
                                    logger.info(f"User {username} on {router.name} changed status from {prev_status} to {status}")
                                    
                                    # Log to database
                                    log_event = "connected" if status == "online" else "disconnected"
                                    log_entry = ConnectionLog(username=username, event=log_event, router_id=router.id)
                                    db.add(log_entry)
                                    
                                    # Send notification
                                    if status == "offline":
                                        send_notification(f"User '{username}' on '{router.name}' has disconnected from PPPoE.")
                                    elif status == "online":
                                        send_notification(f"User '{username}' on '{router.name}' has connected to PPPoE.")
                        
                        # Log active count for this router
                        db.add(ActiveUsersLog(active_count=active_count, router_id=router.id))

                        # Update previous_state for this router
                        previous_state[router.id] = current_router_users

                    except Exception as e:
                        logger.error(f"Error processing router {router.name} (ID: {router.id}) in monitoring loop: {e}")
                
                # Cleanup old logs (older than 24h)
                cutoff = datetime.utcnow() - timedelta(days=1)
                db.query(ActiveUsersLog).filter(ActiveUsersLog.timestamp < cutoff).delete()
                db.query(ConnectionLog).filter(ConnectionLog.timestamp < cutoff).delete() # Also clean connection logs
                db.commit()
                
        except Exception as e:
            logger.error(f"Error in main monitoring loop iteration: {e}")
            
        await asyncio.sleep(900) # Run every 15 minutes

@app.on_event("startup")
async def startup_event():
    try:
        init_db()
        logger.info("Database initialized successfully.")
        
        # Create default admin user if none exists
        with next(get_db()) as db:
            admin_user = db.query(User).filter(User.email == "admin@example.com").first()
            if not admin_user:
                logger.info("Creating default admin user: admin@example.com / admin")
                hashed_pw = get_password_hash("admin")
                admin = User(
                    email="admin@example.com",
                    hashed_password=hashed_pw,
                    role="admin"
                )
                db.add(admin)
                db.commit()
            
            # Create a default mock router for demo purposes if no routers exist
            first_router = db.query(Router).first()
            if not first_router:
                logger.info("Creating default demo router")
                demo_router = Router(
                    name="Demo Router (Mock)",
                    host="mock",
                    username="admin",
                    password="",
                    is_active=True
                )
                db.add(demo_router)
                db.commit()
                
    except Exception as e:
        logger.error(f"Error during startup database initialization or default user/router creation: {e}")

    logger.info("Starting monitoring loop task")
    # Initialize previous_state for all active routers
    with next(get_db()) as db:
        routers = db.query(Router).filter(Router.is_active == True).all()
        for router in routers:
            try:
                users = get_pppoe_users(router)
                previous_state[router.id] = {u["name"]: u["status"] for u in users}
            except Exception as e:
                logger.warning(f"Could not initialize state for router {router.name}: {e}")
    
    asyncio.create_task(monitoring_loop_task())

@app.post("/api/auth/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = get_user(db, form_data.username) # OAuth2 uses 'username', we map it to email
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

# --- Router Management API ---
class RouterCreate(BaseModel):
    name: str
    host: str
    username: Optional[str] = None
    password: Optional[str] = None
    use_api: bool = True
    api_port: int = 8728
    use_ssh: bool = False
    ssh_port: int = 22
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    use_snmp: bool = False
    snmp_host: Optional[str] = None
    snmp_port: int = 161
    snmp_version: str = "v2c"
    snmp_community: Optional[str] = "public"
    snmp_interface: Optional[str] = "all"
    snmp_username: Optional[str] = None
    snmp_auth_password: Optional[str] = None
    snmp_priv_password: Optional[str] = None

@app.get("/api/routers")
def api_get_routers(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    routers = db.query(Router).filter(Router.is_active == True).all()
    return [{
        "id": r.id, 
        "name": r.name, 
        "host": r.host, 
        "use_api": r.use_api, 
        "api_port": r.api_port, 
        "use_ssh": r.use_ssh, 
        "ssh_port": r.ssh_port, 
        "ssh_username": r.ssh_username,
        "use_snmp": r.use_snmp, 
        "snmp_host": r.snmp_host,
        "snmp_port": r.snmp_port, 
        "snmp_version": r.snmp_version,
        "snmp_community": r.snmp_community,
        "snmp_interface": r.snmp_interface,
        "snmp_username": r.snmp_username
        # Deliberately omitting passwords in GET
    } for r in routers]

@app.post("/api/routers")
def api_create_router(router_data: RouterCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    new_router = Router(
        name=router_data.name,
        host=router_data.host,
        username=router_data.username,
        password=router_data.password,
        use_api=router_data.use_api,
        api_port=router_data.api_port,
        use_ssh=router_data.use_ssh,
        ssh_port=router_data.ssh_port,
        ssh_username=router_data.ssh_username,
        ssh_password=router_data.ssh_password,
        use_snmp=router_data.use_snmp,
        snmp_host=router_data.snmp_host,
        snmp_port=router_data.snmp_port,
        snmp_version=router_data.snmp_version,
        snmp_community=router_data.snmp_community,
        snmp_interface=router_data.snmp_interface,
        snmp_username=router_data.snmp_username,
        snmp_auth_password=router_data.snmp_auth_password,
        snmp_priv_password=router_data.snmp_priv_password,
        is_active=True
    )
    db.add(new_router)
    db.commit()
    db.refresh(new_router)
    return {"message": "Router added successfully", "id": new_router.id}

@app.delete("/api/routers/{router_id}")
def api_delete_router(router_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    router = db.query(Router).filter(Router.id == router_id).first()
    if not router:
        raise HTTPException(status_code=404, detail="Router not found")
    router.is_active = False # Soft delete
    db.commit()
    return {"message": "Router deleted"}

@app.get("/api/routers/{router_id}/interfaces")
def api_get_router_interfaces(router_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    router = db.query(Router).filter(Router.id == router_id).first()
    if not router:
        raise HTTPException(status_code=404, detail="Router not found")
    
    interfaces = get_router_interfaces(router)
    return interfaces

# --- Dashboard API ---
@app.get("/api/users")
def api_get_users(router_id: int = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    users = []
    routers = db.query(Router).filter(Router.is_active == True)
    if router_id:
        routers = routers.filter(Router.id == router_id)
        
    for router in routers.all():
        try:
            users.extend(get_pppoe_users(router))
        except Exception as e:
            logger.error(f"Could not get users from router {router.name}: {e}")
            # Optionally, you might want to return an error for this specific router or skip it
            
    return users

@app.get("/api/router/status")
def api_get_router_status(router_id: int = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    statuses = []
    routers = db.query(Router).filter(Router.is_active == True)
    if router_id:
        routers = routers.filter(Router.id == router_id)
        
    for router in routers.all():
        try:
            statuses.append(get_router_status(router))
        except Exception as e:
            logger.error(f"Could not get status from router {router.name}: {e}")
            # Optionally, append an error status for this router
            statuses.append({"router_id": router.id, "name": router.name, "status": "error", "detail": str(e)})
    
    # Return single object if requesting specific router, else list
    if router_id and statuses:
        return statuses[0]
    return statuses

@app.get("/api/traffic")
def api_get_traffic(router_id: int = Query(None), interface: str = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    traffic_data = []
    routers = db.query(Router).filter(Router.is_active == True)
    if router_id:
        routers = routers.filter(Router.id == router_id)
        
    for router in routers.all():
        if router.use_snmp:
            try:
                data = get_router_traffic(router, interface)
                traffic_data.append(data)
            except Exception as e:
                logger.error(f"Could not get traffic from router {router.name}: {e}")
                traffic_data.append({"router_id": router.id, "name": router.name, "error": str(e)})
        else:
            traffic_data.append({"router_id": router.id, "name": router.name, "error": "SNMP not enabled"})
    
    # Return single object if requesting specific router, else list
    if router_id and traffic_data:
        return traffic_data[0]
    return traffic_data

@app.get("/api/stats")
def api_get_stats(router_id: int = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    users = []
    routers = db.query(Router).filter(Router.is_active == True)
    if router_id:
        routers = routers.filter(Router.id == router_id)
        
    for router in routers.all():
        try:
            users.extend(get_pppoe_users(router))
        except Exception as e:
            logger.error(f"Could not get users for stats from router {router.name}: {e}")
        
    active = sum(1 for u in users if u['status'] == 'online')
    down = sum(1 for u in users if u['status'] == 'offline')
    return {
        "total": len(users),
        "active": active,
        "down": down
    }

@app.get("/api/chart_data")
def api_get_chart_data(router_id: int = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    # Get data from the last hour
    cutoff = datetime.utcnow() - timedelta(hours=1)
    query = db.query(ActiveUsersLog).filter(ActiveUsersLog.timestamp >= cutoff).order_by(ActiveUsersLog.timestamp)
    
    if router_id:
        query = query.filter(ActiveUsersLog.router_id == router_id)
    
    logs = query.all()
    
    # Simple sub-sampling to not send too much data
    # If no router_id, aggregate counts for the same timestamp
    if not router_id:
        aggregated_logs = {}
        for log in logs:
            # Group by minute for aggregation
            timestamp_key = log.timestamp.replace(second=0, microsecond=0)
            if timestamp_key not in aggregated_logs:
                aggregated_logs[timestamp_key] = 0
            aggregated_logs[timestamp_key] += log.active_count
        
        # Sort by timestamp
        sorted_aggregated_logs = sorted(aggregated_logs.items())
        
        # Sub-sample if too many points
        sub_sampled_logs = sorted_aggregated_logs[::max(1, len(sorted_aggregated_logs)//60)] # max 60 data points
        
        labels = [ts.strftime("%H:%M") for ts, _ in sub_sampled_logs]
        data = [count for _, count in sub_sampled_logs]
    else:
        sub_sampled_logs = logs[::max(1, len(logs)//60)] # max 60 data points
        labels = [log.timestamp.strftime("%H:%M:%S") for log in sub_sampled_logs]
        data = [log.active_count for log in sub_sampled_logs]
    
    return {
        "labels": labels,
        "data": data
    }

@app.get("/api/logs")
def api_get_logs(router_id: int = Query(None), limit: int = 10, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    query = db.query(ConnectionLog).order_by(ConnectionLog.timestamp.desc())
    if router_id:
        query = query.filter(ConnectionLog.router_id == router_id)
        
    logs = query.limit(limit).all()
    
    router_map = {r.id: r.name for r in db.query(Router).all()}
    
    return [
        {
            "id": log.id,
            "username": log.username,
            "event": log.event,
            "timestamp": log.timestamp.isoformat(),
            "router_name": router_map.get(log.router_id, "Unknown Router")
        }
        for log in logs
    ]

# Mount frontend
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse("../frontend/index.html")

@app.get("/login.html")
def serve_login():
    return FileResponse("../frontend/login.html")
