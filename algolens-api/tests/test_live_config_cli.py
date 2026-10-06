"""Owned loopback HTTP; redirects and cookies never cross an origin."""
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
from threading import Thread
import pytest

spec=importlib.util.spec_from_file_location('live_config_cli',Path(__file__).resolve().parents[2]/'scripts/live_config_admin.py')
cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)

@pytest.fixture
def server():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path,dict(self.headers)))
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            if self.path=='/redirect':
                self.send_response(302); self.send_header('Location','http://127.0.0.2:1/leak'); self.end_headers()
            elif self.path=='/error':
                self.send_response(403); self.end_headers(); self.wfile.write(b'cookie-secret csrf-secret')
            else:
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"execution_authorized":false}')
        def log_message(self,*args): pass
    httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=httpd.serve_forever,daemon=True); thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}',seen
    httpd.shutdown(); thread.join(); httpd.server_close()

def jar(tmp_path,*,domain='127.0.0.1',path='/',extra=False):
    name=tmp_path/'cookies'; cookies=http.cookiejar.MozillaCookieJar(str(name))
    def add(name,domain,path,value):
        cookies.set_cookie(http.cookiejar.Cookie(0,name,value,None,False,domain,False,False,path,True,False,None,True,None,None,{},False))
    add('csrf_access_token',domain,path,'csrf-secret'); add('access_token_cookie',domain,path,'cookie-secret')
    if extra: add('csrf_access_token','other.invalid','/','foreign-secret')
    cookies.save(ignore_discard=True); return name

def test_csrf_selected_for_origin_and_path(server,tmp_path):
    origin,seen=server
    result=cli.Client(origin,jar(tmp_path,extra=True)).call('/config',{'reason':'reviewed'})
    assert result=={'execution_authorized':False}
    headers=seen[0][1]
    assert headers['X-Csrf-Token']=='csrf-secret'
    assert 'foreign-secret' not in str(headers)

@pytest.mark.parametrize('domain,path',[('other.invalid','/'),('127.0.0.1','/not-this')])
def test_wrong_origin_or_path_never_sends(server,tmp_path,domain,path):
    origin,seen=server
    with pytest.raises(cli.Refused): cli.Client(origin,jar(tmp_path,domain=domain,path=path)).call('/config',{})
    assert seen==[]

@pytest.mark.parametrize('path',['/redirect','/error'])
def test_redirect_and_error_refused_without_secret(server,tmp_path,path):
    origin,seen=server
    with pytest.raises(cli.Refused) as error: cli.Client(origin,jar(tmp_path)).call(path,{})
    assert 'secret' not in str(error.value) and len(seen)==1

@pytest.mark.parametrize('url',['http://example.com','https://u:pass@example.com','https://example.com/path','https://example.com#cookie'])
def test_only_explicit_safe_origin(url):
    with pytest.raises(cli.Refused): cli.base_url(url)
