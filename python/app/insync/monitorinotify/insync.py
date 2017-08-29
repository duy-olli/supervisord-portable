#!/opt/python/bin/python
# TODO: exclude in pyinotify is strange. ex: ^/data/static/rating.* works ; ^/data/static/rating/.* not working
import pyinotify, asyncore, multiprocessing, time, ConfigParser, sys, os, string, hashlib, setproctitle, optparse, pwd, grp, signal
from trigger import Trigger

is_exit = multiprocessing.Value('b', 0)
def clean_exit(signum, frame):
	is_exit.value = 1

class Daemon(object):
	def __init__(self, stdin="/dev/null", stdout="/dev/null", stderr="/dev/null", conf="./insync.conf", pidfile=None, user=None, group=None):
		options = dict(
			stdin=stdin,
			stdout=stdout,
			stderr=stderr,
			pidfile=pidfile,
			user=user,
			group=group,
			conf=conf,
		)

		self.options = optparse.Values(options)

	def openstreams(self):
		si = open(self.options.stdin, "r")
		so = open(self.options.stdout, "a+", 0)
		se = open(self.options.stderr, "a+", 0)
		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
	
	def handlesighup(self, signum, frame):
		self.openstreams()

	def switchuser(self, user, group):
		if group is not None:
			if isinstance(group, basestring):
				group = grp.getgrnam(group).gr_gid
			os.setegid(group)
		if user is not None:
			if isinstance(user, basestring):
				user = pwd.getpwnam(user).pw_uid
			os.seteuid(user)
			if "HOME" in os.environ:
				os.environ["HOME"] = pwd.getpwuid(user).pw_dir

	def start(self):
		# Finish up with the current stdout/stderr
		sys.stdout.flush()
		sys.stderr.flush()
	
		# Do first fork
		try:
			pid = os.fork()
			if pid > 0:
				sys.exit(0) # Exit first parent
		except OSError, exc:
			sys.exit("%s: fork #1 failed: (%d) %s\n" % (sys.argv[0], exc.errno, exc.strerror))
	
		# Decouple from parent environment
		os.chdir("/")
		os.umask(0)
		os.setsid()
	
		# Do second fork
		try:
			pid = os.fork()
			if pid > 0:
				sys.exit(0) # Exit second parent
		except OSError, exc:
			sys.exit("%s: fork #2 failed: (%d) %s\n" % (sys.argv[0], exc.errno, exc.strerror))
	
		# Now I am a daemon!
	
		# Switch user
		self.switchuser(self.options.user, self.options.group)

		# Redirect standard file descriptors (will belong to the new user)
		self.openstreams()
	
		# Write pid file (will belong to the new user)
		if self.options.pidfile is not None:
			open(self.options.pidfile, "wb").write(str(os.getpid()))

		# Reopen file descriptions on SIGHUP
		signal.signal(signal.SIGHUP, self.handlesighup)


	def stop(self):
		if self.options.pidfile is None:
			sys.exit("no pidfile specified")
		try:
			pidfile = open(self.options.pidfile, "rb")
		except IOError, exc:
			sys.exit("can't open pidfile %s: %s" % (self.options.pidfile, str(exc)))
		data = pidfile.read()
		try:
			pid = int(data)
		except ValueError:
			sys.exit("mangled pidfile %s: %r" % (self.options.pidfile, data))
		os.kill(pid, signal.SIGTERM)

	def optionparser(self):
		p = optparse.OptionParser(usage="usage: %prog [options] (start|stop|restart|run)")
		p.add_option("-p", "--pidfile", dest="pidfile", help="PID filename (default %default)", default=self.options.pidfile)
		p.add_option("--stdin", dest="stdin", help="stdin filename (default %default)", default=self.options.stdin)
		p.add_option("-o", "--stdout", dest="stdout", help="stdout filename (default %default)", default=self.options.stdout)
		p.add_option("-e", "--stderr", dest="stderr", help="stderr filename (default %default)", default=self.options.stderr)
		p.add_option("-u", "--user", dest="user", help="user name or id (default %default)", default=self.options.user)
		p.add_option("-g", "--group", dest="group", help="group name or id (default %default)", default=self.options.group)
		p.add_option("-c", "--conf", dest="conf", help="configuration file (default %default)", default=self.options.conf)
		return p

	def service(self, args=None):
		p = self.optionparser()
		if args is None:
			args = sys.argv
		(self.options, self.args) = p.parse_args(args)
		if len(self.args) != 2:
			p.error("incorrect number of arguments")
			sys.exit(1)
		if self.args[1] == "run":
			return True
		elif self.args[1] == "restart":
			self.stop()
			self.start()
			return True
		elif self.args[1] == "start":
			self.start()
			return True
		elif self.args[1] == "stop":
			self.stop()
			return False
		else:
			p.error("incorrect argument %s" % self.args[1])
			sys.exit(1)

