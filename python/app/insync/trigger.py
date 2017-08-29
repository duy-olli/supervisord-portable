class Trigger(object):
	def __init__(self, params):
		raise NotImplementedError
	def on_modified(self, pathname, data):
		raise NotImplementedError
	def on_deleted(self, pathname):
		raise NotImplementedError
	def on_renamed(self, pathname, new_pathname):
		raise NotImplementedError
	def on_terminated(self):
		raise NotImplementedError
