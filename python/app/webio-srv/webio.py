#!/opt/python/bin/python

"""A web.py application powered by gevent"""

import eventlet
from eventlet import wsgi
import os, json, mimetypes, string, time, shutil, sys, pwd, grp, optparse, signal, setproctitle, hashlib, urllib
from daemon import Daemon

root_dir = "/storage"
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

http_code = { 200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 404: "404 Not Found", 409: "409 Conflict", 500: "500 Internal Server Error" }

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
					response.status = 200
					response.desc = "No Data"
					return
				fd = open(realpath,'rb')
				olddata = fd.read()
				fd.close()
				old_digest = hashlib.md5(olddata).hexdigest()
				new_digest = hashlib.md5(request.data).hexdigest()
				if old_digest == new_digest:
					response.status = 200
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
		if not userinput.destination.startswith(request.domain + root_doc):
			error_status(response, 400, "Unknown destination.")
			return

		dstpath = os.path.relpath(userinput.destination, request.domain + root_doc)
		dstrealpath = os.path.join(root_dir, dstpath)
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
		fd_log = open(daemon.options.stdout + "." + fd_logdate, "a+")

	fd_log.write("%s | %s | %s | %s | %s | %s | %.6f\n" % (remote_addr, strdate, method, url, req_length, ret_desc, response_time))
	fd_log.flush()
	

def wsgi_func(env, start_response):
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
	response.status = 200
	response.headers = {}
	response.data = []
	if globals().has_key(method):
		globals()[method](request, response)
		start_response('%s' % (http_code[response.status]),response.headers.items())
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

daemon = Daemon(
	user="detik",
	group="detik",
        stdin="/dev/null",
        stdout="/var/log/webio/webio.log",
        stderr="/var/log/webio/webio.err",
        pidfile="/var/log/webio/webio.pid",
	port="20202",
	rootdir=root_dir,
)

if __name__ == "__main__":
	if daemon.service():
		setproctitle.setproctitle(sys.argv[0])
		os.umask(022)
		port = 20202 if not daemon.options.port.isdigit() else int(daemon.options.port)
		root_dir = root_dir if root_dir == daemon.options.rootdir else daemon.options.rootdir
		sys.stdout.write("Using port: %s and root directory: %s\n" % (port,root_dir))
		sys.stdout.flush() 
		wsgi.server(eventlet.listen(('', port)), wsgi_func, open("/dev/null","w"), keepalive=False)
