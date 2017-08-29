#!/opt/python/bin/python
import multiprocessing, time, ConfigParser, sys, os, string, hashlib, setproctitle, signal, socket, struct
from trigger import Trigger
from daemon import Daemon

is_exit = multiprocessing.Value('b', 0)
isexit = False
def clean_exit(signum, frame):
	global isexit
	is_exit.value = 1
	isexit = True

def execute_module(trigger_modules, operation, pathname, new_pathname=None, data=None):
	global mod_instances
	for trigger in trigger_modules:
		if operation == 'm':
			try:
				if data and not len(data):
					sys.stdout.write("Isinya kok kosong\n")
					sys.stdout.flush()
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
	global digest_list, worker_pool
	pathname, attribute = item
	true_pathname = pathname.lstrip('*')
	modified = False
	data = None

	log_request2(pathname)

	if attribute['op'] in ['c', 'm']:
		if os.path.islink(true_pathname):
			modified = True
		elif os.path.isfile(true_pathname):
			try:
				data = open(true_pathname,'rb').read()
			except Exception, err:
				return False
			if not len(data): data = ""
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
			return False #pass # maybe already deleted or renamed, put it to next list

		if attribute['ts'] == section['watch_list'][pathname]['ts']:
			section['watch_list'].pop(pathname)
	
		if modified:
			if os.path.isdir(true_pathname):
				return worker_pool.apply_async(execute_module, (section['triggermod'], 'm', true_pathname, None, data))
			else:
				worker_pool.apply_async(execute_module, (section['triggermod'], 'm', true_pathname, None, data))
	elif attribute['op'] == 'd':
		# not necessarily needed
		if digest_list.has_key(pathname):
			digest_list.pop(pathname)
		
		if attribute['ts'] == section['watch_list'][pathname]['ts']:
			section['watch_list'].pop(pathname)

		if os.path.isdir(true_pathname):
			return worker_pool.apply_async(execute_module, (section['triggermod'], 'd', true_pathname))
		else:
			worker_pool.apply_async(execute_module, (section['triggermod'], 'd', true_pathname))

	elif attribute['op'] == 'r':
		if digest_list.has_key(pathname):
			attr = digest_list.pop(pathname)
			digest_list[attribute['new_path']] = attr

		# if it's directory, all digest files under it must be cleaned
		if os.path.isdir(attribute['new_path'].lstrip('*')):
			for key in digest_list.keys():
				if key.lstrip('*').startswith(true_pathname + '/'):
					digest_list.pop(key)

		if attribute['ts'] == section['watch_list'][pathname]['ts']:
			section['watch_list'].pop(pathname)
		
		return worker_pool.apply_async(execute_module, (section['triggermod'], 'r', true_pathname, attribute['new_path']))

	return False

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

	while not queue.empty() and len(section['watch_list']) < section['mqi']:
		pathname, attribute = queue.get()
		if not section['first_item_ts']: section['first_item_ts'] = attribute['ts']
		arrange_event_list(pathname, attribute, section['watch_list'])

	worker_triggered = False

	if len(section['watch_list']) >= section['mqi']:
		worker_triggered = True
	if section['first_item_ts'] and time.time() - section['first_item_ts'] >= section['qtt']:
		worker_triggered = True

	return worker_triggered

def watcher(queue_dict, sections):
	setproctitle.setproctitle(sys.argv[0] + ':executor')

	global digest_list, worker_pool
	digest_list = {}

	worker_pool = multiprocessing.Pool(processes=max_workers_default)
	for section_key in sections:
		section = sections[section_key]
		section['watch_list'] = {}
		section['first_item_ts'] = 0

	slen = len(sections)
	idx = 0
	one_round = False
	no_ops = True
	worker_triggered = False
	while not is_exit.value:
		section_key = sections.keys()[idx]
		section = sections[section_key]
		if not worker_triggered:
			worker_triggered = consume_queue(queue_dict[section_key], section)

		if worker_triggered:
			worker_triggered = False
			no_ops = False
			section['first_item_ts'] = 0
			ordered_event_list = sorted(section['watch_list'].items(), key=lambda x:x[1]['ts'])
			for item in ordered_event_list:
				pathname, attribute = item
				wait = do_operation((pathname, attribute), section)	
				curr_idx = idx
				while wait and not wait.ready() and not worker_triggered:
					# doing activity on blocked do_operation
					if idx == len(sections)-1: idx = 0 ; one_round = True
					else: idx += 1
					if idx == curr_idx: 
						wait.wait()
						break
					tmp_section_key = sections.keys()[idx]
					tmp_section = sections[tmp_section_key]
					worker_triggered = consume_queue(queue_dict[tmp_section_key], tmp_section)

		if not worker_triggered:
			if idx == len(sections)-1: idx = 0 ; one_round = True
			else: idx += 1
		
		if one_round:
			one_round = False
			if no_ops: time.sleep(.2)
			else: no_ops = True
			# if max(digest list) => remove n least recently digests (n = max_removed_items) 
			if len(digest_list) >= max_digest_list:
				ts_ordered_digest = sorted(digest_list.items(), key=lambda x:x[1]['ts'])
				for item in ts_ordered_digest[:max_removed_items]:
					digest_list.pop(item[0])

	worker_pool.close()
	worker_pool.join()

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

fd_log2 = None
fd_logdate2 = None
def log_request2(line=None, flushed=True):
        global daemon, fd_log2, fd_logdate2
        now = time.strftime("%Y%m%d", time.localtime())
        if not fd_log2 or now != fd_logdate2:
                fd_logdate2 = now
                if fd_log2: fd_log2.close()
                fd_log2 = open(daemon.options.stdout + "2." + fd_logdate2, "a+")

	if line: fd_log2.write("%s\n" % (line))
	if flushed: fd_log2.flush()