#------------------------------------------------------------------------------------------------

watch_mask = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY | pyinotify.IN_MOVED_TO | pyinotify.IN_MOVED_FROM | pyinotify.IN_Q_OVERFLOW

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

def arrange_event_list(pathname, attribute, watch_list):
	"""
	prev => curr
	c => c (not replaced); d (remove from watch list); m (not replaced); r (add new pathname to watch list, mark as 'c'; remove old pathname from watch list)
	m => c (not happening); d (replaced); m (not replaced); r (replaced)
	d => c (replaced); d (not happening); m (mark as 'c'); r (not happening)
	r => c (mark pathname with additional *); d (not happening); m (not happening); r (not happening)
	**r => c (mark old pathname as 'c', new pathname as 'c'); d (not happening); m (not happening); r (not happening)
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
		watch_list['*' + pathname] = watch_list[pathname]
		watch_list[pathname] = { 'op': 'c', 'ts': attribute['ts'] }
	else:
		return False

	return True

def execute_module(trigger_modules, operation, pathname, new_pathname=None, data=None):
	global mod_instances
	for trigger in trigger_modules:
		if operation == 'm':
			mod_instances[trigger].on_modified(pathname, data)
		elif operation == 'd':
			mod_instances[trigger].on_deleted(pathname)
		else:
			mod_instances[trigger].on_renamed(pathname, new_pathname)

def do_operation(item, section, digest_list, watch_list, lock_watch_list, new_process):
	pathname, attribute = item
	true_pathname = pathname.lstrip('*')
	modified = False
	data = None

	if attribute['op'] in ['c', 'm']:
		if os.path.islink(true_pathname):
			modified = True
		elif os.path.isfile(true_pathname):
			try:
				data = open(true_pathname,'rb').read()
			except Exception, err:
				return
			new_digest = hashlib.md5(data).hexdigest()
			if not digest_list.has_key(pathname):
				digest_list[pathname] = { 'digest': new_digest, 'ts': attribute['ts'] }
				modified = True
			else:
				if digest_list[pathname]['digest'] != new_digest:
					digest_list[pathname] = { 'digest': new_digest, 'ts': attribute['ts'] }
					modified = True
		elif os.path.isdir(true_pathname):
			modified = True	
		else:
			pass # maybe already deleted or renamed, put it to next list

		if modified:
			if attribute['ts'] == watch_list[pathname]['ts']:
				lock_watch_list.acquire()
				watch_list.pop(pathname)
				lock_watch_list.release()

			if new_process:
				multiprocessing.Process(target=execute_module, args=(section['triggermod'], 'm', true_pathname, None, data)).start()
			else:
				execute_module(section['triggermod'], 'm', true_pathname, data=data)
	
	elif attribute['op'] == 'd':
		# not necessarily needed
		if digest_list.has_key(pathname):
			digest_list.pop(pathname)
		
		if attribute['ts'] == watch_list[pathname]['ts']:
			lock_watch_list.acquire()
			watch_list.pop(pathname)
			lock_watch_list.release()

		if new_process:
			multiprocessing.Process(target=execute_module, args=(section['triggermod'], 'd', true_pathname)).start()
		else:
			execute_module(section['triggermod'], 'd', true_pathname)

	elif attribute['op'] == 'r':
		if digest_list.has_key(pathname):
			attr = digest_list.pop(pathname)
			digest_list[attribute['new_path']] = attr

		if attribute['ts'] == watch_list[pathname]['ts']:
			lock_watch_list.acquire()
			watch_list.pop(pathname)
			lock_watch_list.release()	

		if new_process:
			multiprocessing.Process(target=execute_module, args=(section['triggermod'], 'r', true_pathname, attribute['new_path'])).start()
		else:
			execute_module(section['triggermod'], 'r', true_pathname, attribute['new_path'])

max_queue_default = 15 # default 15 items queued
max_interval_default = 60 # default 60 seconds
max_digest_list = 10000 
max_removed_items = 10 # for digest list
max_workers_default = 10

def consume_queue(queue, watch_list, lock_watch_list, max_queue, max_interval):
	global first_item_ts
		
	try:
		pathname, attribute = queue.get(timeout=1)
		updated = True
		if not first_item_ts: first_item_ts = attribute['ts']
	except Exception:
		updated = False
	
	worker_triggered = False
	if updated:
		lock_watch_list.acquire() 
		arrange_event_list(pathname, attribute, watch_list) 
		lock_watch_list.release()

	if len(watch_list) >= max_queue:
		worker_triggered = True
	if first_item_ts and time.time() - first_item_ts >= max_interval:
		worker_triggered = True

	return worker_triggered

def watcher(queue, section):
	global digest_list, first_item_ts
	manager = multiprocessing.Manager()
	digest_list = manager.dict()
	watch_list = manager.dict()
	max_queue = section['mqi'] or max_queue_default
	max_interval = section['qtt'] or max_interval_default
	max_workers = section['mw'] or max_workers_default
	setproctitle.setproctitle(sys.argv[0] + ':watcher')
	first_item_ts = 0
	lock_watch_list = multiprocessing.Lock()
	while not is_exit.value:
		worker_triggered = consume_queue(queue, watch_list, lock_watch_list, max_queue, max_interval)
		
		if worker_triggered:
			first_item_ts = 0
			ordered_event_list = sorted(watch_list.items(), key=lambda x:x[1]['ts'])
			for item in ordered_event_list:
				pathname, attribute = item
				if os.path.isdir(pathname.lstrip('*')) or attribute['op'] =='r':
					# directory or rename operation must be done sequentially
					do_operation((pathname, attribute), section, digest_list, watch_list, lock_watch_list, False)
				else:
					do_operation((pathname, attribute), section, digest_list, watch_list, lock_watch_list, True)
					while len(multiprocessing.active_children()) > max_workers:
						consume_queue(queue, watch_list, lock_watch_list, max_queue, max_interval)

			# TODO: performance penalty
			while len(multiprocessing.active_children()) > 1: 
				consume_queue(queue, watch_list, lock_watch_list, max_queue, max_interval)
		
			# if max(digest list) => remove n least recently digests (n = max_removed_items) 
			if len(digest_list) >= max_digest_list:
				ts_ordered_digest = sorted(digest_list.items(), key=lambda x:x[1]['ts'])
				for item in ts_ordered_digest[:max_removed_items]:
					digest_list.pop(item[0])
			
class EventHandler(pyinotify.ProcessEvent):
	def __init__(self, deleted_wd, watch_queue):
		self.watch_queue = watch_queue
		self.deleted_wd = deleted_wd

	def process_IN_CREATE(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'c', 'ts': time.time() }])

	def process_IN_MODIFY(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'm', 'ts': time.time() }])

	def process_IN_DELETE(self, event):
		self.watch_queue.put([event.pathname, { 'op': 'd', 'ts': time.time() }])
		# reducing memory consumption for delete/create activity
		if os.path.isdir(event.pathname):
			self.deleted_wd.append(event.wd)

	def process_IN_MOVED_TO(self, event):
		if event.__dict__.has_key('src_pathname'):
			# renamed in one watched directory
			self.watch_queue.put([event.src_pathname, { 'op': 'r', 'ts': time.time(), 'new_path': event.pathname }])
		else:
			pass # TODO
			# renamed into watched directory (same as creating new file/dir)
			#self.watch_queue.put([event.pathname, { 'op': 'c', 'ts': time.time() }])

	def process_IN_MOVED_FROM(self, event):
		pass # TODO
		# renamed to outside watched directory
		#self.watch_queue.put([event.pathname, { 'op': 'r2', 'ts': time.time() }])
	def process_IN_Q_OVERFLOW(self, event):
		sys.stdout.write("%s : Queue overflow !! (update your sysctl)\n" % time.ctime())
		sys.stdout.flush()		

date_tpl = ('{year', '{month', '{day', '{hour', '{minute', '{second')

def small_idx_date(text):
	idx = len(date_tpl) - 1
	while text.find(date_tpl[idx]) == -1 and idx > -1: idx-=1
	return idx

def substitute_date(text, date):
	return text.format(year=num(date[0]), month=num(date[1],2), day=num(date[2],2), hour=num(date[3],2), minute=num(date[4],2), second=num(date[5],2))

def tuple_date(seconds = time.time()):
	Ynow, Mnow, Dnow, hnow, mnow, snow, x, x, x = time.localtime(seconds)
	return [Ynow, Mnow, Dnow, hnow, mnow, snow, 0,0,0]

def next_seconds(tnow, idx, inc = 1):
	now = list(tnow)
	for zeroidx in range(idx+1,6): now[zeroidx] = 0
	# day cannot start with zero
	if idx == 1: now[idx+1] = 1
	now[idx] += inc
	return time.mktime(now)

def watch_section_job(section_name, section):
	setproctitle.setproctitle(sys.argv[0] + ':' + section_name)
	# process to consume items from this producer
	watch_queue = multiprocessing.Queue()
	watchjob = multiprocessing.Process(target=watcher, args=(watch_queue,section,))
	watchjob.start()

	deleted_wd = []
	max_deleted_queue = 10

	wm = pyinotify.WatchManager()
	notifier = pyinotify.AsyncNotifier(wm, EventHandler(deleted_wd, watch_queue), timeout=10)
	
	exclude = pyinotify.ExcludeFilter(section['exclude'])
	template = {} # [small index date, next triggered seconds, wdd]
	for include_dir in section['include']:
		key = include_dir
		template[key] = [0,0,None]
		template[key][0] = small_idx_date(include_dir)
		if template[key][0] > -1:
			now = tuple_date()
			template[key][1] = next_seconds(now, template[key][0])
			sys.stdout.flush()
			include_dir = substitute_date(include_dir, now)
		if not os.path.exists(include_dir): continue
		template[key][2] = wm.add_watch(include_dir, watch_mask, rec=True, auto_add=True, exclude_filter=exclude)
	
	next_trigger = min(map(lambda x: template[x][1], template))
	while not is_exit.value:
		notifier.process_events()
		while notifier.check_events():
			notifier.read_events()
			notifier.process_events()
			if len(deleted_wd) > max_deleted_queue:
				while len(deleted_wd):
					sys.stdout.write("%s : Deleting unnecessary object : " % time.ctime())
					wd = deleted_wd.pop()
					wm.del_watch(wd)
					sys.stdout.write("Done\n")
					sys.stdout.flush()
		
		# check for updated watch
		if next_trigger and time.time() >= next_trigger:
			# update watch
			sys.stdout.write("%s\n" % next_trigger)
			sys.stdout.write("%s : Updating watched directory\n" % time.ctime())
			sys.stdout.flush()
			for include_dir in section['include']:
				key = include_dir
				if template[key][1] != next_trigger: continue	
				now = tuple_date(next_trigger)
				include_dir = substitute_date(include_dir, now)
				if not os.path.exists(include_dir): continue # wait until directory exists
				template[key][1] = next_seconds(now, template[key][0])
				next_trigger = min(map(lambda x: template[x][1], template))
				wm.rm_watch(template[key][2].values(), rec=True)
				template[key][2] = wm.add_watch(include_dir, watch_mask, rec=True, auto_add=True, exclude_filter=exclude)	

	notifier.stop()
	watchjob.join()

def read_config(config_path):
	if not os.path.exists(config_path):
		print "Configuration file not exists !!"
		sys.exit()

	cfg = ConfigParser.ConfigParser()
	cfg.read(config_path)
	tmp_sections = {}
	for section in cfg.sections():
		tmp_sections[section] = {}
		for item in cfg.items(section):
			if item[1] is None: continue
			if item[1].find(',') >= 0: # split for multivalue
				val = map(lambda x:x.strip(), item[1].split(','))
			else:
				val = item[1]
			tmp_sections[section][item[0]] = val

		if not tmp_sections[section].has_key('watch-dirs') and not tmp_sections[section].has_key('module'): 
			tmp_sections.pop(section)
	
	watch_sections = {}
	module_sections = {}
	# watch_sections => section => {watchdirs[], exclude[], qtt, mqi, modules[]}
	# module_sections => section => {params}
	for section in tmp_sections:
		if tmp_sections[section].has_key('module'):
			if os.path.exists(tmp_sections[section]['module'] + '.py'): 
				module_sections[section] = tmp_sections[section]
			continue

		qtt = tmp_sections[section].has_key('queue-threshold-time') and int(tmp_sections[section]['queue-threshold-time']) or 0

		mqi = tmp_sections[section].has_key('max-queued-items') and int(tmp_sections[section]['max-queued-items']) or 0
		
		mw =  tmp_sections[section].has_key('max-workers') and int(tmp_sections[section]['max-workers']) or 0
		
		if not tmp_sections[section].has_key('exclude-dirs'): 
			exc_dirs = []
		else:
			if isinstance(tmp_sections[section]['exclude-dirs'], list):
				exc_dirs = map(lambda x: '^' + x + '.*', tmp_sections[section]['exclude-dirs'])
			else:
				exc_dirs = ['^' + tmp_sections[section]['exclude-dirs'] + '.*']
		
		inc_dirs = tmp_sections[section]['watch-dirs']
		if not type(inc_dirs) is list: inc_dirs = [inc_dirs]
		triggers = tmp_sections[section]['triggers']
		if not type(triggers) is list: triggers = [triggers]
		watch_sections[section] = { 'include': inc_dirs, 'exclude': exc_dirs, 'qtt': qtt, 'mqi': mqi, 'mw': mw, 'triggermod': triggers}
	
	return watch_sections, module_sections

mod_instances = {} # instances of module object per section

daemon = Daemon(
	user="detik",
	group="detik",
        stdin="/dev/null",
        stdout="/var/log/insync/insync.log",
        stderr="/var/log/insync/insync.err",
        pidfile="/var/log/insync/insync.pid",
)

if __name__ == "__main__":
	if daemon.service():
		signal.signal(signal.SIGABRT, clean_exit)
		signal.signal(signal.SIGTERM, clean_exit)
		signal.signal(signal.SIGQUIT, clean_exit)
		signal.signal(signal.SIGINT, clean_exit)

		setproctitle.setproctitle(sys.argv[0])
		os.umask(022)
		os.chdir('/opt/python/app')
		sys.path.append('/opt/python/app')

		watch_sections, module_sections = read_config(daemon.options.conf)

		modules = {}
		for section in module_sections:
			# initialize modules
			modname = module_sections[section]['module']
			if not modname in modules: 
				module = __import__(modname)
				if issubclass(module.__dict__[modname], Trigger):
					modules[modname] = module.__dict__[modname]
			params = dict(filter(lambda x:x[0] != 'module', module_sections[section].items()))
			mod_instances[section] = modules[modname](params) # instantiate module object
		
		curr_active_children = multiprocessing.active_children()
		for section in watch_sections:	
			# each section takes one process
			wsjob = multiprocessing.Process(target=watch_section_job, args=(section, watch_sections[section],))
			wsjob.start()

		while len(multiprocessing.active_children()) > len(curr_active_children):
			time.sleep(1)
		
		for instance in mod_instances:
			mod_instances[instance].on_terminated()

