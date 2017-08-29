#!/opt/python/bin/python
from errno import EACCES
from os.path import realpath
from sys import argv, exit
from threading import Lock

import os, time, socket, shutil, fuse

from fuse import FUSE, FuseOSError, Operations

log_dir_ops = "/dev/shm/monitorfs"
curr_fd = None
cache_list = {}
max_list = 100
max_delay = 5

# m = modify; c = create; d = delete; r = rename; s = close
def notify(path, operation, rename_path = None):
	global cache_list, curr_fd

	now = time.time()
	minute = time.localtime()[4]

	if curr_fd is None or int(os.path.basename(curr_fd.name)) != minute:
		if curr_fd: curr_fd.close()
		curr_fd = open(os.path.join(log_dir_ops, "%02d" % minute), "w+")

	# handling redudant write
	if operation in  ['m','c']:
		if len(cache_list) > max_list:
			cache_list.clear()

		if not path in cache_list:
			cache_list[path] = now
		elif now - cache_list[path] > max_delay:
			cache_list[path] = now
		else:
			return
	elif operation in ['d','r','s']:
		if path in cache_list:
			cache_list.pop(path)
		if operation == 's': return		

	try:
		if rename_path:
			data = "%s|%f|%s|%s\n" % (operation, now, path, rename_path)
		else:
			data = "%s|%f|%s\n" % (operation, now, path)
		curr_fd.write(data)
		curr_fd.flush()
	except Exception, err:
		pass
	

class MonitorFS(Operations):    
	def __init__(self, root):
		self.root = realpath(root)
		self.rwlock = Lock()
    
	def __call__(self, op, path, *args):
		return super(MonitorFS, self).__call__(op, self.root + path, *args)
    
	def access(self, path, mode):
		if not os.access(path, mode):
			raise FuseOSError(EACCES)
    
	chmod = os.chmod
	chown = os.chown
    
	def create(self, path, mode):
		notify(path, 'c')
		ret = os.open(path, os.O_WRONLY | os.O_CREAT, mode)
		uid, gid, pid = fuse.fuse_get_context()
		os.chown(path, uid, gid)
		return ret
    
	def flush(self, path, fh):
		return os.fsync(fh)

	def fsync(self, path, datasync, fh):
		return os.fsync(fh)
                
	def getattr(self, path, fh=None):
		st = os.lstat(path)
		return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
			'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
    
	getxattr = None
    
	def link(self, target, source):
		if os.path.lexists(self.root + source):
			notify(target, 'c')
		return os.link(self.root + source, target)
    
	listxattr = None

	def mkdir(self, path, mode):
		if not os.path.lexists(path):
			notify(path, 'c')
		ret = os.mkdir(path, mode)
		uid, gid, pid = fuse.fuse_get_context()
		os.chown(path, uid, gid)
		return ret
	
	def mknod(self, path, mode, dev):
		# FIXME: not this time (webio not supported)
		#if not os.path.lexists(path):
		#	notify(path, 'c')
		ret = os.mknod(path, mode, dev)
		uid, gid, pid = fuse.fuse_get_context()
		os.chown(path, uid, gid)
		return ret

	def open(self, path,flag):
		return os.open(path, flag)

	def read(self, path, size, offset, fh):
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.read(fh, size)
    
	def readdir(self, path, fh):
		return ['.', '..'] + os.listdir(path)

	readlink = os.readlink
    
	def release(self, path, fh):
		notify(path, 's')
		return os.close(fh)
        
	def rename(self, old, new):
		if os.path.lexists(old):
			notify(old, 'r', self.root + new)
		return os.rename(old, self.root + new)
    
	def rmdir(self, path):
		if os.path.lexists(path):
			notify(path, 'd')
		return os.rmdir(path)
    
	def statfs(self, path):
		stv = os.statvfs(path)
		return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
			'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
			'f_frsize', 'f_namemax'))
    
	def symlink(self, target, source):
		notify(target, 'c')
		ret = os.symlink(source, target)
		uid, gid, pid = fuse.fuse_get_context()
		try:
			os.chown(target, uid, gid)
		except Exception, err:
			pass
		return ret
    
	def truncate(self, path, length, fh=None):
		notify(path, 'm')
		with open(path, 'r+') as f:
			f.truncate(length)
    
	def unlink(self, path):
		if os.path.lexists(path):
			notify(path, 'd')
		return os.unlink(path)
	
	utimens = os.utime
    
	def write(self, path, data, offset, fh):
		notify(path, 'm')
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.write(fh, data)
    

if __name__ == "__main__":
	if len(argv) != 3:
		print 'usage: %s <root> <mountpoint>' % argv[0]
		exit(1)
	
	# clear old logs
	shutil.rmtree(log_dir_ops,True)
	os.mkdir(log_dir_ops)
		
	fuse = FUSE(MonitorFS(argv[1]), argv[2], foreground=False, allow_other=True, nonempty=True)
    
