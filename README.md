# MikroTik PPPoE Monitoring Dashboard

A real-time, high-performance monitoring dashboard for MikroTik routers. Track PPPoE users, system resources, and network interface traffic in real-time.

## 🚀 Quick Start (Deployment)

Assume you are starting on a fresh Linux server:

```bash
# 1. Clone the repository
git clone https://github.com/Majinanda/mikrotik-network-monitor-Majinanda.git
cd mikrotik-pppoe-dashboard

# 2. Setup Environment
cp backend/.env.example backend/.env
# EDIT backend/.env with your MikroTik credentials

# 3. Install & Start using NPM
npm run setup
npm start
```

## 🛠 Project Structure

```text
.
├── backend/            # FastAPI (Python) Application
│   ├── .env.example    # Configuration Template
│   ├── main.py        # API Entry Point
│   ├── mikrotik.py    # Router Interaction Logic
│   └── requirements.txt
├── frontend/           # Vanilla JS + Tailwind UI
│   ├── index.html
│   └── app.js
├── package.json        # NPM lifecycle manager
├── run.sh             # Startup script
└── .gitignore         # Strict security filters
```

## 🔒 Security Best Practices

- **Zero-Secret Commits**: Never commit `.env` files. We use `.env.example` as a template.
- **Persistent Sessions**: The backend handles persistent MikroTik API sessions with Thread-Safe locks.
- **Pre-commit Scanning**: Includes a script to check for leaked credentials before you push.

## 📡 Requirements
- Python 3.8+
- Node.js & NPM (for project management)
- MikroTik Router with API (8728) or SNMP enabled.
# mikrotik-network-monitor-Majinanda
