import os, sqlite3, tempfile, time, unittest
from pathlib import Path
from fastapi.testclient import TestClient

TEMP=tempfile.TemporaryDirectory()
os.environ.update(DATABASE_PATH=str(Path(TEMP.name)/'db.sqlite'),UPLOAD_DIR=str(Path(TEMP.name)/'uploads'),PUBLIC_HOST='192.168.1.24',PORT='8766',MAX_UPLOAD_SIZE='10485760')
from app.main import app, cleanup

class PasteDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(app); cls.client=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None); TEMP.cleanup()
    def paste(self,**kwargs):
        r=self.client.post('/api/paste',json={'text_content':'Olá <mundo>','expiration':86400,**kwargs})
        self.assertEqual(r.status_code,201,r.text); return r.json()
    def upload(self,name,data,**kwargs):
        r=self.client.post('/api/upload',files={'file':(name,data,'application/octet-stream')},data=kwargs)
        self.assertEqual(r.status_code,201,r.text); return r.json()
    def test_text_urls_and_raw(self):
        x=self.paste(format='code',title='hello.py'); pid=x['id']
        self.assertEqual(x['url'],f'http://192.168.1.24:8766/{pid}')
        self.assertEqual(x['raw_url'],f'http://192.168.1.24:8766/raw/{pid}')
        self.assertIn('Olá',self.client.get('/'+pid).text)
        r=self.client.get('/raw/'+pid); self.assertEqual(r.text,'Olá <mundo>'); self.assertTrue(r.headers['content-type'].startswith('text/plain'))
        self.assertEqual(self.client.get('/api/paste/'+pid).json()['text_content'],'Olá <mundo>')
        self.assertEqual(self.client.get('/docs').status_code,200)
    def test_image_and_range_video(self):
        data=b'\x89PNG\r\n\x1a\n'+b'x'*100
        x=self.upload('../../evil.png',data); pid=x['id']
        self.assertIn('evil.png',self.client.get('/'+pid).text)
        r=self.client.get('/raw/'+pid); self.assertEqual(r.content,data);self.assertEqual(r.headers['content-type'],'image/png')
        data=b'\0\0\0\x18ftypisom'+bytes(range(100))
        x=self.upload('movie.mp4',data);pid=x['id'];self.assertIn('<video',self.client.get('/'+pid).text)
        r=self.client.get('/raw/'+pid,headers={'Range':'bytes=10-29'})
        self.assertEqual(r.status_code,206);self.assertEqual(r.content,data[10:30]);self.assertEqual(r.headers['content-range'],f'bytes 10-29/{len(data)}')
        self.assertEqual(self.client.get('/raw/'+pid,headers={'Range':'bytes=-5'}).content,data[-5:])
        self.assertEqual(self.client.get('/raw/'+pid,headers={'Range':'bytes=999-'}).status_code,416)
    def test_password_and_markdown_xss(self):
        x=self.paste(password='secret',format='markdown',text_content='Hello **world** <script>alert(1)</script> [x](javascript:alert(1))'); pid=x['id']
        guest=TestClient(app)
        self.assertIn('Digite a senha',guest.get('/'+pid).text)
        self.assertEqual(guest.get('/raw/'+pid).status_code,403)
        self.assertEqual(guest.get('/api/paste/'+pid).status_code,403)
        self.assertEqual(guest.post('/'+pid+'/unlock',data={'password':'wrong'}).status_code,403)
        self.assertEqual(guest.post('/'+pid+'/unlock',data={'password':'secret'},follow_redirects=False).status_code,303)
        page=guest.get('/'+pid).text
        self.assertIn('<strong>world</strong>',page);self.assertNotIn('<script>',page);self.assertNotIn('javascript:',page)
        self.assertEqual(guest.get('/raw/'+pid).status_code,200)
    def test_expiration_physical_cleanup(self):
        x=self.upload('expired.pdf',b'%PDF-1.4'+b'x'*20,expiration='600');pid=x['id']
        with sqlite3.connect(os.environ['DATABASE_PATH']) as db:
            name=db.execute('SELECT stored_filename FROM pastes WHERE id=?',(pid,)).fetchone()[0]
            db.execute('UPDATE pastes SET expires_at=? WHERE id=?',(int(time.time())-1,pid))
        self.assertEqual(self.client.get('/'+pid).status_code,404)
        self.assertFalse((Path(os.environ['UPLOAD_DIR'])/name).exists())
    def test_one_view_claim(self):
        x=self.upload('once.webm',b'\x1a\x45\xdf\xa3'+bytes(range(100)),delete_after_view='true');pid=x['id']
        self.assertEqual(self.client.get('/qr/'+pid).status_code,200)
        with sqlite3.connect(os.environ['DATABASE_PATH']) as db:
            self.assertEqual(db.execute('SELECT views FROM pastes WHERE id=?',(pid,)).fetchone()[0],0)
        self.assertEqual(self.client.get('/'+pid).status_code,200)
        stranger=TestClient(app)
        self.assertEqual(stranger.get('/'+pid).status_code,404)
        self.assertEqual(stranger.get('/raw/'+pid).status_code,404)
        self.assertEqual(self.client.get('/raw/'+pid,headers={'Range':'bytes=5-10'}).status_code,206)
        with sqlite3.connect(os.environ['DATABASE_PATH']) as db:
            self.assertEqual(db.execute('SELECT views FROM pastes WHERE id=?',(pid,)).fetchone()[0],1)
            db.execute('UPDATE pastes SET claimed_until=? WHERE id=?',(int(time.time())-1,pid))
        cleanup();self.assertEqual(self.client.get('/'+pid).status_code,404)
    def test_direct_raw_once_and_delete(self):
        x=self.paste(delete_after_view=True);pid=x['id']
        self.assertEqual(TestClient(app).get('/raw/'+pid).status_code,200)
        self.assertEqual(TestClient(app).get('/'+pid).status_code,404)
        x=self.paste();pid=x['id']
        self.assertEqual(self.client.delete('/api/paste/'+pid).status_code,403)
        self.assertEqual(self.client.delete('/api/paste/'+pid,headers={'X-Delete-Token':x['delete_token']}).status_code,200)
        self.assertEqual(self.client.get('/'+pid).status_code,404)
    def test_restart_persistence(self):
        x=self.paste(text_content='persistência')
        with TestClient(app) as restarted:
            self.assertEqual(restarted.get('/raw/'+x['id']).text,'persistência')

if __name__=='__main__':unittest.main()
