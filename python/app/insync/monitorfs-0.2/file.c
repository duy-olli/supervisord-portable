/* monitorfs: pass-through stackable filesystem

   Copyright (C) 1997-2004 Erez Zadok
   Copyright (C) 2001-2004 Stony Brook University
   Copyright (C) 2004-2007 International Business Machines Corp.
   Copyright (C) 2008 John Ogness 
     Author: John Ogness <dazukocode@ogness.net>

   This program is free software; you can redistribute it and/or
   modify it under the terms of the GNU General Public License
   as published by the Free Software Foundation; either version 2
   of the License, or (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
*/

#include <linux/module.h>
#include <linux/fs.h>
#include <linux/mount.h>
#include <linux/file.h>
#include <linux/fs_stack.h>
#include "monitorfs_fs.h"

extern struct kmem_cache *monitorfs_file_info_cachep;

/**
 * monitorfs_llseek - do something.
 * @file: is something.
 * @offset: is something.
 * @origin: is something.
 *
 * Description: Called when the VFS needs to move the file position index.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static loff_t monitorfs_llseek(struct file *file, loff_t offset, int origin)
{
	loff_t retval = -EINVAL;
	struct file *lower_file = GET_LOWER_FILE(file);

	lower_file->f_pos = file->f_pos;

	memcpy(&(lower_file->f_ra), &(file->f_ra),
	       sizeof(struct file_ra_state));

	if (lower_file->f_op && lower_file->f_op->llseek)
		retval = lower_file->f_op->llseek(lower_file, offset, origin);
	else
		retval = generic_file_llseek(lower_file, offset, origin);
	
	if (retval >= 0) {
		file->f_pos = lower_file->f_pos;
		file->f_version = lower_file->f_version;
	}

	return retval;
}

/**
 * monitorfs_read - do something.
 * @file: is something.
 * @buf: is something.
 * @count: is something.
 * @ppos: is something.
 *
 * Description: Called by read(2) and related system calls.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static ssize_t monitorfs_read(struct file *file, char *buf, size_t count,
			   loff_t *ppos)
{
	int err = -EINVAL;
	struct file *lower_file = GET_LOWER_FILE(file);
	loff_t pos_copy = *ppos;

	if (!lower_file->f_op || !lower_file->f_op->read)
		goto out;

	err = lower_file->f_op->read(lower_file, buf, count, &pos_copy);

	lower_file->f_pos = pos_copy;
	*ppos = pos_copy;

	if (err >= 0) {
		fsstack_copy_attr_atime(file->f_dentry->d_inode,
					lower_file->f_dentry->d_inode);
	}
	
	memcpy(&(file->f_ra), &(lower_file->f_ra),
	       sizeof(struct file_ra_state));
out:
	return err;
}

/**
 * monitorfs_write - do something.
 * @file: is something.
 * @buf: is something.
 * @count: is something.
 * @ppos: is something.
 *
 * Description: Called by write(2) and related system calls.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static ssize_t monitorfs_write(struct file *file, const char *buf, size_t count,
			    loff_t *ppos)
{
	int err = -EINVAL;
	struct file *lower_file = GET_LOWER_FILE(file);
	struct inode *inode = file->f_dentry->d_inode;
	struct inode *lower_inode = GET_LOWER_INODE(inode);
	loff_t pos_copy = *ppos;

	if (!lower_file->f_op || !lower_file->f_op->write)
		goto out;

	err = lower_file->f_op->write(lower_file, buf, count, &pos_copy);

	lower_file->f_pos = pos_copy;
	*ppos = pos_copy;

	if (err >= 0)
		fsstack_copy_attr_atime(inode, lower_inode);
	
	memcpy(&(file->f_ra), &(lower_file->f_ra),
	       sizeof(struct file_ra_state));

	mutex_lock(&inode->i_mutex);
	i_size_write(inode, i_size_read(lower_inode));
	mutex_unlock(&inode->i_mutex);
	
	if (GET_FILE_INFO(file))
		GET_FILE_INFO(file)->written = 1;
out:
	return err;
}

/**
 * monitorfs_readdir - do something.
 * @file: is something.
 * @dirent: is something.
 * @filldir: is something.
 *
 * Description: Called when the VFS needs to read the directory contents.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_readdir(struct file *file, void *dirent, filldir_t filldir)
{
	int err;
	struct file *lower_file = GET_LOWER_FILE(file);
	struct inode *inode = file->f_dentry->d_inode;

	lower_file->f_pos = file->f_pos;

	err = vfs_readdir(lower_file, filldir, dirent);

	file->f_pos = lower_file->f_pos;

	if (err >= 0)
		fsstack_copy_attr_atime(inode, lower_file->f_dentry->d_inode);

	return err;
}

/**
 * monitorfs_ioctl - do something.
 * @inode: is something.
 * @file: is something.
 * @cmd: is something.
 * @arg: is something.
 *
 * Description: Called by the ioctl(2) system call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_ioctl(struct inode *inode, struct file *file,
			unsigned int cmd, unsigned long arg)
{
	struct file *lower_file = GET_LOWER_FILE(file);
	struct inode *lower_inode = GET_LOWER_INODE(inode);
	int err = -ENOTTY;

	if (!lower_file || !lower_file->f_op || !lower_file->f_op->ioctl ||
	    !lower_inode) {
		goto out;
	}

	err = lower_file->f_op->ioctl(lower_inode, lower_file, cmd, arg);
out:
        return err;
}

/**
 * monitorfs_open - do something.
 * @inode: is something.
 * @file: is something.
 *
 * Description: Called by the VFS when an inode should be opened. When the
 * VFS opens a file, it creates a new "struct file". It then calls the open
 * method for the newly allocated file structure. You might think that the
 * open method really belongs in "struct inode_operations", and you may be
 * right. I think it's done the way it is because it makes filesystems
 * simpler to implement. The open() method is a good place to initialize
 * the "private_data" member in the file structure if you want to point to
 * a device structure.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_open(struct inode *inode, struct file *file)
{
	struct dentry *dentry = file->f_dentry;
	struct dentry *lower_dentry = dget(GET_LOWER_DENTRY(dentry));
	struct vfsmount *lower_mnt = mntget(GET_LOWER_MNT(dentry));
	struct file *lower_file;
	int err = 0;

	SET_FILE_INFO(file, kmem_cache_zalloc(monitorfs_file_info_cachep,
		      GFP_KERNEL));
	if (!GET_FILE_INFO(file)) {
		err = -ENOMEM;
		goto out;
	}

	lower_file = dentry_open(lower_dentry, lower_mnt, file->f_flags);
	if (IS_ERR(lower_file)) {
		err = PTR_ERR(lower_file);
		goto out;
	}

	SET_LOWER_FILE(file, lower_file);
	GET_FILE_INFO(file)->written = 0;	
out:
	if (err) {
		dput(lower_dentry);
		mntput(lower_mnt);
	}
	return err;
}

/**
 * monitorfs_flush - do something.
 * @inode: is something.
 * @td: is something.
 *
 * Description: Called by the close(2) system call to flush a file.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_flush(struct file *file, fl_owner_t td)
{
	struct file *lower_file = GET_LOWER_FILE(file);
	int err = 0;

	if (!lower_file || !lower_file->f_op || !lower_file->f_op->flush)
		goto out;

	err = lower_file->f_op->flush(lower_file, td);
out:
        return err;
}

/**
 * monitorfs_release - do something.
 * @inode: is something.
 * @file: is something.
 *
 * Description: Called when the last reference to an open file is closed.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_release(struct inode *inode, struct file *file)
{
	struct inode *lower_inode = GET_LOWER_INODE(inode);

	fput(GET_LOWER_FILE(file));
	inode->i_blocks = lower_inode->i_blocks;

	if (GET_FILE_INFO(file) && GET_FILE_INFO(file)->written)
		monitorfs_log_operation(MONITORFS_OPS_MODIFY, file->f_dentry, NULL, file);
		
	kmem_cache_free(monitorfs_file_info_cachep, GET_FILE_INFO(file));

	return 0;
}

/**
 * monitorfs_fsync - do something.
 * @file: is something.
 * @dentry: is something.
 * @datasync: is something.
 *
 * Description: Called by the fsync(2) system call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_fsync(struct file *file, struct dentry *dentry,
			int datasync)
{
	struct file *lower_file = GET_LOWER_FILE(file);
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	int err = -EINVAL;

	if (!lower_file || !lower_file->f_op || !lower_file->f_op->fsync)
		goto out;

	err = lower_file->f_op->fsync(lower_file, lower_dentry, datasync);
out:
        return err;
}

/**
 * monitorfs_fasync - do something.
 * @fd: is something.
 * @file: is something.
 * @flag: is something.
 *
 * Description: .called by the fcntl(2) system call when asynchronous
 * (non-blocking) mode is enabled for a file.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_fasync(int fd, struct file *file, int flag)
{
	struct file *lower_file = GET_LOWER_FILE(file);
	int err = 0;

	if (!lower_file || !lower_file->f_op || !lower_file->f_op->fasync)
		goto out;

	err = lower_file->f_op->fasync(fd, lower_file, flag);
out:
        return err;
}

static ssize_t monitorfs_sendfile(struct file *file, loff_t *ppos,
                size_t count, read_actor_t actor, void *target)
{
	struct file *lower_file = NULL;
	int err = -EINVAL;

	if (GET_FILE_INFO(file) != NULL)
		lower_file = GET_LOWER_FILE(file);
	BUG_ON(!lower_file);

	if (lower_file->f_op && lower_file->f_op->sendfile)
		err = lower_file->f_op->sendfile(lower_file, ppos, count,
						actor, target);

	return err;
}

/**
 * Unused operations:
 *   - owner
 *   - aio_read (generic)
 *   - aio_write (generic)
 *   - poll
 *   - unlocked_ioctl
 *   - compat_ioctl
 *   - mmap (generic)
 *   - aio_fsync
 *   - lock
 *   - sendpage
 *   - get_unmapped_area
 *   - check_flags
 *   - dir_notify
 *   - flock
 *   - splice_write
 *   - splice_read (generic)
 *   - setlease
 */
