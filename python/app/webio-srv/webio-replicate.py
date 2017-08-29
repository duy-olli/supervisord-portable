#!/opt/python/bin/python

"""A web.py application powered by gevent"""

import eventlet
from eventlet import wsgi
import os, json, mimetypes, string, time, shutil, sys, pwd, grp, optparse, signal, setproctitle, hashlib, urllib, multiprocessing, httplib, gc
from daemon import Daemon
from netaddr import *

eventlet.monkey_patch(socket=True, select=True, time=True)

root_dir = "/data"
root_doc = "" # document root for webio

def httpdate(seconds):
	return time.strftime("%a, %d %b %Y %H:%M:%S GMT",time.localtime(seconds))

def seconds(httpdate):
	try:
		sec = time.mktime(time.strptime(httpdate, "%a, %d %b %Y %H:%M:%S GMT"))
	except ValueError:
		return False
	return sec

class user_input:
        pass

def parseinput(userinput, **default):
        items = userinput.split('&')
        for item in items:
		if item == '': continue
		if item.find('=') == -1: item = item + '='
                key, value = item.strip().split('=')
                default[key.strip()] = value.strip()
        ui = user_input()
        for item in default:
                ui.__dict__[item] = default[item]
        return ui

http_code = { 200: "200 OK", 201: "201 Created", 204: "204 No Data", 205: "205 No Change", 400: "400 Bad Request", 404: "404 Not Found", 409: "409 Conflict", 500: "500 Internal Server Error" }

def error_status(response, code, description):
	response.status = code
	response.desc = description
	response.headers["Content-Type"] = "application/json"
	response.data.append(json.dumps({ "Error": description }))

""" directory => get list ; file => get content """
# todo: generate etag/expire, to cache content
def GET(request, response):
	path = request.path[1:]
	realpath = os.path.join(root_dir, path) 
	if os.path.isdir(realpath):			
		files = []
		directories = []
		for node in os.listdir(realpath):
			pathnode = os.path.join(realpath, node)
			if not os.path.isdir(pathnode) and not os.path.isfile(pathnode):
				continue

			relativepath = os.path.relpath(pathnode, root_dir)
			if os.path.islink(pathnode):
				# symbolic link
				pathnode = os.path.realpath(pathnode)
				if pathnode.startswith(root_dir): # allowing real path inside root directory 
					relativepath = os.path.relpath(pathnode, root_dir) 
				
			if os.path.isfile(pathnode):
				files.append({ "name": node, "link": request.domain + root_doc + '/' + relativepath, "size": os.path.getsize(pathnode)})
			else:
				directories.append({ "name": node, "link": request.domain + root_doc + '/' + relativepath })
			
		directories.sort(key=lambda x:x['name'])
		files.sort(key=lambda x:x['name'])
		response.headers["Content-Type"] = "application/json"
		response.data.append(json.dumps({ "directory": directories, "file": files }))

	elif os.path.isfile(realpath):
		mime = mimetypes.guess_type(realpath)
		if mime[0] is None:
			response.headers["Content-Type"] = "application/octet-stream"
		else:
			response.headers["Content-Type"] = mime[0]

		response.headers["Content-Length"] = os.path.getsize(realpath)
		response.data.append(open(realpath, "rb").read())

	else:
		error_status(response, 404, "Directory/file doesn't exists.")
	
""" directory => create. file => create/update (always ends with /) """
def PUT(request, response):
	path = request.path[1:]
	isdir = False
	if path.endswith('/'):
		realpath = os.path.join(root_dir, path[:-1])
		isdir = True
	else:
		realpath = os.path.join(root_dir, path)
				
	dirname = os.path.dirname(realpath)
	basename = os.path.basename(realpath)
	if not os.path.exists(dirname):
		if not request.qstrings.has_key('force_create_dir') or request.qstrings['force_create_dir'] != '1':
			error_status(response, 404, "Directory/file " + dirname + " not exists.")
			return
		else:
			try:
				os.makedirs(dirname)
			except Exception, err:
				error_status(response, 500, "Cannot create " + dirname + ".")
				return
		
	if isdir:
		# create directory
		if os.path.exists(realpath):
			error_status(response, 409, "Directory " + basename + " already exists.")
			return
			
		if os.path.isdir(dirname):
			try:
				os.mkdir(realpath)
			except Exception, err:
                        	error_status(response, 500, "Cannot create " + realpath + ".")
				return
			response.status = 201
			return
		else:
			error_status(response, 409, basename + " is not a directory.")
			return

	else: 
		# create/overwrite file
		if os.path.isdir(realpath):
			error_status(response, 409, basename + " is a directory.")
			return

		#if os.path.exists(realpath) and web.input(overwrite='').overwrite != '1':
		#	return self.error_status(409, "File " + basename + " already exists. Use overwrite option.")
		mtime = 0
		if request.headers.has_key("wio-modification-time"):
			mtime = seconds(request.headers["wio-modification-time"])
			if request.headers.has_key("wio-access-time"):
                               	atime = seconds(request.headers["wio-access-time"])
			else: atime = mtime

		fd = None
		try:
			if os.path.exists(realpath):
				if not len(request.data):
					response.status = 204
					response.desc = "No Data"
					return
				fd = open(realpath,'rb')
				olddata = fd.read()
				fd.close()
				old_digest = hashlib.md5(olddata).hexdigest()
				new_digest = hashlib.md5(request.data).hexdigest()
				if old_digest == new_digest:
					response.status = 205
					response.desc = "No Change"
					return
		except Exception, err:
			if fd and not fd.closed: fd.close()
			pass

		try:
			fd = open(realpath, "wb")
			fd.write(request.data)
			fd.close()
			if mtime: os.utime(realpath, (atime, mtime))
		except Exception, err:
			if fd and not fd.closed: fd.close()
			error_status(response, 500, "Error creating.")
			return
		response.status = 201
		return

