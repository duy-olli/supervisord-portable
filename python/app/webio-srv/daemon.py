#!/opt/python/bin/python

import os, sys, pwd, grp, optparse, signal

class Daemon(object):
	def __init__(self, stdin="/dev/null", stdout="/dev/null", stderr="/dev/null", pidfile=None, user=None, group=None, port="10101", rootdir=None, readonly=True):
		options = dict(
			stdin=stdin,
			stdout=stdout,
			stderr=stderr,
			pidfile=pidfile,
			user=user,
			group=group,
			port=port,
			rootdir=rootdir,
			readonly=readonly,
		)

		self.options = optparse.Values(options)

	def openstreams(self):
		si = open(self.options.stdin, "r")
		so = open(self.options.stdout, "a+", 0)
		se = open(self.options.stderr, "a+", 0)
		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
		self.log = so
	
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
		p.add_option("-i", "--stdin", dest="stdin", help="stdin filename (default %default)", default=self.options.stdin)
		p.add_option("-o", "--stdout", dest="stdout", help="stdout filename (default %default)", default=self.options.stdout)
		p.add_option("-e", "--stderr", dest="stderr", help="stderr filename (default %default)", default=self.options.stderr)
		p.add_option("-u", "--user", dest="user", help="user name or id (default %default)", default=self.options.user)
		p.add_option("-g", "--group", dest="group", help="group name or id (default %default)", default=self.options.group)
		p.add_option("-P", "--port", dest="port", help="port number (default %default)", default=self.options.port)
		p.add_option("-r", "--rootdir", dest="rootdir", help="root directory (default %default)", default=self.options.rootdir)
		p.add_option("-R", "--readonly", dest="readonly", action="store_true", help="readonly (default %default)", default=self.options.readonly)
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
