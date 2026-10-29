import os, sqlite3, hashlib, secrets, hmac, json, re, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent.parent
DB = os.environ.get('BEA_DB', str(ROOT / 'data.sqlite3'))
HOST = os.environ.get('BEA_HOST', '127.0.0.1')
PORT = int(os.environ.get('BEA_PORT', '8000'))

@contextmanager
def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:
            yield c
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, salt TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, type TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), category TEXT NOT NULL, description TEXT NOT NULL, date TEXT NOT NULL, payment TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS budgets(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, month TEXT NOT NULL, category TEXT NOT NULL COLLATE NOCASE, amount INTEGER NOT NULL CHECK(amount>0), UNIQUE(user_id, month, category));
        CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, target INTEGER NOT NULL CHECK(target>0), saved INTEGER NOT NULL CHECK(saved>=0));
        CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, opening INTEGER NOT NULL DEFAULT 0, daily_limit INTEGER NOT NULL DEFAULT 0, monthly_budget INTEGER NOT NULL DEFAULT 0, theme TEXT NOT NULL DEFAULT 'light');
        ''')

def nonnegative(value):
    if str(value) in ('0','0.0','0.00'): return 0
    return amount(value)

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()

def amount(value):
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0 or d > 1000000000 or d.as_tuple().exponent < -2: raise ValueError()
        return int(d * 100)
    except (InvalidOperation, ValueError, TypeError): raise ValueError('Enter an amount greater than zero with at most two decimal places.')

def field(data, key, limit=100):
    v = data.get(key, '')
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > limit: raise ValueError(f'{key.title()} is required (maximum {limit} characters).')
    return v.strip()

def valid_date(value, month=False):
    try:
        datetime.date.fromisoformat(value + '-01' if month else value)
        if not re.fullmatch(r'\d{4}-\d{2}' if month else r'\d{4}-\d{2}-\d{2}', value): raise ValueError()
    except (ValueError, TypeError): raise ValueError('Enter a valid ' + ('month.' if month else 'date.'))
    return value

class Handler(BaseHTTPRequestHandler):
    def response(self, code, value, cookie=None):
        payload = json.dumps(value).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers(); self.wfile.write(payload)
    def body(self):
        n = int(self.headers.get('Content-Length','0'))
        if n > 16384: raise ValueError('Request too large.')
        try:
            obj = json.loads(self.rfile.read(n))
            if not isinstance(obj, dict): raise ValueError()
            return obj
        except (ValueError, UnicodeDecodeError): raise ValueError('Invalid request.')
    def user(self, c):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        token = cookie.get('session')
        return c.execute("SELECT users.id, users.name, users.email FROM users JOIN sessions ON users.id=sessions.user_id WHERE sessions.token=? AND sessions.expires > ?", (token.value if token else '', datetime.datetime.now(datetime.timezone.utc).isoformat())).fetchone()
    def handle_api(self):
        path = urlparse(self.path).path; method = self.command
        try:
            with db() as c:
                if method == 'POST' and path in ('/api/register','/api/login'):
                    d=self.body(); email=field(d,'email',254).lower(); pw=field(d,'password',128)
                    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise ValueError('Enter a valid email address.')
                    if path.endswith('register'):
                        name=field(d,'name',80)
                        if len(pw)<8: raise ValueError('Password must be at least 8 characters.')
                        salt=secrets.token_hex(16)
                        try: c.execute('INSERT INTO users(name,email,salt,password) VALUES(?,?,?,?)',(name,email,salt,password_hash(pw,salt)))
                        except sqlite3.IntegrityError: raise ValueError('An account with this email already exists.')
                    u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                    if not u or not hmac.compare_digest(password_hash(pw,u['salt']),u['password']): return self.response(401,{'error':'Invalid email or password.'})
                    token=secrets.token_urlsafe(32); expiry=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=7)).isoformat()
                    c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,u['id'],expiry))
                    return self.response(200,{'name':u['name'],'email':u['email']},f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800')
                u=self.user(c)
                if not u: return self.response(401,{'error':'Please sign in.'})
                uid=u['id']
                if method=='POST' and path=='/api/logout':
                    cookie=SimpleCookie(); cookie.load(self.headers.get('Cookie','')); c.execute('DELETE FROM sessions WHERE token=?',(cookie['session'].value,))
                    return self.response(200,{'ok':True},'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                if method=='GET' and path=='/api/me': return self.response(200,dict(u))
                if method=='PUT' and path=='/api/me':
                    name=field(self.body(),'name',80); c.execute('UPDATE users SET name=? WHERE id=?',(name,uid)); return self.response(200,{'name':name,'email':u['email']})
                if path=='/api/settings':
                    if method=='GET':
                        row=c.execute('SELECT opening,daily_limit,monthly_budget,theme FROM settings WHERE user_id=?',(uid,)).fetchone()
                        return self.response(200,dict(row) if row else {'opening':0,'daily_limit':0,'monthly_budget':0,'theme':'light'})
                    if method=='PUT':
                        d=self.body(); opening=nonnegative(d.get('opening')); daily=nonnegative(d.get('daily_limit')); monthly=nonnegative(d.get('monthly_budget')); theme=d.get('theme')
                        if theme not in ('light','dark'): raise ValueError('Invalid theme.')
                        c.execute('INSERT INTO settings VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET opening=excluded.opening,daily_limit=excluded.daily_limit,monthly_budget=excluded.monthly_budget,theme=excluded.theme',(uid,opening,daily,monthly,theme))
                        return self.response(200,{'ok':True})
                if path=='/api/goals' and method=='GET': return self.response(200,[dict(x) for x in c.execute('SELECT id,name,target,saved FROM goals WHERE user_id=? ORDER BY id DESC',(uid,))])
                goal=re.fullmatch(r'/api/goals/(\d+)',path)
                if (path=='/api/goals' and method=='POST') or (goal and method=='PUT'):
                    d=self.body(); name=field(d,'name',50); target=amount(d.get('target')); saved=nonnegative(d.get('saved'))
                    if goal:
                        cur=c.execute('UPDATE goals SET name=?,target=?,saved=? WHERE id=? AND user_id=?',(name,target,saved,int(goal[1]),uid))
                        if not cur.rowcount: return self.response(404,{'error':'Goal not found.'})
                    else: c.execute('INSERT INTO goals(user_id,name,target,saved) VALUES(?,?,?,?)',(uid,name,target,saved))
                    return self.response(200,{'ok':True})
                if goal and method=='DELETE':
                    cur=c.execute('DELETE FROM goals WHERE id=? AND user_id=?',(int(goal[1]),uid)); return self.response(200 if cur.rowcount else 404,{'ok':True} if cur.rowcount else {'error':'Goal not found.'})
                if path=='/api/sample' and method=='POST':
                    if c.execute('SELECT 1 FROM transactions WHERE user_id=? LIMIT 1',(uid,)).fetchone() or c.execute('SELECT 1 FROM goals WHERE user_id=? LIMIT 1',(uid,)).fetchone():
                        raise ValueError('Sample data can only be loaded into an empty ledger and goals list.')
                    today=datetime.date.today()
                    sample=[('income',1800000,'Salary','Sample: part-time internship',12),('expense',85000,'Food','Sample: groceries and snacks',1),('expense',32000,'Travel','Sample: metro and bus',2),('expense',125000,'Shopping','Sample: clothes',4),('expense',55000,'Education','Sample: study materials',5),('income',150000,'Pocket Money','Sample: allowance',8)]
                    c.executemany('INSERT INTO transactions(user_id,type,amount,category,description,date,payment) VALUES(?,?,?,?,?,?,?)',[(uid,t,a,cat,desc,(today-datetime.timedelta(days=days)).isoformat(),'Other') for t,a,cat,desc,days in sample])
                    c.execute('INSERT INTO goals(user_id,name,target,saved) VALUES(?,?,?,?)',(uid,'Sample: Emergency fund',2000000,650000))
                    return self.response(200,{'ok':True})
                if path=='/api/reset' and method=='POST':
                    for table in ('transactions','budgets','goals','settings'): c.execute('DELETE FROM '+table+' WHERE user_id=?',(uid,))
                    return self.response(200,{'ok':True})
                if path=='/api/transactions' and method=='GET':
                    rows=c.execute('SELECT id,type,amount,category,description,date,payment FROM transactions WHERE user_id=? ORDER BY date DESC,id DESC',(uid,)).fetchall()
                    return self.response(200,[dict(x) for x in rows])
                match=re.fullmatch(r'/api/transactions/(\d+)',path)
                if (path=='/api/transactions' and method=='POST') or (match and method=='PUT'):
                    d=self.body(); typ=field(d,'type'); cat=field(d,'category',60); desc=field(d,'description',120); date=valid_date(field(d,'date')); pay=field(d,'payment',60); money=amount(d.get('amount'))
                    if typ not in ('expense','income'): raise ValueError('Invalid transaction type.')
                    if match:
                        cur=c.execute('UPDATE transactions SET type=?,amount=?,category=?,description=?,date=?,payment=? WHERE id=? AND user_id=?',(typ,money,cat,desc,date,pay,int(match[1]),uid))
                        if not cur.rowcount: return self.response(404,{'error':'Transaction not found.'})
                    else: c.execute('INSERT INTO transactions(user_id,type,amount,category,description,date,payment) VALUES(?,?,?,?,?,?,?)',(uid,typ,money,cat,desc,date,pay))
                    return self.response(200,{'ok':True})
                if match and method=='DELETE':
                    cur=c.execute('DELETE FROM transactions WHERE id=? AND user_id=?',(int(match[1]),uid)); return self.response(200 if cur.rowcount else 404,{'ok':True} if cur.rowcount else {'error':'Transaction not found.'})
                if path=='/api/budgets' and method=='GET': return self.response(200,[dict(x) for x in c.execute('SELECT id,month,category,amount FROM budgets WHERE user_id=? ORDER BY month DESC,category',(uid,))])
                if path=='/api/budgets' and method=='POST':
                    d=self.body(); month=valid_date(field(d,'month'),True); cat=field(d,'category',60); money=amount(d.get('amount'))
                    c.execute('INSERT INTO budgets(user_id,month,category,amount) VALUES(?,?,?,?) ON CONFLICT(user_id,month,category) DO UPDATE SET amount=excluded.amount',(uid,month,cat,money)); return self.response(200,{'ok':True})
                match=re.fullmatch(r'/api/budgets/(\d+)',path)
                if match and method=='DELETE':
                    cur=c.execute('DELETE FROM budgets WHERE id=? AND user_id=?',(int(match[1]),uid)); return self.response(200 if cur.rowcount else 404,{'ok':True} if cur.rowcount else {'error':'Budget not found.'})
                return self.response(404,{'error':'Not found.'})
        except ValueError as e: return self.response(400,{'error':str(e)})
        except sqlite3.Error:
            return self.response(500,{'error':'Database error. Please try again.'})
    def do_GET(self):
        if self.path.startswith('/api/'): return self.handle_api()
        path=urlparse(self.path).path
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if path not in files: self.send_error(404); return
        name,typ=files[path]; content=(ROOT/'frontend'/name).read_bytes(); self.send_response(200); self.send_header('Content-Type',typ); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(content)
    def do_POST(self): self.handle_api()
    def do_PUT(self): self.handle_api()
    def do_DELETE(self): self.handle_api()

if __name__=='__main__':
    init(); print(f'Smart Expense and Budget Management System: http://{HOST}:{PORT}',flush=True); ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