""" get metadata of directory/file """
def HEAD(request, response):
	path = request.path[1:]
	realpath = os.path.join(root_dir, path)
	if not os.path.exists(realpath):
		error_status(response, 404, "Directory/file doesn't exists.")
		return
		
	try:
		stat = os.stat(realpath)
	except Exception, err:
		error_status(response, 500, "Cannot stat file.")
		return

	if os.path.isfile(realpath):
		item = { "wio-size": stat.st_size, 
		"wio-modification-time": httpdate(stat.st_mtime),
		"wio-access-time": httpdate(stat.st_atime) }
	else:
		item = { "wio-modification-time": httpdate(stat.st_mtime),
		"wio-access-time": httpdate(stat.st_atime) }
		
	for k in item:
		response.headers[k] = item[k]
	return 

""" update metadata of directory/file """
def POST(request, response):
	path = request.path[1:]
	realpath = os.path.join(root_dir, path)
		
	userinput = parseinput(urllib.unquote(request.data), operation='', destination='', modification_time='', access_time='')
	if userinput.operation == 'rename':
		if not os.path.exists(realpath):
			error_status(response, 404, "Directory/file doesn't exists.")
			return
			
		if not userinput.destination.startswith(request.domain + root_doc):
			error_status(response, 400, "Unknown destination.")
			return

		srcrealpath = realpath
		dstpath = os.path.relpath(userinput.destination, request.domain + root_doc)
		dstrealpath = os.path.join(root_dir, dstpath)

		# only for webio insync 
		if os.path.isdir(os.path.dirname(dstrealpath)):
			# rename with specifying new filename
			try:
				shutil.move(srcrealpath, dstrealpath)
			except Exception, err:
				error_status(response, 500, "Cannot rename.")
				return
		else:
			error_status(response, 400, "Cannot rename the file/directory. %s %s" %(dstpath, dstrealpath) )
			return

                #modtime = seconds(userinput.modification_time)
                #accesstime = seconds(userinput.access_time) or modtime
                #if modtime:
                #        os.utime(realpath, (accesstime, modtime))

		return 
	
	elif userinput.operation == 'change_attribute':
		if not os.path.exists(realpath):
			error_status(response, 404, "Directory/file doesn't exists.")
			return
			
		modtime = seconds(userinput.modification_time)
		accesstime = seconds(userinput.access_time)
		if accesstime or modtime:
			try:
				stat = os.stat(realpath)
				if not accesstime: accesstime = stat.st_atime
				if not modtime: modtime = stat.st_mtime
				os.utime(realpath, (accesstime, modtime))
			except Exception, err:
				error_status(response, 500, "Error changing attribute.")
				return
			return				
		else:			
			error_status(response, 400, "Attribute value not found.")
			return

	elif userinput.operation == 'symlink':
		#if not userinput.destination.startswith(request.domain + root_doc):
		#	error_status(response, 400, "Unknown destination.")
		#	return

		#dstpath = os.path.relpath(userinput.destination, request.domain + root_doc)
		#dstrealpath = os.path.join(root_dir, dstpath)
		dstrealpath = userinput.destination
		try:
			os.symlink(dstrealpath, realpath)
		except Exception, err:
			error_status(response, 500, "Cannot symlink.")
			return
                # TODO: dont know how to utime symbolic link
		#modtime = seconds(userinput.modification_time)
                #accesstime = seconds(userinput.access_time) or modtime
		#sys.stderr.write(userinput.modification_time + ' ' + userinput.access_time)
                #if modtime:
                #        os.utime(realpath, (accesstime, modtime))

		return
	else:
		error_status(response, 400, "Unknown operation.")
		return
	
