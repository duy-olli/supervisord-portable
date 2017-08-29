#!/opt/python/bin/python
import hashlib, sys
from trigger import Trigger
class echo(Trigger):
	def __init__(self, params):
		pass
	def on_modified(self, pathname, data):
		if data is None:
			data=""
		sys.stdout.write("Modified item at %s => %s\n" % (pathname, hashlib.md5(data).hexdigest()))
		sys.stdout.flush()
	def on_deleted(self, pathname):
		sys.stdout.write("Deleted item at %s\n" % pathname)
		sys.stdout.flush()
	def on_renamed(self, pathname, new_pathname):
		sys.stdout.write("Renamed item at %s to %s\n" % (pathname, new_pathname)) 
		sys.stdout.flush()
	def on_terminated(self):
		pass
