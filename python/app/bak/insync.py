#!/opt/python/bin/python
import multiprocessing, time, ConfigParser, sys, os, string, hashlib, setproctitle, signal
from trigger import Trigger
from daemon import Daemon

is_exit = multiprocessing.Value('b', 0)
def clean_exit(signum, frame):
	is_exit.value = 1

def execute_module(trigger_modules, operation, pathname, new_pathname=None, data=None):
	global mod_instances
	for trigger in trigger_modules:
		if operation == 'm':
			try:
				mod_instances[trigger].on_modified(pathname, data)
			except Exception, err:
				print err
		elif operation == 'd':
			try:
				mod_instances[trigger].on_deleted(pathname)
			except Exception, err:
				print err
		else:
			try:
				mod_instances[trigger].on_renamed(pathname, new_pathname)
			except Exception, err:
				print err

def do_operation(item, section):
	global digest_list
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
			if attribute['ts'] == section['watch_list'][pathname]['ts']:
				section['watch_list'].pop(pathname)

			executor = os.path.isdir(true_pathname) and section['worker_pool'].apply or section['worker_pool'].apply_async
			executor(execute_module, (section['triggermod'], 'm', true_pathname, None, data))
	
	elif attribute['op'] == 'd':
		# not necessarily needed
		if digest_list.has_key(pathname):
			digest_list.pop(pathname)
		
		if attribute['ts'] == section['watch_list'][pathname]['ts']:
			section['watch_list'].pop(pathname)

		executor = os.path.isdir(true_pathname) and section['worker_pool'].apply or section['worker_pool'].apply_async
		executor(execute_module, (section['triggermod'], 'd', true_pathname))

	elif attribute['op'] == 'r':
		if digest_list.has_key(pathname):
			attr = digest_list.pop(pathname)
			digest_list[attribute['new_path']] = attr

		if attribute['ts'] == section['watch_list'][pathname]['ts']:
			section['watch_list'].pop(pathname)
		
		executor = section['worker_pool'].apply
		executor(execute_module, (section['triggermod'], 'r', true_pathname, attribute['new_path']))

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

max_digest_list = 10000 
max_removed_items = 10 # for digest list

def consume_queue(queue, section):
	if not queue.empty():
		pathname, attribute = queue.get()
		updated = True
		if not section['first_item_ts']: section['first_item_ts'] = attribute['ts']
		#print "Terima queue : ", pathname, attribute
	else:
		updated = False
	
	worker_triggered = False
	if updated: arrange_event_list(pathname, attribute, section['watch_list']) 

	if len(section['watch_list']) >= section['mqi']:
		worker_triggered = True
	if section['first_item_ts'] and time.time() - section['first_item_ts'] >= section['qtt']:
		worker_triggered = True

	return worker_triggered

def watcher(queue_dict, sections):
	setproctitle.setproctitle(sys.argv[0] + ':executor')

	global digest_list
	digest_list = {}

	for section_key in sections:
		section = sections[section_key]
		section['watch_list'] = {}
		section['first_item_ts'] = 0
		section['worker_pool'] = multiprocessing.Pool(processes=section['mw'])

	while not is_exit.value:
		no_ops = True
		for section_key in sections:
			section = sections[section_key]

			worker_triggered = consume_queue(queue_dict[section_key], section)
		
			if worker_triggered:
				#print "masuk worker triggered"
				no_ops = False
				section['first_item_ts'] = 0
				ordered_event_list = sorted(section['watch_list'].items(), key=lambda x:x[1]['ts'])
				for item in ordered_event_list:
					pathname, attribute = item
					do_operation((pathname, attribute), section)	
		
		if no_ops: time.sleep(.2)			
		# if max(digest list) => remove n least recently digests (n = max_removed_items) 
		if len(digest_list) >= max_digest_list:
			ts_ordered_digest = sorted(digest_list.items(), key=lambda x:x[1]['ts'])
			for item in ts_ordered_digest[:max_removed_items]:
				digest_list.pop(item[0])

	for section_key in sections:
		section = sections[section_key]
		section['worker_pool'].close()
		section['worker_pool'].join()

log_dir_ops = "/dev/shm/monitorfs"

def build_map_tree(sections, key):
	map_tree = {}
	for section in sections:
		list_dir = sections[section][key]
		for dir in list_dir:
			dir_parts = dir.strip('/').split('/')
			map = map_tree
			for part in dir_parts:
				if not map.has_key(part):
					map[part] = {}
				map = map[part]
			map['/'] = section # mark this belong to section 'x'
	return map_tree
				
def traverse_tree(map_tree, dir):
	dir_parts = dir.strip('/').split('/')
	map = map_tree
	for part in dir_parts:
		if not map.has_key(part):
			return map.has_key('/') and map['/'] or None
		else: map = map[part]
	return map.has_key('/') and map['/'] or None

def sendto_queue(line, include_tree, exclude_tree, watch_queue_dict):
	ops, ts, path = line.strip().split('|',2)
	if ops == 'r':
		path, new_path = path.split('|')
		queue_val = [path,{ 'op': ops, 'ts': float(ts), 'new_path': new_path }]
	else:
		queue_val = [path,{ 'op': ops, 'ts': float(ts) }]
		
	section = traverse_tree(include_tree, path)
	if section and section != traverse_tree(exclude_tree, path):
		#print "kirim ke queue : ", queue_val
		watch_queue_dict[section].put(queue_val)

# 1 process handle filtering message to predefined queues
def watch_section_job(sections): 
	# build map tree for search (mapping pathname to section handle)
	include_tree = build_map_tree(sections, 'include')
	exclude_tree = build_map_tree(sections, 'exclude')

	queue_dict =  {}
	for section in sections:
		queue_dict[section] = multiprocessing.Queue()

	# process to consume queued items from this producer
	watchjob = multiprocessing.Process(target=watcher, args=(queue_dict, sections,))
	watchjob.start()
	
	# watch monitorfs's log
	fd = None
	currname = None
	while not is_exit.value:
		minute = time.localtime()[4]
		log_path = "%s/%02d" % (log_dir_ops, minute)
		if (not fd or currname != minute) and os.path.exists(log_path) and (time.time() - os.stat(log_path).st_mtime) <= 60:
			if fd: 
				# catch last lines which might be missed
				lines = fd.readlines()
				for line in lines:
					sendto_queue(line, include_tree, exclude_tree, queue_dict)	
				fd.close()
			fd = open(log_path, "r")
			currname = minute
	
		if fd:	
			lines = fd.readlines()
			for line in lines:
				sendto_queue(line, include_tree, exclude_tree, queue_dict)	
			else: time.sleep(.1)
		else: time.sleep(1)	

	watchjob.join()

max_queue_default = 15 # default 15 items queued
max_interval_default = 30 # default 30 seconds
max_workers_default = 5
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

		qtt = tmp_sections[section].has_key('queue-threshold-time') and int(tmp_sections[section]['queue-threshold-time']) or max_interval_default

		mqi = tmp_sections[section].has_key('max-queued-items') and int(tmp_sections[section]['max-queued-items']) or max_queue_default
		
		mw =  tmp_sections[section].has_key('max-workers') and int(tmp_sections[section]['max-workers']) or max_workers_default
		
		if not tmp_sections[section].has_key('exclude-dirs'): 
			exc_dirs = []
		else:
			exc_dirs = tmp_sections[section]['exclude-dirs']
			if not type(exc_dirs) is list: exc_dirs = [exc_dirs]

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
	conf="./insync.conf",
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
		
		watch_section_job(watch_sections)

		for instance in mod_instances:
			mod_instances[instance].on_terminated()