""" delete directory/file/(metadata?) """
def DELETE(request, response):
	path = request.path[1:]
	realpath = os.path.join(root_dir, path)
	if not os.path.lexists(realpath):
		error_status(response, 404, "Directory/file doesn't exists.")
		return

	if os.path.isfile(realpath) or os.path.islink(realpath):
		try:
			os.unlink(realpath)
		except Exception, err:
			error_status(response, 500, "Cannot unlink file")
			return
	else:
		if len(os.listdir(realpath)) == 0:
			try:
				os.rmdir(realpath)
			except Exception, err:
				error_status(response, 500, "Cannot remove directory.")
				return
		else:
			error_status(response, 400, "Directory is not empty.")
			return
	return

class obj: pass

fd_log = None
fd_logdate = None
def log_request(remote_addr, strdate, method, url, req_length, ret_desc, response_time):
	global daemon, fd_log, fd_logdate
	now = time.strftime("%Y%m%d", time.localtime())
	if not fd_log or now != fd_logdate:
		fd_logdate = now
		if fd_log: fd_log.close()
		gc.collect()
		fd_log = open(daemon.options.stdout + "." + fd_logdate, "a+")

	fd_log.write("%s | %s | %s | %s | %s | %s | %.6f\n" % (remote_addr, strdate, method, url, req_length, ret_desc, response_time))
	fd_log.flush()

# fix destination in request.data, adjust with new replication domain host	
def fix_destination(hostname, request):
	# fix data request for rename and symlink
	userinput = parseinput(urllib.unquote(request.data), operation='', destination='', modification_time='', access_time='')
	#if userinput.operation in ['rename', 'symlink']:
	if userinput.operation in ['rename']:
		dest = httplib.urlsplit(userinput.destination)
		userinput.destination = "http://%s%s" % (hostname, dest.path)
		request.data = ''
		for item in userinput.__dict__:
			if userinput.__dict__[item] == '': continue
			request.data += "%s=%s&" % (item, userinput.__dict__[item])
		request.data = urllib.quote(request.data)

def wsgi_func(env, start_response):
	global hosts, reject_urls

	start_time = time.time()
	request = obj()
	response = obj()
	request.path = urllib.unquote(env.get('PATH_INFO'))
	request.headers = {}
	for key in env:
		if key.startswith('HTTP_') and key != 'HTTP_HOST':
			request.headers[key[5:].lower().replace('_','-')] = env[key]
	request.domain = "http://" + env.get('HTTP_HOST', '[unknown]')
	request.qstrings = {}
        items = urllib.unquote(env.get('QUERY_STRING', '')).split('&')
        for item in items:
		if item == '': continue
		if item.find('=') == -1: item = item + '='
                key, value = item.strip().split('=')
                request.qstrings[key.strip()] = value.strip()
	request.contentlen = long(env.get('CONTENT_LENGTH', '0'))
	request.data = env['wsgi.input'].read(request.contentlen)
	method = env.get('REQUEST_METHOD')
	request.method = method
	response.status = 200
	response.headers = {}
	response.data = []

        if not IPAddress(env.get('REMOTE_ADDR')) in IPNetwork('192.168.0.0/16') and env.get('REMOTE_ADDR') != '127.0.0.1':
                start_response('404 Not Found', [('Content-Type', 'text/plain')])
                log_request(env.get('REMOTE_ADDR'), \
                        time.strftime("%d/%m/%Y %H:%M:%S",time.localtime()), \
                        method, request.path, request.contentlen, "IP forbidden", time.time() - start_time)
                return ['Method is not Implemented !!\r\n']

	

	# url reject lists
	rejected = False
	for url in reject_urls:
		if request.path.startswith(url): rejected = True

	# url accept lists
	for url in accept_urls:
		if request.path.startswith(url): rejected = False

	# khusus glustervm neh (list production saja yang direject)
	if rejected and env.get('REMOTE_ADDR') != "127.0.0.1": 
		start_response('205 No Change', [('Content-Type', 'text/plain')])
		return ['URL is rejected from list !!\r\n']
	elif globals().has_key(method):
		# khusus glustervm neh (modifikasi lokal direplikasi kesemua host kecuali dirinya sendiri)
		if (not daemon.options.readonly or request.method in ['GET', 'HEAD']) and env.get('REMOTE_ADDR') != "127.0.0.1": 
			globals()[method](request, response)
		else:
			response.status = 200
			response.headers['Content-Type'] = 'text/plain'
		
		start_response('%s' % (http_code[response.status]),response.headers.items())

		# check force=1 in qstring; force to write event there's no data or data still same
		force_write = False
		if request.qstrings.has_key('force') and request.qstrings['force'] == '1' and response.status in [205, 409]:
			force_write = True	

		# replicate only POST, PUT, DELETE and return code 200 n 201
 		if request.method in ['POST', 'PUT', 'DELETE'] and (response.status in [200, 201] or force_write) :
			for host in hosts: hosts[host]['queue'].put(request)

		# log request
		if response.__dict__.has_key('desc'):
			desc = response.desc
		else: desc = "OK"
		log_request(env.get('REMOTE_ADDR'), \
			time.strftime("%d/%m/%Y %H:%M:%S",time.localtime()), \
			method, request.path, request.contentlen, desc, time.time() - start_time)

		return response.data
	else:
		start_response('404 Not Found', [('Content-Type', 'text/plain')])
		return ['Method is not Implemented !!\r\n']

