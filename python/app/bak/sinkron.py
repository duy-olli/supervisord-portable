#!/opt/python/bin/python

import pyinotify, asyncore, multiprocessing, time, ConfigParser, sys, os, string, hashlib, httplib

sinkron_conf = {}

watch_mask = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY | pyinotify.IN_MOVED_TO | pyinotify.IN_MOVED_FROM

def httpdate(seconds):
        return time.strftime("%a, %d %b %Y %H:%M:%S GMT",time.localtime(seconds))

# ex: num(10).minus5 ; num(10).plus5
class num(object):
        def __init__(self, val, digit=0):
                self.value = val
		self.digit = digit
        def __getattr__(self, name):
                if name.startswith('plus') and name[4:].isdigit():
                        return self.digit and string.rjust(str(self.value + int(name[4:])), self.digit, '0') or str(self.value + int(name[4:]))
                elif name.startswith('minus') and name[5:].isdigit():
                        return self.digit and string.rjust(str(self.value - int(name[5:])), self.digit, '0') or str(self.value - int(name[5:]))
                else:
                        return self.digit and string.rjust(str(self.value), self.digit, '0') or str(self.value)
        def __str__(self):
                return self.digit and string.rjust(str(self.value), self.digit, '0') or str(self.value)

class webio(object):
	def __init__(self, host_address):
		self.conn = httplib.HTTPConnection(host_address)
		self.host = host_address
	def get(self):
		pass
	def put(self, pathname, data, mtime=0, atime=0):
		headers = {}
		if mtime:
			if not atime: atime = mtime
			headers['wio-modification_time'] = httpdate(mtime)
			headers['wio-access_time'] = httpdate(atime)
		self.conn.request("PUT", pathname, data, headers)
		resp = self.conn.getresponse()
	def rename(self, pathname, new_pathname):
		self.conn.request("POST", pathname, 'operation=rename&destination=%s' % (new_pathname))
		self.conn.getresponse()
	def mkdir(self, pathname):
		if not pathname.endswith('/'):
			pathname = pathname + '/'
		self.conn.request("PUT", pathname)
		resp = self.conn.getresponse()
	def rmdir(self):
		self.conn.request("DELETE", pathname)
		self.conn.getresponse()
	def utime(self):
		pass
	def unlink(self, pathname):
		self.conn.request("DELETE", pathname)
		self.conn.getresponse()
	#def symlink(self, pathname, orig_pathname, mtime=0, atime=0):
	#	self.conn.request("POST", pathname, 'operation=symlink&destination=%s&modification_time=%s&access_time=%s' % (orig_pathname, httpdate(mtime), httpdate(atime)))
	def symlink(self, pathname, orig_pathname):
		self.conn.request("POST", pathname, 'operation=symlink&destination=%s' % (orig_pathname))
		self.conn.getresponse()
	def stat(self):
		pass

def arrange_event_list(pathname, attribute, watch_list):
	"""
	prev => curr
	c => c (not replaced); d (remove from watch list); m (not replaced); r (add new pathname to watch list, mark as 'c'; remove old pathname from watch list)
	m => c (not happening); d (replaced); m (not replaced); r (replaced)
	d => c (replaced); d (not happening); m (mark as 'c'); r (not happening)
	r => c (mark old pathname as 'c', new pathname as 'c'); d (not happening); m (not happening); r (not happening)
	"""

	if not watch_list.has_key(pathname):
		watch_list[pathname] = attribute
		return True
	
	if watch_list[pathname]['op'] == 'c':
		if attribute['op'] == 'd': watch_list.pop(pathname)
		elif attribute['op'] == 'r': 
			watch_list[attribute['new_path']] =  { 'op': 'c', 'ts': attribute['ts'] }
			watch_list.pop(pathname)
	elif watch_list[pathname]['op'] == 'm' and attribute['op'] in ['d','r']:
		watch_list[pathname] = attribute

	elif watch_list[pathname]['op'] == 'd' and attribute['op'] in ['c','m']:
		watch_list[pathname] = { 'op': 'c', 'ts': attribute['ts'] }

	elif watch_list[pathname]['op'] == 'r' and attribute['op'] == 'c':
		newpathname = watch_list[pathname]['new_path']
		if not watch_list.has_key(newpathname): watch_list[newpathname] = { 'op': 'c', 'ts': watch_list[pathname]['ts'] }
		watch_list[pathname]['op'] = { 'op': 'c', 'ts': attribute['ts'] }

	else:
		return False

	return True