struct file_operations monitorfs_main_fops = {
	.llseek		= monitorfs_llseek,
	.read		= monitorfs_read,
	.aio_read	= generic_file_aio_read,
	.write		= monitorfs_write,
	.aio_write	= generic_file_aio_write,
	.readdir	= monitorfs_readdir,
	.ioctl		= monitorfs_ioctl,
	.mmap		= generic_file_mmap,
	.open		= monitorfs_open,
	.flush		= monitorfs_flush,
	.release	= monitorfs_release,
	.fsync		= monitorfs_fsync,
	.fasync		= monitorfs_fasync,
	.splice_read	= generic_file_splice_read,
	.sendfile = monitorfs_sendfile,
};

/**
 * Unused operations:
 *   - owner
 *   - llseek
 *   - read
 *   - write
 *   - aio_read
 *   - aio_write
 *   - poll
 *   - unlocked_ioctl
 *   - compat_ioctl
 *   - mmap (generic)
 *   - aio_fsync
 *   - lock
 *   - sendpage
 *   - get_unmapped_area
 *   - check_flags
 *   - dir_notify
 *   - flock
 *   - splice_write
 *   - splice_read (generic)
 *   - setlease
 */
const struct file_operations monitorfs_dir_fops = {
	.readdir	= monitorfs_readdir,
	.ioctl		= monitorfs_ioctl,
	.mmap		= generic_file_mmap,
	.open		= monitorfs_open,
	.flush		= monitorfs_flush,
	.release	= monitorfs_release,
	.fsync		= monitorfs_fsync,
	.fasync		= monitorfs_fasync,
	.splice_read	= generic_file_splice_read,
	.sendfile = monitorfs_sendfile,
};