is_exit = multiprocessing.Value('b', 0)
def clean_exit(signum, frame):
        global hosts
	is_exit.value = 1
	for host in hosts:
		hosts[host]['proc'].join()
	sys.exit()

def do_gc(signum, frame):
	gc.collect()

max_retry = 2
def http_request(host, req):
	http = httplib.HTTPConnection(host, timeout=60)
	success = False
	retry = 0

	if req.method == 'POST': fix_destination(host, req)

	while not success and retry <= max_retry:
		try:
			http.request(req.method, urllib.quote(req.path), req.data, req.headers)
			resp = http.getresponse()
			
			if resp.status == 404 and req.method == 'PUT':
				http.request(req.method, urllib.quote(req.path) + "?force_create_dir=1", req.data, req.headers)
				resp = http.getresponse()
				
			if resp.status != 500:
				success = True
			else: retry += 1
		except Exception, err:
			success = False
			retry += 1
	http.close()

def replicator(host, queue):
	setproctitle.setproctitle(sys.argv[0] + ' %s' % host)
	pool = eventlet.GreenPool()
	while not is_exit.value:
		if not queue.empty():
			request = queue.get()
			if request.method == 'DELETE' or (request.method == 'POST' and urllib.unquote(request.data).find('operation=rename') >= 0) or request.path.endswith('/'):
				# make it sequential for rename or operation on directory
				http_request(host, request)
			else:
				pool.spawn_n(http_request, host, request)	
		else: 
			#pool.waitall()
			#time.sleep(.2) 
			eventlet.sleep(.2) 

daemon = Daemon(
	user="detik",
	group="detik",
        stdin="/dev/null",
        stdout="/var/log/webio/webio-replicate.log",
        stderr="/var/log/webio/webio-replicate.err",
        pidfile="/var/log/webio/webio-replicate.pid",
	port="20202",
	rootdir=root_dir,
	readonly=False,
)

hosts = {}
reject_urls = {}
accept_urls = {}
if __name__ == "__main__":
	if daemon.service():
		signal.signal(signal.SIGABRT, clean_exit)
		signal.signal(signal.SIGTERM, clean_exit)
		signal.signal(signal.SIGQUIT, clean_exit)
		signal.signal(signal.SIGINT, clean_exit)
		signal.signal(signal.SIGUSR1, do_gc)
		setproctitle.setproctitle(sys.argv[0])
		os.umask(022)
		os.chdir("/opt/python/app/webio-srv")

		host_list = map(lambda x: x.strip(), open("replicate-dev.conf", "r").readlines())
		for hostname in host_list:
			queue = multiprocessing.Queue()
			hosts[hostname] = { 'queue': queue ,'proc': multiprocessing.Process(target=replicator, args=(hostname, queue)) }
			hosts[hostname]['proc'].start()

		if os.path.exists("reject.conf"):
			reject_urls = map(lambda x: x.strip(), open("reject.conf", "r").readlines())
		if os.path.exists("accept.conf"):
			accept_urls = map(lambda x: x.strip(), open("accept.conf", "r").readlines())

		port = 20202 if not daemon.options.port.isdigit() else int(daemon.options.port)
		root_dir = root_dir if root_dir == daemon.options.rootdir else daemon.options.rootdir
		sys.stdout.write("Using port: %s and root directory: %s\n" % (port,root_dir))
		sys.stdout.flush() 
		wsgi.server(eventlet.listen(('', port)), wsgi_func, open("/dev/null","w"), keepalive=False)
