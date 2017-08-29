#!/opt/python/bin/python
import Image, StringIO, os, sys, time
from trigger import Trigger

class thumbnail(Trigger):
	def __init__(self, params):
		self.src = params['src-root-dir']	
		self.dst = params['dst-root-dir']
		self.scale = float(params['scale-percentage'])/100

	def on_modified(self, pathname, data):
		relpath = os.path.relpath(pathname, self.src)
		dst_path = os.path.join(self.dst, relpath)
		dst_dir = os.path.dirname(dst_path)
		if not os.path.exists(dst_dir):
			os.makedirs(dst_dir)

		if os.path.isdir(pathname):
			os.mkdir(dst_path)
		else:
			try:
				strio = StringIO.StringIO(data)
				img = Image.open(strio)
				newsize = (int(round(img.size[0] * self.scale)), int(round(img.size[1] * self.scale)))
				newimg = img.resize(newsize)
				newimg.save(dst_path)
				sys.stdout.write("%s : Done scaling image : %s\n" % (time.ctime(), dst_path))
			except IOError, e:
				sys.stdout.write("Unknown image : %s\n" % dst_path)
			sys.stdout.flush()			

	def on_deleted(self, pathname):
		relpath = os.path.relpath(pathname, self.src)
		dst_path = os.path.join(self.dst, relpath)
		if os.path.isdir(pathname):
			os.rmdir(dst_path)
		else:
			os.unlink(dst_path)

	def on_renamed(self, pathname, new_pathname):
		relpath = os.path.relpath(pathname, self.src)
		new_relpath = os.path.relpath(new_pathname, self.src)
		dst_path = os.path.join(self.dst, relpath)
		new_dst_path = os.path.join(self.dst, new_relpath)
		os.rename(dst_path, new_dst_path)

	def on_terminated(self):
		pass