fd_log = None
fd_logdate = None
def log_request(line=None, flushed=True):
        global daemon, fd_log, fd_logdate
        now = time.strftime("%Y%m%d", time.localtime())
        if not fd_log or now != fd_logdate:
                fd_logdate = now
                if fd_log: fd_log.close()
                fd_log = open(daemon.options.stdout + "." + fd_logdate, "a+")

	if line: fd_log.write("%s\n" % (line))
	if flushed: fd_log.flush()

def sendto_queue(line, include_tree, exclude_tree, watch_queue_dict):
	ops, path = line.strip().split('|',1)

	if ops == 'r':
		new_path, path = path.split('|')
		path = monitorfs_mount_dir + path
		new_path = monitorfs_mount_dir + new_path
		queue_val = [path,{ 'op': ops, 'ts': time.time(), 'new_path': new_path }]
	else:
		path = monitorfs_mount_dir + path
		queue_val = [path,{ 'op': ops, 'ts': time.time() }]
		
	log_request(path)
	section = traverse_tree(include_tree, path)
	if section and section != traverse_tree(exclude_tree, path):
		if watch_queue_dict[section].full():
			sys.stdout.write("fulll\n")
			sys.stdout.flush()
		watch_queue_dict[section].put(queue_val)

# 1 process handle filtering message to predefined queues
def watch_section_job(sections): 
	global isexit

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
	sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 20)
	sock.bind((0,1))
	sock.settimeout(.5)

	# register pid for netlink communication
	data="helo"
	hdr = struct.pack("IHHII", len(data) + 4*4, 100, 0, 0, 0)
	sock.send(hdr + data)

	isexit = False
	while not isexit:
		try:
			line = sock.recv(8192)
		except Exception:
			continue

		# acknowledge netlink
		msglen, msg_type, flags, seq, pid = struct.unpack("IHHII", line[:16])
        	ack = struct.pack("IHHIII", 4 + 4*4, 101, 0, 0, 0, seq)
	        sock.send(ack)
		
		lastidx = line[16:].find('\x00')
		if lastidx < 0: 
			sys.stdout.write("Line not ends with 0 %s\n" % line)
			sys.stdout.flush()
			continue

		lastidx += 16
		line = line[16:lastidx]
		sendto_queue(line, include_tree, exclude_tree, queue_dict)
	sock.close()
	watchjob.join()

monitorfs_mount_dir = None
monitorfs_src_dir = None
max_queue_default = 15 # default 15 items queued
max_interval_default = 30 # default 30 seconds
max_workers_default = 5
def read_config(config_path):
	global monitorfs_mount_dir
	if not os.path.exists(config_path):
		print "Configuration file not exists !!"
		return None, None

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

			if section == 'monitorfs':
				if item[0] == 'mount-dir':
					monitorfs_mount_dir = val.rstrip('/')
				elif item[0] == 'src-dir':
					monitorfs_src_dir = val.rstrip('/')
				continue

			tmp_sections[section][item[0]] = val

		if not tmp_sections[section].has_key('watch-dirs') and not tmp_sections[section].has_key('module'): 
			tmp_sections.pop(section)

	if not monitorfs_mount_dir:
		print "Section monitorfs or mount-dir/src-dir items don't exists !!"
		return None, None

	exists = False
	for line in open("/proc/mounts").readlines():
		dev, mnt, fstype, rest = line.split(' ', 3)
		if mnt == monitorfs_mount_dir and fstype == "monitorfs":
			exists = True
			break

	if not exists:
		ret = os.system("mount -t monitorfs %s %s" % (monitorfs_src_dir, monitorfs_mount_dir))
		if ret:
			print "Cannot mount directory with monitorfs filesystem !!"
			return None, None
		
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
		
		if not tmp_sections[section].has_key('exclude-dirs'): 
			exc_dirs = []
		else:
			exc_dirs = tmp_sections[section]['exclude-dirs']
			if not type(exc_dirs) is list: exc_dirs = [exc_dirs]

		inc_dirs = tmp_sections[section]['watch-dirs']
		if not type(inc_dirs) is list: inc_dirs = [inc_dirs]
		triggers = tmp_sections[section]['triggers']
		if not type(triggers) is list: triggers = [triggers]
		watch_sections[section] = { 'include': inc_dirs, 'exclude': exc_dirs, 'qtt': qtt, 'mqi': mqi, 'triggermod': triggers}
	
	return watch_sections, module_sections

mod_instances = {} # instances of module object per section

daemon = Daemon(
	user="root",
	group="root",
        stdin="/dev/null",
        stdout="/var/log/insync/insync.log",
        stderr="/var/log/insync/insync.err",
        pidfile="/var/log/insync/insync.pid",
	conf="./insync.conf",
	workers=str(max_workers_default),
)

if __name__ == "__main__":
	signal.signal(signal.SIGABRT, clean_exit)
	signal.signal(signal.SIGTERM, clean_exit)
	signal.signal(signal.SIGQUIT, clean_exit)
	signal.signal(signal.SIGINT, clean_exit)

	watch_sections, module_sections = read_config(daemon.options.conf)
	if daemon.service():
		if not watch_sections:
			sys.exit()
		setproctitle.setproctitle(sys.argv[0])
		os.umask(022)
		os.chdir('/opt/python/app/insync')
		sys.path.append('/opt/python/app/insync')
		max_workers_default = daemon.options.workers.isdigit() and int(daemon.options.workers) or max_workers_default
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

