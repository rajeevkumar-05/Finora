# Finora — Smart Expense and Budget Management System

A local application combining the Finora interface with the planning features of the SmartBudget repository. Python serves the interface and JSON API; SQLite stores accounts, sessions, transactions, budgets, goals, and preferences. Amounts are stored as integer paise. The supplied design exports are preserved in `design-reference/`; The original SmartBudget repository was used as a reference during integration.

## Run on Windows

Install Python 3.10 or newer. No third-party packages or separate database service are needed. Open PowerShell in this folder and run:

```powershell
python backend/server.py
```

Open http://127.0.0.1:8000, create an account, and add transactions and budgets. If an earlier version is running, stop it with Ctrl+C and start this version so its database tables are initialized. Keep the terminal open while using the app. Data persists in `data.sqlite3` in the project folder. Back up that file while the server is stopped. It contains private financial information and password hashes; do not publish it.

Optional environment variables: `BEA_HOST` (default `127.0.0.1`), `BEA_PORT` (default `8000`), and `BEA_DB` (database file path). SQLite creates the database and tables automatically on startup. Example:

```powershell
$env:BEA_PORT = '8001'
python backend/server.py
```

The server is intended for local use. Internet deployment needs HTTPS, hardened session handling, rate limiting, and a proper deployment server.

## Features and rules

- Accounts, login, logout, profile name, and per-user data isolation.
- Income and expense records with edit, delete, search, type and month filters; category budgets and CSV export.
- Opening balance, overall daily and monthly limits, and in-app threshold alerts. Available balance is opening balance plus all income minus all expenses; opening balance is not income.
- Reports show category spending, five-day spending periods, daily average, days over the daily limit and a simple current-month estimate. Estimates are not guarantees. Alerts are in-app only.
- Purchase advisor compares a hypothetical price with the recorded balance and monthly budget. It does not save a transaction.
- Savings goals track manually entered progress; they do not deduct from the balance.
- Account settings include light/dark theme, JSON backup download, account-data reset, and optional labeled sample data. Sample data can be loaded only when the ledger and goals are empty. The JSON download is a data export; automatic import is not implemented. The original SmartBudget browser localStorage is not migrated automatically.
- Zero overall limits disable their alerts. Category limits are monthly and separate from the overall monthly limit; saving a category and month again updates it.

## Test

```powershell
python -m unittest discover -s tests -v
```

The supplied Word document is a generic report template and does not specify project-specific functional requirements. The original HTML design exports contain simulated features; automated savings rebalancing, password reset, currency conversion and external notifications are not implemented.