def process_list(item, section, digest_list, watch_list):
	pathname, attribute = item
	modified = False

	# TODO: now it's only modified or created list
	if attribute['op'] in ['c', 'm']:
		if os.path.islink(pathname):
			modified = True
		elif os.path.isfile(pathname):
			data = open(pathname,'rb').read()
			new_digest = hashlib.md5(data).hexdigest()
			if not digest_list.has_key(pathname):
				digest_list[pathname] = { 'digest': new_digest, 'ts': attribute['ts'] }
				modified = True
			else:
				if digest_list[pathname]['digest'] != new_digest:
					digest_list[pathname] = { 'digest': new_digest, 'ts': attribute['ts'] }
					modified = True
		elif os.path.isdir(pathname):
			modified = True	
		else:
			pass # maybe already deleted or renamed, put it to next list

		if modified:
			relpath = os.path.relpath(pathname, section['src'])
			for dst in section['dsts']:
				urlsplit = httplib.urlsplit(dst)
				wio = webio(urlsplit.netloc)
				dst_path = httplib.urlsplit(os.path.join(dst, relpath)).path
				if os.path.islink(pathname):
					rel_origpath = os.path.relpath(os.path.realpath(pathname), section['src'])
					dst_origpath = os.path.join(dst, rel_origpath)
					#stat = os.lstat(pathname)
					#wio.symlink(dst_path, dst_origpath, stat.st_mtime, stat.st_atime)
					wio.symlink(dst_path, dst_origpath)
				elif os.path.isdir(pathname):
					wio.mkdir(dst_path)
				else:
					stat = os.stat(pathname)
					wio.put(dst_path, data, stat.st_mtime, stat.st_atime)
			watch_list.pop(pathname)
			print "Modified item at ", pathname
	
	elif attribute['op'] == 'd':
		if digest_list.has_key(pathname):
			digest_list.pop(pathname)
		
		relpath = os.path.relpath(pathname, section['src'])
		for dst in section['dsts']:
			urlsplit = httplib.urlsplit(dst)
			wio = webio(urlsplit.netloc)
			dst_path = httplib.urlsplit(os.path.join(dst, relpath)).path
			wio.unlink(dst_path)
		watch_list.pop(pathname)
		print "Deleted item at ", pathname

	elif attribute['op'] == 'r':
		if digest_list.has_key(pathname):
			attr = digest_list.pop(pathname)
			digest_list[attribute['new_path']] = attr

		relpath = os.path.relpath(pathname, section['src'])
		newrelpath = os.path.relpath(attribute['new_path'], section['src'])
		for dst in section['dsts']:
			urlsplit = httplib.urlsplit(dst)
			wio = webio(urlsplit.netloc)
			dst_path = httplib.urlsplit(os.path.join(dst, relpath)).path
			new_dst_path = os.path.join(dst, newrelpath)
			wio.rename(dst_path, new_dst_path)
		watch_list.pop(pathname)	
		print "Renamed item at ", pathname
	
max_queue_default = 15 # default 15 items queued
max_interval_default = 60 # default 60 seconds
max_digest_list = 1000 
max_removed_items = 10 # for digest list

def watch_job(queue, section):
	global digest_list
	workers = []
	manager = multiprocessing.Manager()
	digest_list = manager.dict()
	watch_list = manager.dict()
	max_queue = section['mqi'] or max_queue_default
	max_interval = section['qtt'] or max_interval_default

	first_item_ts = 0
	while True:
		try:
			pathname, attribute = queue.get(timeout=1)
			updated = True
			if not first_item_ts: first_item_ts = attribute['ts']
		except Exception:
			updated = False
		
		worker_triggered = False
		if updated and arrange_event_list(pathname, attribute, watch_list) and len(watch_list) >= max_queue:
			worker_triggered = True
		if first_item_ts and time.time() - first_item_ts >= max_interval:
			worker_triggered = True

		if worker_triggered:
			ordered_event_list = sorted(watch_list.items(), key=lambda x:x[1]['ts'])
			for item in ordered_event_list:
				if os.path.isdir(item[0]) or item[1]['op'] =='r':
					# directory or rename operation must be done sequentially
					process_list(item, section, digest_list, watch_list)
				else:
					worker = multiprocessing.Process(target=process_list, args=(item, section, digest_list, watch_list))
					worker.start()
					workers.append(worker)
			
			# TODO: performance penalty
			while len(workers) > 0:
				for worker in workers:
					if not worker.is_alive():
						worker.join()
						workers.remove(worker)
			first_item_ts = 0
		
			# if max(digest list) => remove n least recently digests (n = max_removed_items) 
			if len(digest_list) >= max_digest_list:
				ts_ordered_digest = sorted(digest_list.items(), key=lambda x:x[1]['ts'])
				for item in ts_ordered_digest[:max_removed_items]:
					digest_list.pop(item[0])
			
class EventHandler(pyinotify.ProcessEvent):
	def __init__(self, watch_queue):
		self.watch_queue = watch_queue

	def process_IN_CREATE(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'c', 'ts': time.time() }])

	def process_IN_MODIFY(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'm', 'ts': time.time() }])

	def process_IN_DELETE(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'd', 'ts': time.time() }])

	def process_IN_MOVED_TO(self, event):
		self.watch_queue.put([event.src_pathname, { 'op': 'r', 'ts': time.time(), 'new_path': event.pathname }])

date = ('{year}', '{month}', '{day}', '{hour}', '{minute}', '{second}')

def small_idx_date(text):
	idx = len(date) - 1
	while text.find(date[idx]) == -1 and idx > -1: idx-=1
	return idx

def substitute_date(text, date):
	return text.format(year=num(date[0]), month=num(date[1],2), day=num(date[2],2), hour=num(date[3],2), minute=num(date[4],2), second=num(date[5],2))

