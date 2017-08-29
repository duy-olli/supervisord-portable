#!/opt/python/bin/python
import os, httplib, time
from trigger import Trigger

max_retry = 2
#TODO: working with problem directory doesn't exists and other
def httpdate(seconds):
        return time.strftime("%a, %d %b %Y %H:%M:%S GMT",time.localtime(seconds))

class webionodel(Trigger):
	def __init__(self, params):
		self.src = params['src-root-dir']
		if not type(params['dst-root-dirs']) is list:
			self.dsts = [params['dst-root-dirs']]
		else:
			self.dsts = params['dst-root-dirs']

	def on_modified(self, pathname, data):
		relpath = os.path.relpath(pathname, self.src)
		for dst in self.dsts:
			retry = 0
			url = httplib.urlsplit(os.path.join(dst, relpath))
			http = httplib.HTTPConnection(url.netloc, timeout=60)
			dst_path = url.path
			
			if os.path.islink(pathname):
				success = False
				rel_origpath = os.path.relpath(os.path.realpath(pathname), self.src)
				dst_origpath = os.path.join(dst, rel_origpath)
				while not success and retry <= max_retry:
					try:
						http.request("POST", dst_path, 'operation=symlink&destination=%s' % (dst_origpath))
						resp = http.getresponse()
						if resp.status != 500:
							success = True
						else: retry += 1
					except Exception, e:
						success = False
						retry += 1
			
			elif os.path.isdir(pathname):
				success = False
				if not dst_path.endswith('/'):
					dst_path = dst_path + '/'
				while not success and retry <= max_retry:
					try:
						http.request("PUT", dst_path)
						resp = http.getresponse()
						if resp.status == 404:
							# use force directory creation
							http.request("PUT", dst_path + "?force_create_dir=1")
							resp = http.getresponse()
						
						if resp.status != 500:
							success = True
						else: retry += 1
					except Exception, e:
						success = False
						retry += 1
			else:
				success =  False
				stat = os.stat(pathname)
				headers = { 'wio-modification_time' : httpdate(stat.st_mtime), 'wio-access_time' : httpdate(stat.st_atime) }
				while not success and retry <= max_retry:
					try:
						http.request("PUT", dst_path, data, headers)
						resp = http.getresponse()
						if resp.status == 404:
							# use force directory creation
							http.request("PUT", dst_path + "?force_create_dir=1", data, headers)
							resp = http.getresponse()
						if resp.status != 500:
							success = True
						else: retry += 1
					except Exception, e:
						success = False
						retry += 1
			http.close()

	def on_deleted(self, pathname):
		pass

	def on_renamed(self, pathname, new_pathname):
		relpath = os.path.relpath(pathname, self.src)
		newrelpath = os.path.relpath(new_pathname, self.src)
		for dst in self.dsts:
			retry = 0
			url = httplib.urlsplit(os.path.join(dst, relpath))
			http = httplib.HTTPConnection(url.netloc, timeout=60)
			dst_path = url.path
			new_dst_path = os.path.join(dst, newrelpath)
			success = False
			while not success and retry <= max_retry:
				try:
					http.request("POST", dst_path, 'operation=rename&destination=%s' % (new_dst_path))
					resp = http.getresponse()
					if resp.status != 500:
						success = True
					else: retry+= 1
				except Exception, e:
					success = False
					retry += 1
			http.close()
	def on_terminated(self):
		pass
