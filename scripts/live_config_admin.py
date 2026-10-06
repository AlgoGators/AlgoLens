#!/usr/bin/env python3
"""Authenticated HTTP only. Reset restores baseline values as a governed version."""
import argparse
import http.cookiejar
import ipaddress
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler

class Refused(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused('redirect_refused')

def base_url(value):
    parsed = urlsplit(value)
    try: loopback = ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError: loopback = parsed.hostname == 'localhost'
    if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('','/')
            or (parsed.scheme != 'https' and not loopback)):
        raise Refused('invalid_api_origin')
    return value.rstrip('/')

class Client:
    def __init__(self, origin, cookie_jar):
        self.origin = base_url(origin)
        self.jar = http.cookiejar.MozillaCookieJar(str(cookie_jar))
        try: self.jar.load(ignore_discard=True,ignore_expires=False)
        except (OSError,http.cookiejar.LoadError): raise Refused('cookie_jar_unavailable') from None
        self.opener = build_opener(ProxyHandler({}),NoRedirect(),HTTPCookieProcessor(self.jar))

    def call(self, path, body=None):
        request = Request(self.origin+path, data=None if body is None else json.dumps(body,allow_nan=False).encode(),
                          headers={'Accept':'application/json','Content-Type':'application/json'})
        if body is not None:
            # Apply exact domain/path/secure/expiry rules before selecting CSRF.
            self.jar.add_cookie_header(request)
            tokens = [part.split('=',1)[1] for part in (request.get_header('Cookie') or '').split('; ')
                      if part.startswith('csrf_access_token=')]
            if len(tokens) != 1 or not tokens[0] or any(ch in tokens[0] for ch in '\r\n'):
                raise Refused('csrf_cookie_unavailable')
            request.add_header('X-CSRF-TOKEN',tokens[0])
        try:
            with self.opener.open(request, timeout=20) as response:
                data=response.read(1_048_577)
                if len(data)>1_048_576: raise Refused('response_too_large')
                result=json.loads(data)
                if not isinstance(result,dict): raise Refused('invalid_response')
                return result
        except (HTTPError,URLError,OSError,ValueError):
            raise Refused('http_request_refused') from None

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api',required=True)
    parser.add_argument('--cookie-jar',required=True,type=Path)
    parser.add_argument('--strategy',required=True)
    parser.add_argument('--portfolio',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    for name in ('preview','submit','approve'):
        sub=commands.add_parser(name)
        sub.add_argument('--reason',required=True)
        sub.add_argument('--expected-active-version',default=None)
        if name=='approve': sub.add_argument('--request-id',required=True)
        else:
            sub.add_argument('--operation',choices=['override','reset_to_baseline'],default='override')
            sub.add_argument('--changes-file',type=Path)
    args=parser.parse_args(argv)
    try:
        path='/portfolio/strategies/'+quote(args.strategy,safe='')+'/config'
        body=None
        if args.command=='status': path+='?'+urlencode({'portfolio_id':args.portfolio})
        else:
            body={'portfolio_id':args.portfolio,'reason':args.reason,'expected_active_version':args.expected_active_version}
            if args.command=='approve': path+='/requests/'+quote(args.request_id,safe='')+'/approve'
            else:
                changes={} if args.changes_file is None else json.loads(args.changes_file.read_text())
                body.update(changes=changes,operation=args.operation)
                path+='/preview' if args.command=='preview' else '/requests'
        result=Client(args.api,args.cookie_jar).call(path,body)
        allowed={'version_id','activation_id','operation','base_sha256','effective_sha256','changed_paths',
                 'execution_authorized','active','requests','expected_active_version','reset_semantics'}
        print(json.dumps({k:v for k,v in result.items() if k in allowed},sort_keys=True))
        return 0
    except (Refused,OSError,ValueError,TypeError):
        print('Configuration request refused; verify session, scope and current configuration.',file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
