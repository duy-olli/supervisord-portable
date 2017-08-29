#!/opt/python/bin/python
from errno import EACCES
from os.path import realpath
from sys import argv, exit
from threading import Lock

import os, time, socket, shutil, fuse

from fuse import FUSE, FuseOSError, Operations

class WebIOFS(Operations):    
	def __init__(self, root):
		self.root = realpath(root)
		self.rwlock = Lock()
    
	def __call__(self, op, path, *args):
		return super(WebIOFS, self).__call__(op, self.root + path, *args)
    
	def access(self, path, mode):
		if not os.access(path, mode):
			raise FuseOSError(EACCES)
    
	def getattr(self, path, fh=None):
		st = os.lstat(path)
		return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
			'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

	def open(self, path,flag):
		return os.open(path, flag | os.O_NDELAY)

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
        
	def statfs(self, path):
		stv = os.statvfs(path)
		return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
			'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
			'f_frsize', 'f_namemax'))
    
	utimens = None
	chmod = None
	chown = None
    	create = None
	flush = None 
	fsync = None   
	getxattr = None
    	link = None
	listxattr = None
	mkdir = None
	mknod = None
	rename = None
	rmdir = None
	symlink = None
	truncate = None
	unlink = None
	write = None
    
if __name__ == "__main__":
	if len(argv) != 3:
		print 'usage: %s <root> <mountpoint>' % argv[0]
		exit(1)
	
	fuse = FUSE(WebIOFS(argv[1]), argv[2], foreground=False, allow_other=True, nonempty=True)
    
