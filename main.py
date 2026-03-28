from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import date
import sqlite3

from database import get_db, init_db
from auth import hash_password, verify_password, create_token, get_current_user

app = FastAPI(title="Finance Manager")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    token = request.cookies.get("token")
    if token:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"})
    token = create_token({"user_id": user["id"]})
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("token", token, httponly=True, max_age=604800)
    return resp

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})

@app.post("/register", response_class=HTMLResponse)
def register(request: Request, username: str = Form(...), password: str = Form(...),
             full_name: str = Form(...), monthly_salary: float = Form(default=0)):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})
    hashed = hash_password(password)
    conn.execute("INSERT INTO users (username, password_hash, full_name, monthly_salary) VALUES (?, ?, ?, ?)",
                 (username, hashed, full_name, monthly_salary))
    conn.commit(); conn.close()
    return RedirectResponse("/login", status_code=302)

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("token")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: dict = Depends(get_current_user)):
    conn = get_db()
    uid = user["id"]
    goals = conn.execute("SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    accounts = conn.execute("SELECT * FROM savings_accounts WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    debts = conn.execute("SELECT * FROM debts WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC", (uid,)).fetchall()
    installments = conn.execute("SELECT * FROM installments WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC", (uid,)).fetchall()
    subscriptions = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    expenses = conn.execute("SELECT * FROM monthly_expenses WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC", (uid,)).fetchall()
    income_sources = conn.execute("SELECT * FROM income_sources WHERE user_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    recent_tx = conn.execute("""
        SELECT t.*, sa.name as account_name, g.title as goal_title
        FROM transactions t
        LEFT JOIN savings_accounts sa ON t.account_id = sa.id
        LEFT JOIN goals g ON t.goal_id = g.id
        WHERE t.user_id = ? ORDER BY t.created_at DESC LIMIT 10
    """, (uid,)).fetchall()
    conn.close()

    total_savings = sum(a["balance"] for a in accounts)
    total_debt = sum(d["remaining_amount"] for d in debts)
    total_monthly_expenses = sum(e["amount"] for e in expenses)
    total_installments = sum(i["monthly_amount"] for i in installments)
    total_subscriptions = sum(s["amount"] for s in subscriptions if s["is_active"])
    total_income = sum(i["amount"] for i in income_sources) + user["monthly_salary"]
    total_outgoing = total_monthly_expenses + total_installments + total_subscriptions
    net_monthly = total_income - total_outgoing

    goals_list = [dict(g) for g in goals]
    for g in goals_list:
        g["progress"] = round((g["current_amount"] / g["target_amount"]) * 100, 1) if g["target_amount"] > 0 else 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "goals": goals_list,
        "accounts": [dict(a) for a in accounts],
        "debts": [dict(d) for d in debts],
        "installments": [dict(i) for i in installments],
        "subscriptions": [dict(s) for s in subscriptions],
        "expenses": [dict(e) for e in expenses],
        "income_sources": [dict(i) for i in income_sources],
        "recent_tx": [dict(t) for t in recent_tx],
        "total_savings": total_savings, "total_debt": total_debt,
        "total_monthly_expenses": total_monthly_expenses,
        "total_installments": total_installments,
        "total_subscriptions": total_subscriptions,
        "total_income": total_income, "total_outgoing": total_outgoing,
        "net_monthly": net_monthly, "today": date.today().isoformat(),
    })

@app.post("/goals/add")
def add_goal(user: dict = Depends(get_current_user),
             title: str = Form(...), description: str = Form(default=""),
             target_amount: float = Form(...), deadline: str = Form(default=""),
             category: str = Form(default="general")):
    conn = get_db()
    conn.execute("INSERT INTO goals (user_id, title, description, target_amount, deadline, category) VALUES (?,?,?,?,?,?)",
                 (user["id"], title, description, target_amount, deadline or None, category))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#goals", status_code=302)

@app.post("/goals/{goal_id}/add-savings")
def add_to_goal(goal_id: int, user: dict = Depends(get_current_user),
                amount: float = Form(...), description: str = Form(default="Added savings")):
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id = ? AND user_id = ?", (goal_id, user["id"])).fetchone()
    if not goal: conn.close(); raise HTTPException(404)
    new_amount = goal["current_amount"] + amount
    status = "completed" if new_amount >= goal["target_amount"] else "active"
    conn.execute("UPDATE goals SET current_amount = ?, status = ? WHERE id = ?", (new_amount, status, goal_id))
    conn.execute("INSERT INTO transactions (user_id, goal_id, type, amount, description, category, date) VALUES (?,?,?,?,?,?,?)",
                 (user["id"], goal_id, "goal_deposit", amount, description, "savings", date.today().isoformat()))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#goals", status_code=302)

@app.post("/goals/{goal_id}/delete")
def delete_goal(goal_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#goals", status_code=302)

@app.post("/accounts/add")
def add_account(user: dict = Depends(get_current_user),
                name: str = Form(...), bank: str = Form(default=""),
                account_type: str = Form(default="savings"),
                balance: float = Form(default=0), interest_rate: float = Form(default=0),
                notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO savings_accounts (user_id, name, bank, account_type, balance, interest_rate, notes) VALUES (?,?,?,?,?,?,?)",
                 (user["id"], name, bank, account_type, balance, interest_rate, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#accounts", status_code=302)

@app.post("/accounts/{acc_id}/deposit")
def deposit(acc_id: int, user: dict = Depends(get_current_user),
            amount: float = Form(...), description: str = Form(default="Deposit")):
    conn = get_db()
    acc = conn.execute("SELECT * FROM savings_accounts WHERE id = ? AND user_id = ?", (acc_id, user["id"])).fetchone()
    if not acc: conn.close(); raise HTTPException(404)
    conn.execute("UPDATE savings_accounts SET balance = balance + ? WHERE id = ?", (amount, acc_id))
    conn.execute("INSERT INTO transactions (user_id, account_id, type, amount, description, category, date) VALUES (?,?,?,?,?,?,?)",
                 (user["id"], acc_id, "deposit", amount, description, "savings", date.today().isoformat()))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#accounts", status_code=302)

@app.post("/accounts/{acc_id}/withdraw")
def withdraw(acc_id: int, user: dict = Depends(get_current_user),
             amount: float = Form(...), description: str = Form(default="Withdrawal")):
    conn = get_db()
    acc = conn.execute("SELECT * FROM savings_accounts WHERE id = ? AND user_id = ?", (acc_id, user["id"])).fetchone()
    if not acc: conn.close(); raise HTTPException(404)
    conn.execute("UPDATE savings_accounts SET balance = balance - ? WHERE id = ?", (amount, acc_id))
    conn.execute("INSERT INTO transactions (user_id, account_id, type, amount, description, category, date) VALUES (?,?,?,?,?,?,?)",
                 (user["id"], acc_id, "withdrawal", amount, description, "savings", date.today().isoformat()))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#accounts", status_code=302)

@app.post("/accounts/{acc_id}/delete")
def delete_account(acc_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM savings_accounts WHERE id = ? AND user_id = ?", (acc_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#accounts", status_code=302)

@app.post("/debts/add")
def add_debt(user: dict = Depends(get_current_user),
             name: str = Form(...), lender: str = Form(default=""),
             total_amount: float = Form(...), remaining_amount: float = Form(...),
             monthly_payment: float = Form(default=0), interest_rate: float = Form(default=0),
             due_date: str = Form(default=""), notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO debts (user_id, name, lender, total_amount, remaining_amount, monthly_payment, interest_rate, due_date, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                 (user["id"], name, lender, total_amount, remaining_amount, monthly_payment, interest_rate, due_date or None, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#debts", status_code=302)

@app.post("/debts/{debt_id}/pay")
def pay_debt(debt_id: int, user: dict = Depends(get_current_user), amount: float = Form(...)):
    conn = get_db()
    debt = conn.execute("SELECT * FROM debts WHERE id = ? AND user_id = ?", (debt_id, user["id"])).fetchone()
    if not debt: conn.close(); raise HTTPException(404)
    new_remaining = max(0, debt["remaining_amount"] - amount)
    status = "cleared" if new_remaining == 0 else "active"
    conn.execute("UPDATE debts SET remaining_amount = ?, status = ? WHERE id = ?", (new_remaining, status, debt_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, description, category, date) VALUES (?,?,?,?,?,?)",
                 (user["id"], "debt_payment", amount, f"Payment: {debt['name']}", "debt", date.today().isoformat()))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#debts", status_code=302)

@app.post("/debts/{debt_id}/delete")
def delete_debt(debt_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM debts WHERE id = ? AND user_id = ?", (debt_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#debts", status_code=302)

@app.post("/installments/add")
def add_installment(user: dict = Depends(get_current_user),
                    name: str = Form(...), provider: str = Form(default=""),
                    total_amount: float = Form(...), monthly_amount: float = Form(...),
                    total_months: int = Form(...), paid_months: int = Form(default=0),
                    due_day: int = Form(default=1), notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO installments (user_id, name, provider, total_amount, monthly_amount, total_months, paid_months, due_day, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                 (user["id"], name, provider, total_amount, monthly_amount, total_months, paid_months, due_day, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#installments", status_code=302)

@app.post("/installments/{inst_id}/pay")
def pay_installment(inst_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    inst = conn.execute("SELECT * FROM installments WHERE id = ? AND user_id = ?", (inst_id, user["id"])).fetchone()
    if not inst: conn.close(); raise HTTPException(404)
    new_paid = inst["paid_months"] + 1
    is_active = 0 if new_paid >= inst["total_months"] else 1
    conn.execute("UPDATE installments SET paid_months = ?, is_active = ? WHERE id = ?", (new_paid, is_active, inst_id))
    conn.execute("INSERT INTO transactions (user_id, type, amount, description, category, date) VALUES (?,?,?,?,?,?)",
                 (user["id"], "installment", inst["monthly_amount"], f"Installment: {inst['name']}", "installment", date.today().isoformat()))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#installments", status_code=302)

@app.post("/installments/{inst_id}/delete")
def delete_installment(inst_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM installments WHERE id = ? AND user_id = ?", (inst_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#installments", status_code=302)

@app.post("/subscriptions/add")
def add_subscription(user: dict = Depends(get_current_user),
                     name: str = Form(...), amount: float = Form(...),
                     currency: str = Form(default="LKR"),
                     billing_cycle: str = Form(default="monthly"),
                     next_billing_date: str = Form(default=""),
                     notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO subscriptions (user_id, name, amount, currency, billing_cycle, next_billing_date, notes) VALUES (?,?,?,?,?,?,?)",
                 (user["id"], name, amount, currency, billing_cycle, next_billing_date or None, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#subscriptions", status_code=302)

@app.post("/subscriptions/{sub_id}/toggle")
def toggle_subscription(sub_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    sub = conn.execute("SELECT * FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user["id"])).fetchone()
    if not sub: conn.close(); raise HTTPException(404)
    conn.execute("UPDATE subscriptions SET is_active = ? WHERE id = ?", (0 if sub["is_active"] else 1, sub_id))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#subscriptions", status_code=302)

@app.post("/subscriptions/{sub_id}/delete")
def delete_subscription(sub_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#subscriptions", status_code=302)

@app.post("/expenses/add")
def add_expense(user: dict = Depends(get_current_user),
                name: str = Form(...), amount: float = Form(...),
                category: str = Form(default="fixed"),
                due_day: int = Form(default=1), notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO monthly_expenses (user_id, name, amount, category, due_day, notes) VALUES (?,?,?,?,?,?)",
                 (user["id"], name, amount, category, due_day, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#expenses", status_code=302)

@app.post("/expenses/{exp_id}/delete")
def delete_expense(exp_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM monthly_expenses WHERE id = ? AND user_id = ?", (exp_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#expenses", status_code=302)

@app.post("/income/add")
def add_income(user: dict = Depends(get_current_user),
               name: str = Form(...), amount: float = Form(...),
               type: str = Form(default="fixed"),
               frequency: str = Form(default="monthly"),
               notes: str = Form(default="")):
    conn = get_db()
    conn.execute("INSERT INTO income_sources (user_id, name, amount, type, frequency, notes) VALUES (?,?,?,?,?,?)",
                 (user["id"], name, amount, type, frequency, notes))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#income", status_code=302)

@app.post("/income/{inc_id}/delete")
def delete_income(inc_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM income_sources WHERE id = ? AND user_id = ?", (inc_id, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard#income", status_code=302)

@app.post("/profile/update")
def update_profile(user: dict = Depends(get_current_user),
                   full_name: str = Form(...), monthly_salary: float = Form(default=0)):
    conn = get_db()
    conn.execute("UPDATE users SET full_name = ?, monthly_salary = ? WHERE id = ?",
                 (full_name, monthly_salary, user["id"]))
    conn.commit(); conn.close()
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/transactions", response_class=HTMLResponse)
def all_transactions(request: Request, user: dict = Depends(get_current_user)):
    conn = get_db()
    txs = conn.execute("""
        SELECT t.*, sa.name as account_name, g.title as goal_title
        FROM transactions t
        LEFT JOIN savings_accounts sa ON t.account_id = sa.id
        LEFT JOIN goals g ON t.goal_id = g.id
        WHERE t.user_id = ? ORDER BY t.created_at DESC
    """, (user["id"],)).fetchall()
    conn.close()
    return templates.TemplateResponse("transactions.html", {
        "request": request, "user": user,
        "transactions": [dict(t) for t in txs]
    })
