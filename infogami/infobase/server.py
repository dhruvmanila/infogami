"""Infobase server to expose the API.
"""
import web
import infobase
import _json as simplejson
import time

infobase.NotFound = Exception
infobase.InfobaseException = Exception

urls = (
    "/([^/]*)/get", "withkey",
    "/([^/]*)/get_many", "get_many",
    "/([^/]*)/things", "things",
    "/([^/]*)/versions", "versions",
    "/([^/]*)/write", "write",
    "/([^/]*)/account/(.*)", "account",
    "/([^/]*)/permission", "permission",
)

def jsonify(f):
    def g(self, *a, **kw):
        t1 = time.time()
        
        if not web.ctx.get('infobase_localmode'):
            cookies = web.cookies(infobase_auth_token=None)
            web.ctx.infobase_auth_token = cookies.infobase_auth_token
                
        d = {'status': 'ok'}
        try:
            d['result'] = f(self, *a, **kw)
        except (infobase.InfobaseException, AssertionError), e:
            import traceback
            traceback.print_exc()
            d['status'] = 'fail'
            d['message'] = str(e)
            d['traceback'] = traceback.format_exc()
        except Exception, e:
            import traceback
            traceback.print_exc()
            d['status'] = 'fail'
            d['message'] = 'InternalError: %s' % str(e)
            d['traceback'] = traceback.format_exc()
            
            # call web.internalerror to send email when web.internalerror is set to web.emailerrors
            web.internalerror()
            web.ctx.output = ""
        
        t2 = time.time()
        i = input(prettyprint=None, stats=None)
        
        if i.stats:
            d['stats'] = dict(time_taken=t2-t1)

        if i.prettyprint:
            result = simplejson.dumps(d, indent=4)
        else:
            result = simplejson.dumps(d)

        if web.ctx.get('infobase_localmode'):
            return result
        else:
            # set auth-token as cookie for remote connection.
            if web.ctx.get('infobase_auth_token'):
                web.setcookie('infobase_auth_token', web.ctx.infobase_auth_token)
            web.ctx.output = web.utf8(result)
    return g
    
def input(*a, **kw):
    if 'infobase_input' in web.ctx:
        return web.storify(web.ctx.infobase_input, *a, **kw)
    else:
        return web.input(*a, **kw)
    
_infobase = None
def get_site(sitename):
    import config
    global _infobase
    if not _infobase:
        import dbstore
        schema = dbstore.Schema()
        store = dbstore.DBStore(schema)
        _infobase = infobase.Infobase(store, config.secret_key)
    return _infobase.get(sitename)

class write:
    @jsonify
    def POST(self, sitename):
        site = get_site(sitename)
        i = input('query', comment=None, machine_comment=None)
        query = simplejson.loads(i.query)
        result = site.write(query, comment=i.comment, machine_comment=i.machine_comment)
        return result

class withkey:
    @jsonify
    def GET(self, sitename):
        try:
            i = input("key", revision=None, expand=False)
            site = get_site(sitename)
            revision = i.revision and int(i.revision)
            thing = site.withKey(i.key, revision=revision)
            return thing._get_data()
        except infobase.NotFound:
            return None

class get_many:
    @jsonify
    def GET(self, sitename):
        i = input("keys")
        keys = simplejson.loads(i['keys'])
        site = get_site(sitename)
        things = site.get_many(keys)
        return things
            
class things:
    @jsonify
    def GET(self, sitename):
        site = get_site(sitename)
        i = input('query')
        q = simplejson.loads(i.query)
        return site.things(q)

class versions:
    @jsonify
    def GET(self, sitename):
        site = get_site(sitename)
        i = input('query')
        q = simplejson.loads(i.query)
        return site.versions(q)
        
class permission:
    @jsonify
    def GET(self, sitename):
        site = get_site(sitename)
        i = input('key')
        return site.get_permissions(i.key)
        
class account:
    """Code for handling /account/.*"""
    def get_method(self):
        if web.ctx.get('infobase_localmode'):
            return web.ctx.infobase_method
        else:
            return web.ctx.method
        
    @jsonify
    def delegate(self, sitename, method):
        site = get_site(sitename)
        methodname = "%s_%s" % (self.get_method(), method)
        
        m = getattr(self, methodname, None)
        if m:
            return m(site)
        else:
            web.notfound()
            raise StopIteration
        
    GET = POST = delegate

    def POST_login(self, site):
        i = input('username', 'password')
        a = site.get_account_manager()
        user = a.login(i.username, i.password)
        if user:
            return user._get_data()
        else:
            raise infobase.InfobaseException('Invalid username or password')

    def POST_register(self, site):
        i = input('username', 'password', 'email')
        a = site.get_account_manager()
        username = i.pop('username')
        password = i.pop('password')
        email = i.pop('email')
        a.register(username=username, email=email, password=password, data=i)
        return ""

    def GET_get_user(self, site):
        a = site.get_account_manager()
        user = a.get_user()
        if user:
            d = user._get_data()
            d['email'] = a.get_email(user)
            return d

    def GET_get_reset_code(self, site):
        i = input('email')
        a = site.get_account_manager()
        username, code = a.get_user_code(i.email)
        return dict(username=username, code=code)
        
    def GET_get_user_email(self, site):
        i = input('username')
        a = site.get_account_manager()
        email = a.get_user_email(i.username)
        return dict(email=email)

    def POST_reset_password(self, site):
        i = input('username', 'code', 'password')
        a = site.get_account_manager()
        return a.reset_password(i.username, i.code, i.password)
    
    def POST_update_user(self, site):
        i = input('old_password', new_password=None, email=None)
        a = site.get_account_manager()
        return a.update_user(i.old_password, i.new_password, i.email)
        
def request(path, method, data):
    """Fakes the web request.
    Useful when infobase is not run as a separate process.
    """
    web.ctx.infobase_localmode = True
    web.ctx.infobase_input = data or {}
    web.ctx.infobase_method = method
    for pattern, classname in web.group(urls, 2):
        m = web.re_compile('^' + pattern + '$').match(path)
        if m:
            args = m.groups()
            cls = globals()[classname]
            tocall = getattr(cls(), method)
            return tocall(*args)
    return web.notfound()

def run():
    web.run(urls, globals())
    
if __name__ == "__main__":
    web.config.db_parameters = dict(dbn='postgres', db='infobase2', user='anand', pw='')
    web.config.db_printing = True
    web.run(urls, globals())
