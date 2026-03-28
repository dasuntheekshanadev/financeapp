# FinanceOS - Personal Finance Manager

A full-stack personal finance web app built with FastAPI + SQLite + HTML.

## Features
- Login / Register with secure password hashing
- Dashboard with full financial overview
- Savings accounts (deposit, withdraw, track balance)
- Savings goals with progress tracking
- Monthly expenses tracking
- Installments (Koko, Mint Pay, Pay Z etc.)
- Subscriptions (Netflix, Claude, HBO etc.)
- Debt tracking with payment recording
- Income sources (salary + freelance)
- Full transaction history with search/filter
- Profile management (name, salary)

## Setup & Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the app
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or use the run script:
```bash
chmod +x run.sh && ./run.sh
```

### 3. Open in browser
```
http://localhost:8000
```

### 4. Register your account
- Go to /register
- Enter your name, username, password and monthly salary
- Login and start adding your data

## Project Structure
```
financeapp/
  main.py          - FastAPI routes
  database.py      - SQLite setup and schema
  auth.py          - JWT authentication
  requirements.txt - Python dependencies
  run.sh           - Quick start script
  finance.db       - SQLite database (auto-created)
  templates/
    login.html
    register.html
    dashboard.html
    transactions.html
```

## Tech Stack
- Backend: FastAPI (Python)
- Database: SQLite
- Auth: JWT cookies + bcrypt
- Frontend: Plain HTML/CSS/JS (no frameworks)
- Templates: Jinja2
