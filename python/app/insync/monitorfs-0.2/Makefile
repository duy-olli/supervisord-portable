#
# Makefile for the nullfs-filesystem routines.
#

MFS_KERNEL_SRC     = /lib/modules/`uname -r`/build
MFS_KERNEL_INSTALL = /lib/modules/`uname -r`/kernel/fs/mfs

# EXTRA_CFLAGS += -DNULLFS_HOOK_UNNEEDED
# EXTRA_CFLAGS += -DNULLFS_HOOK_UNWANTED

obj-m += mfs.o

mfs-objs := super.o inode.o file.o dentry.o mmap.o netlink.o

mfs_modules:
	make -C $(MFS_KERNEL_SRC) SUBDIRS="`pwd`" modules

mfs_install: mfs_modules
	mkdir -p $(MFS_KERNEL_INSTALL)
	cp mfs.ko $(MFS_KERNEL_INSTALL)
	/sbin/depmod -ae

clean:
	rm -f Module.symvers
	make -C $(MFS_KERNEL_SRC) SUBDIRS="`pwd`" clean

.PHONY: mfs_modules mfs_install clean
