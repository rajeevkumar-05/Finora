import unittest, tempfile, os, sys, threading, json, urllib.request, urllib.error, http.cookiejar
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'backend'))
import server

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]); server.DB=os.path.join(cls.temp.name,'test.sqlite3'); server.init()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler); cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True); cls.thread.start(); cls.url='http://127.0.0.1:'+str(cls.http.server_port)
    @classmethod
    def tearDownClass(cls): cls.http.shutdown(); cls.http.server_close(); cls.temp.cleanup()
    def client(self): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(self,client,path,method='GET',body=None):
        req=urllib.request.Request(self.url+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
        try:
            with client.open(req) as r: return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e: return e.code,json.load(e)
    def test_full_workflow_and_isolation(self):
        a,b=self.client(),self.client()
        self.assertEqual(self.request(a,'transactions')[0],401)
        self.assertEqual(self.request(a,'register','POST',{'name':'A','email':'a@example.com','password':'password123'})[0],200)
        self.assertEqual(self.request(b,'register','POST',{'name':'B','email':'b@example.com','password':'password123'})[0],200)
        t={'type':'expense','amount':'125.50','description':'Groceries','category':'Food','payment':'UPI','date':'2026-10-12'}
        self.assertEqual(self.request(a,'transactions','POST',t)[0],200)
        rows=self.request(a,'transactions')[1]; self.assertEqual(rows[0]['amount'],12550); ident=rows[0]['id']
        self.assertEqual(self.request(b,'transactions')[1],[])
        self.assertEqual(self.request(b,f'transactions/{ident}','DELETE')[0],404)
        t['amount']='200.00'; self.assertEqual(self.request(a,f'transactions/{ident}','PUT',t)[0],200)
        self.assertEqual(self.request(a,'transactions')[1][0]['amount'],20000)
        self.assertEqual(self.request(a,'budgets','POST',{'month':'2026-10','category':'Food','amount':'250'})[0],200)
        self.assertEqual(self.request(a,'budgets')[1][0]['amount']-self.request(a,'transactions')[1][0]['amount'],5000)
        self.assertEqual(self.request(a,f'transactions/{ident}','DELETE')[0],200); self.assertEqual(self.request(a,'transactions')[1],[])
        self.assertEqual(self.request(a,'logout','POST',{})[0],200); self.assertEqual(self.request(a,'transactions')[0],401)
        self.assertEqual(self.request(a,'login','POST',{'email':'a@example.com','password':'password123'})[0],200); self.assertEqual(len(self.request(a,'budgets')[1]),1)
    def test_validation(self):
        c=self.client(); self.assertEqual(self.request(c,'register','POST',{'name':'V','email':'bad','password':'password123'})[0],400)
        self.assertEqual(self.request(c,'register','POST',{'name':'V','email':'v@example.com','password':'password123'})[0],200)
        t={'type':'expense','amount':'0','description':'x','category':'x','payment':'x','date':'2026-10-12'}
        for bad in ['0','-1','1.234','NaN']:
            t['amount']=bad; self.assertEqual(self.request(c,'transactions','POST',t)[0],400)
        t['amount']='1'; t['date']='2026-02-30'; self.assertEqual(self.request(c,'transactions','POST',t)[0],400)
        t['date']='2026-10-12'; t['description']=''; self.assertEqual(self.request(c,'transactions','POST',t)[0],400)
    def test_planning_settings_and_goals(self):
        a,b=self.client(),self.client()
        self.assertEqual(self.request(a,'register','POST',{'name':'Plan','email':'plan@example.com','password':'password123'})[0],200)
        self.assertEqual(self.request(b,'register','POST',{'name':'Other','email':'other@example.com','password':'password123'})[0],200)
        config={'opening':'1000','daily_limit':'300','monthly_budget':'2000','theme':'dark'}
        self.assertEqual(self.request(a,'settings','PUT',config)[0],200)
        self.assertEqual(self.request(a,'settings')[1]['opening'],100000)
        self.assertEqual(self.request(b,'settings')[1]['opening'],0)
        goal={'name':'Laptop','target':'2000','saved':'100'}
        self.assertEqual(self.request(a,'goals','POST',goal)[0],200)
        g=self.request(a,'goals')[1][0]; self.assertEqual(g['saved'],10000)
        self.assertEqual(self.request(b,f"goals/{g['id']}",'DELETE')[0],404)
        goal['saved']='125.50'; self.assertEqual(self.request(a,f"goals/{g['id']}",'PUT',goal)[0],200)
        self.assertEqual(self.request(a,'goals')[1][0]['saved'],12550)
        self.assertEqual(self.request(a,'sample','POST',{})[0],400)
        self.assertEqual(self.request(a,'reset','POST',{})[0],200)
        self.assertEqual(self.request(a,'goals')[1],[]); self.assertEqual(self.request(a,'settings')[1]['opening'],0)
        self.assertEqual(self.request(a,'sample','POST',{})[0],200)
        self.assertEqual(len(self.request(a,'transactions')[1]),6)
        self.assertEqual(self.request(a,'sample','POST',{})[0],400)
    def test_case_insensitive_budget_update(self):
        c=self.client(); self.request(c,'register','POST',{'name':'Case','email':'case@example.com','password':'password123'})
        self.request(c,'budgets','POST',{'month':'2026-10','category':'Food','amount':'100'})
        self.request(c,'budgets','POST',{'month':'2026-10','category':'food','amount':'200'})
        budgets=self.request(c,'budgets')[1]; self.assertEqual(len(budgets),1); self.assertEqual(budgets[0]['amount'],20000)
    def test_amount_unit(self):
        self.assertEqual(server.amount('99.99'),9999)
        with self.assertRaises(ValueError): server.amount('-1')
if __name__=='__main__': unittest.main()