def tuple_date(seconds = time.time()):
	Ynow, Mnow, Dnow, hnow, mnow, snow, x, x, x = time.localtime(seconds)
	return [Ynow, Mnow, Dnow, hnow, mnow, snow, 0,0,0]

def next_seconds(tnow, idx, inc = 1):
	now = list(tnow)
	now[idx] += inc
	return time.mktime(now)

def section_job(section):
	# process to consume items from this producer
	watch_queue = multiprocessing.Queue()
	watchjob = multiprocessing.Process(target=watch_job, args=(watch_queue,section,))
	watchjob.start()

	wm = pyinotify.WatchManager()
	notifier = pyinotify.AsyncNotifier(wm, EventHandler(watch_queue))
	
	exclude = pyinotify.ExcludeFilter(section['exclude'])
	template = {} # [small index date, next triggered seconds, wdd]
	for include_dir in section['include']:
		key = include_dir
		template[key] = [0,0,None]
		template[key][0] = small_idx_date(include_dir)
		if template[key][0] > -1:
			now = tuple_date()
			template[key][1] = next_seconds(now, template[key][0])
			include_dir = substitute_date(include_dir, now)
		print "New watch with include directory " , include_dir
		template[key][2] = wm.add_watch(include_dir, watch_mask, rec=True, auto_add=True, exclude_filter=exclude)

	next_trigger = min(map(lambda x: template[x][1], template))
	while True:
		notifier.process_events()
		while notifier.check_events():
			notifier.read_events()
			notifier.process_events()
		
		# check for updated watch
		if next_trigger and time.time() >= next_trigger:
			# update watch
			for include_dir in section['include']:
				key = include_dir
				if template[key][1] != next_trigger: continue	
				now = tuple_date(next_trigger)
				template[key][1] = next_seconds(now, template[key][0])
				next_trigger = min(map(lambda x: template[x][1], template))
				wm.rm_watch(template[key][2].values(), rec=True)
				include_dir = substitute_date(include_dir, now)
				print "Updated with new include directory " , include_dir
				template[key][2] = wm.add_watch(include_dir, watch_mask, rec=True, auto_add=True, exclude_filter=exclude)	

	watchjob.join()

def read_config():
	cfg = ConfigParser.ConfigParser()
	cfg.read("sinkron.conf")
	tmp_sections = {}
	for section in cfg.sections():
		tmp_sections[section] = {}
		for item in cfg.items(section):
			if item[1] is None: continue
			if item[1].find(',') >= 0: # split for multivalue
				val = map(lambda x:x.strip(), item[1].split(','))
			else:
				val = [item[1]]
			tmp_sections[section][item[0]] = val

		if not tmp_sections[section].has_key('src-root-dir') or not tmp_sections[section].has_key('dst-root-dirs'): 
			tmp_sections.pop(section)
	
	sections = {}
	# sections => section => {src, dsts[], include[], exclude[], qtt, mqi}
	for section in tmp_sections:
		src_dir = tmp_sections[section]['src-root-dir'][0]
		dst_dirs = tmp_sections[section]['dst-root-dirs']
		if tmp_sections[section].has_key('exclude-dirs'):
			tmp_exclude_dirs = map(lambda x: (len(x) > 0 and x[0] == '/') and x[1:] or x, tmp_sections[section]['exclude-dirs'])
		else:
			tmp_exclude_dirs = []

		if tmp_sections[section].has_key('queue-threshold-time'):
			qtt = string.atoi(tmp_sections[section]['queue-threshold-time'][0])
		else: qtt = 0

		if tmp_sections[section].has_key('max-queued-items'):
			mqi = string.atoi(tmp_sections[section]['max-queued-items'][0])
		else: mqi = 0

		if tmp_sections[section].has_key('include-dirs'):
			inc_dirs = map(lambda x: (len(x) > 0 and x[0] == '/') and x[1:] or x, tmp_sections[section]['include-dirs'])
			exc_dirs = []
			for incdir in inc_dirs:
				for excdir in tmp_exclude_dirs:
					if excdir.startswith(incdir):
						exc_dirs.append(os.path.join(src_dir, excdir))
			inc_dirs = map(lambda x: os.path.join(src_dir, x), inc_dirs)
			exc_dirs = map(lambda x: '^' + x + '.*', exc_dirs)
			sections[section] = { 'src': src_dir, 'dsts': dst_dirs, 'include': inc_dirs, 'exclude': exc_dirs, 'qtt': qtt, 'mqi': mqi}
		else:
			exc_dirs = map(lambda x: '^' + os.path.join(src_dir, x) + '.*', tmp_exclude_dirs)
			sections[section] = { 'src': src_dir, 'dsts': dst_dirs, 'include': [src_dir], 'exclude': exc_dirs, 'qtt': qtt, 'mqi': mqi }
			
	return sections

if __name__ == "__main__":
	sinkronconf = read_config()
	
	for section in sinkronconf:
		# each section takes one process
		sectionjob = multiprocessing.Process(target=section_job, args=(sinkronconf[section],))
		sectionjob.start()

	while multiprocessing.active_children():
		time.sleep(1)
