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
#include <linux/namei.h>
#include <linux/mount.h>
#include <linux/uaccess.h>
#include <linux/fs_stack.h>
#include "monitorfs_fs.h"

extern struct kmem_cache *monitorfs_dentry_info_cachep;
extern struct dentry_operations monitorfs_dops;
extern struct file_operations monitorfs_main_fops;
extern struct file_operations monitorfs_dir_fops;
extern struct address_space_operations monitorfs_aops;

static struct inode_operations monitorfs_symlink_iops;
static struct inode_operations monitorfs_dir_iops;
static struct inode_operations monitorfs_main_iops;

/**
 * monitorfs_inode_test - do something.
 * @inode: is something.
 * @candidate_lower_inode: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_inode_test(struct inode *inode, void *candidate_lower_inode)
{
	if (GET_LOWER_INODE(inode) ==
	    (struct inode *)candidate_lower_inode) {
		return 1;
	}

	return 0;
}

/**
 * monitorfs_init_inode - do something.
 * @inode: is something.
 * @lower_inode: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void monitorfs_init_inode(struct inode *inode, struct inode *lower_inode)
{
	SET_LOWER_INODE(inode, lower_inode);
	inode->i_ino = lower_inode->i_ino;
	inode->i_version++;
	inode->i_op = &monitorfs_main_iops;
	inode->i_fop = &monitorfs_main_fops;
	inode->i_mapping->a_ops = &monitorfs_aops;
}

/**
 * monitorfs_inode_set - do something.
 * @inode: is something.
 * @lower_inode: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_inode_set(struct inode *inode, void *lower_inode)
{
	monitorfs_init_inode(inode, (struct inode *)lower_inode);
	return 0;
}

/**
 * monitorfs_interpose - do something.
 * @lower_dentry: is something.
 * @dentry: is something.
 * @sb: is something.
 * @flag: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
int monitorfs_interpose(struct dentry *lower_dentry, struct dentry *dentry,
		     struct super_block *sb, int flag)
{
	struct inode *inode;
	struct inode *lower_inode = igrab(lower_dentry->d_inode);
	int err = 0;

	if (!lower_inode) {
		err = -ESTALE;
		goto out;
	}

	if (lower_inode->i_sb != GET_LOWER_SB(sb)) {
		iput(lower_inode);
		err = -EXDEV;
		goto out;
	}

	inode = iget5_locked(sb, (unsigned long)lower_inode,
			     monitorfs_inode_test, monitorfs_inode_set,
			     lower_inode);

	if (!inode) {
		iput(lower_inode);
		err = -EACCES;
		goto out;
	}

	if (inode->i_state & I_NEW) {
		unlock_new_inode(inode);
		/*
		 * This is a new node so we leave the lower_node "in use"
		 * and do not call iput().
		 */
	} else {
		/*
		 * This is not a new node so we decrement the usage count.
		 */
		iput(lower_inode);
	}

	if (S_ISLNK(lower_inode->i_mode))
		inode->i_op = &monitorfs_symlink_iops;
	else if (S_ISDIR(lower_inode->i_mode))
		inode->i_op = &monitorfs_dir_iops;

	if (S_ISDIR(lower_inode->i_mode))
		inode->i_fop = &monitorfs_dir_fops;

	if (special_file(lower_inode->i_mode)) {
		init_special_inode(inode, lower_inode->i_mode,
				   lower_inode->i_rdev);
	}

	dentry->d_op = &monitorfs_dops;

	if (flag)
		d_add(dentry, inode);
	else
		d_instantiate(dentry, inode);

	fsstack_copy_attr_all(inode, lower_inode, NULL);
	fsstack_copy_inode_size(inode, lower_inode);
out:
	return err;
}

/**
 * monitorfs_lookup - do something.
 * @dir: is something.
 * @dentry: is something.
 * @nd: is something.
 *
 * Description: Called when the VFS needs to look up an inode in a parent
 * directory. The name to look for is found in the dentry. This method
 * must call d_add() to insert the found inode into the dentry. The
 * "i_count" field in the inode structure should be incremented. If the
 * named inode does not exist a NULL inode should be inserted into the
 * dentry (this is called a negative dentry). Returning an error code
 * from this routine must only be done on a real error, otherwise
 * creating inodes with system calls like create(2), mknod(2), mkdir(2)
 * and so on will fail. If you wish to overload the dentry methods then
 * you should initialise the "d_dop" field in the dentry; this is a
 * pointer to a struct "dentry_operations". This method is called with
 * the directory inode semaphore held.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static struct dentry *monitorfs_lookup(struct inode *dir, struct dentry *dentry,
				    struct nameidata *nd)
{
	struct dentry *lower_dentry;
	struct dentry *lower_dentry_parent;
	struct vfsmount *lower_mnt;
	int err = 0;

	if ((dentry->d_name.len == 1 && !strcmp(dentry->d_name.name, "."))
	    || (dentry->d_name.len == 2 &&
		!strcmp(dentry->d_name.name, ".."))) {
		d_drop(dentry);
		goto out;
	}

	dentry->d_op = &monitorfs_dops;

	lower_dentry_parent = GET_LOWER_DENTRY(dentry->d_parent);
	lower_dentry = lookup_one_len(dentry->d_name.name, lower_dentry_parent,
				      dentry->d_name.len);

	if (IS_ERR(lower_dentry)) {
		err = PTR_ERR(lower_dentry);
		d_drop(dentry);
		goto out;
	}

	BUG_ON(!atomic_read(&lower_dentry->d_count));

	SET_DENTRY_INFO(dentry, kmem_cache_zalloc(monitorfs_dentry_info_cachep,
			GFP_KERNEL));

	if (!GET_DENTRY_INFO(dentry)) {
		err = -ENOMEM;
		goto out_dput;
	}

	lower_mnt = mntget(GET_LOWER_MNT(dentry->d_parent));

	fsstack_copy_attr_atime(dir, lower_dentry_parent->d_inode);

	SET_LOWER_DENTRY(dentry, lower_dentry, lower_mnt);

	if (!lower_dentry->d_inode) {
		/*
		 * We want to add because we could not find in lower.
		 */
		d_add(dentry, NULL);
		goto out;
	}

	err = monitorfs_interpose(lower_dentry, dentry, dir->i_sb, 1);
	if (err)
		goto out_dput;
	goto out;

out_dput:
	dput(lower_dentry);
	d_drop(dentry);

out:
	return ERR_PTR(err);
}

/**
 * monitorfs_mknod - do something.
 * @dir: is something.
 * @dentry: is something.
 * @mode: is something.
 * @dev: is something.
 *
 * Description: Called by the mknod(2) system call to create a device
 * (char, block) inode or a named pipe (FIFO) or socket. Only required if
 * you want to support creating these types of inodes. You will probably
 * need to call d_instantiate() just as you would in the create() method.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_mknod(struct inode *dir, struct dentry *dentry, int mode,
			dev_t dev)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err = -ENOENT;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_mknod(lower_dentry_parent_inode, lower_dentry, mode, dev);
	if (err)
		goto out;

	err = monitorfs_interpose(lower_dentry, dentry, dir->i_sb, 0);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	fsstack_copy_inode_size(dir, lower_dentry_parent_inode);
	monitorfs_log_operation(MONITORFS_OPS_CREATE, dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_mkdir - do something.
 * @dir: is something.
 * @dentry: is something.
 * @mode: is something.
 *
 * Description: Called by the mkdir(2) system call. Only required if you
 * want to support creating subdirectories. You will probably need to call
 * d_instantiate() just as you would in the create() method.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_mkdir(struct inode *dir, struct dentry *dentry, int mode)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err = -ENOENT;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_mkdir(lower_dentry_parent_inode, lower_dentry, mode);
	if (err)
		goto out;

	err = monitorfs_interpose(lower_dentry, dentry, dir->i_sb, 0);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	fsstack_copy_inode_size(dir, lower_dentry_parent_inode);
	dir->i_nlink = lower_dentry_parent_inode->i_nlink;
	monitorfs_log_operation(MONITORFS_OPS_CREATE, dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_create - do something.
 * @dir: is something.
 * @dentry: is something.
 * @mode: is something.
 * @nd: is something.
 *
 * Description: Called by the open(2) and creat(2) system calls. Only
 * required if you want to support regular files. The dentry you get
 * should not have an inode (i.e. it should be a negative dentry). Here
 * you will probably call d_instantiate() with the dentry and the newly
 * created inode.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_create(struct inode *dir, struct dentry *dentry, int mode,
			 struct nameidata *nd)
{
	struct vfsmount *lower_mnt = GET_LOWER_MNT(dentry);
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	struct vfsmount *vfsmount_save;
	struct dentry *dentry_save;
	int err = -ENOENT;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	vfsmount_save = nd->mnt;
	dentry_save = nd->dentry;

	nd->mnt = mntget(lower_mnt);
	nd->dentry = dget(lower_dentry);

	err = vfs_create(lower_dentry_parent_inode, lower_dentry, mode, nd);

	mntput(lower_mnt);
	dput(lower_dentry);

	nd->mnt = vfsmount_save;
	nd->dentry = dentry_save;

	if (err)
		goto out;

	err = monitorfs_interpose(lower_dentry, dentry, dir->i_sb, 0);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	fsstack_copy_inode_size(dir, lower_dentry_parent_inode);
	monitorfs_log_operation(MONITORFS_OPS_CREATE, dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_symlink - do something.
 * @dir: is something.
 * @dentry: is something.
 * @symname: is something.
 *
 * Description: Called by the symlink(2) system call. Only required if you
 * want to support symlinks. You will probably need to call d_instantiate()
 * just as you would in the create() method.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_symlink(struct inode *dir, struct dentry *dentry,
			  const char *symname)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err = -ENOENT;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_symlink(lower_dentry_parent_inode, lower_dentry, symname,
			  S_IALLUGO);
	if (err)
		goto out;

	err = monitorfs_interpose(lower_dentry, dentry, dir->i_sb, 0);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	fsstack_copy_inode_size(dir, lower_dentry_parent_inode);
	monitorfs_log_operation(MONITORFS_OPS_CREATE, dentry, NULL, NULL);		
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_readlink - do something.
 * @dentry: is something.
 * @buf: is something.
 * @bufsiz: is something.
 *
 * Description: Called by the readlink(2) system call. Only required if
 * you want to support reading symbolic links.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_readlink(struct dentry *dentry, char __user *buf,
			   int bufsiz)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *lower_dentry_inode = lower_dentry->d_inode;
	int err = 0;

	if (!lower_dentry_inode) {
		err = -ENOENT;
		d_drop(dentry);
		goto out;
	}

	if (!lower_dentry_inode->i_op ||
	    !lower_dentry_inode->i_op->readlink) {
		err = -EINVAL;
		goto out;
	}

	err = lower_dentry_inode->i_op->readlink(lower_dentry, buf, bufsiz);
	if (err)
		goto out;

	fsstack_copy_attr_times(dentry->d_inode, lower_dentry_inode);
out:
	return err;
}

/**
 * monitorfs_follow_link - do something.
 * @dentry: is something.
 * @nd: is something.
 *
 * Description: Called by the VFS to follow a symbolic link to the inode
 * it points to. Only required if you want to support symbolic links. This
 * method returns a void pointer cookie that is passed to put_link().
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static void *monitorfs_follow_link(struct dentry *dentry, struct nameidata *nd)
{
	mm_segment_t fs_save;
	int rc;
	char *buf;
	int len = PAGE_SIZE;
	int err = 0;

	/*
	 * Released in monitorfs_put_link(). Only release here on error.
	 */
	buf = kmalloc(len, GFP_KERNEL);
	if (!buf) {
		err = -ENOMEM;
		goto out;
	}

	fs_save = get_fs();
	set_fs(get_ds());
	rc = monitorfs_readlink(dentry, (char __user *)buf, len);
	set_fs(fs_save);

	if (rc < 0) {
		err = rc;
		goto out_free;
	}
	buf[rc] = 0;

        nd_set_link(nd, buf);
        goto out;

out_free:
	kfree(buf);
out:
	return ERR_PTR(err);
}

/**
 * monitorfs_put_link - do something.
 * @dentry: is something.
 * @nd: is something.
 * @ptr: is something.
 *
 * Description: Called by the VFS to release resources allocated by
 * follow_link(). The cookie returned by follow_link() is passed to this
 * method as the last parameter. It is used by filesystems such as NFS
 * where page cache is not stable (i.e. page that was installed when the
 * symbolic link walk started might not be in the page cache at the end
 * of the walk).
 *
 * We do some stuff and then call the lower function version.
 */
static void monitorfs_put_link(struct dentry *dentry, struct nameidata *nd,
			    void *ptr)
{
	/*
	 * Release the char* from monitorfs_follow_link().
	 */
	kfree(nd_get_link(nd));
}

/**
 * monitorfs_permission - do something.
 * @inode: is something.
 * @mask: is something.
 * @nd: is something.
 *
 * Description: Called by the VFS to check for access rights on a
 * POSIX-like filesystem.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_permission(struct inode *inode, int mask,
			     struct nameidata *nd)
{
	struct vfsmount *lower_mnt = NULL;
	struct dentry *lower_dentry = NULL;
	struct vfsmount *vfsmnt_save = NULL;
	struct dentry *dentry_save = NULL;
	int err;

	if (nd) {
		lower_mnt = GET_LOWER_MNT(nd->dentry);
		lower_dentry = GET_LOWER_DENTRY(nd->dentry);

		vfsmnt_save = nd->mnt;
		dentry_save = nd->dentry;

		nd->mnt = mntget(lower_mnt);
		nd->dentry = dget(lower_dentry);
	}

	err = permission(GET_LOWER_INODE(inode), mask, nd);

	if (nd) {
		mntput(lower_mnt);
		dput(lower_dentry);

		nd->mnt = vfsmnt_save;
		nd->dentry = dentry_save;
	}

        return err;
}

/**
 * monitorfs_setattr - do something.
 * @dentry: is something.
 * @ia: is something.
 *
 * Description: Called by the VFS to set attributes for a file. This method
 * is called by chmod(2) and related system calls.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_setattr(struct dentry *dentry, struct iattr *ia)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *inode = dentry->d_inode;
	struct inode *lower_inode = GET_LOWER_INODE(inode);
	int err;

	err = notify_change(lower_dentry, ia);

	fsstack_copy_attr_all(inode, lower_inode, NULL);
	fsstack_copy_inode_size(inode, lower_inode);

	return err;
}

/**
 * monitorfs_setxattr - do something.
 * @dentry: is something.
 * @name: is something.
 * @value: is something.
 * @flags: is something.
 *
 * Description: Called by the VFS to set an extended attribute for a file.
 * Extended attribute is a name:value pair associated with an inode. This
 * method is called by setxattr(2) system call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_setxattr(struct dentry *dentry, const char *name,
			   const void *value, size_t size, int flags)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *lower_dentry_inode = lower_dentry->d_inode;
	int err = 0;

	if (!lower_dentry_inode) {
		err = -ENOENT;
		d_drop(dentry);
		goto out;
	}

	if (!lower_dentry_inode->i_op ||
	    !lower_dentry_inode->i_op->setxattr) {
		err = -ENOSYS;
		goto out;
	}

        err = lower_dentry_inode->i_op->setxattr(lower_dentry, name, value,
						 size, flags);

	fsstack_copy_attr_all(dentry->d_inode, lower_dentry_inode, NULL);
	fsstack_copy_inode_size(dentry->d_inode, lower_dentry_inode);
out:
        return err;
}

/**
 * monitorfs_getxattr - do something.
 * @dentry: is something.
 * @name: is something.
 * @value: is something.
 * @size: is something.
 *
 * Description: Called by the VFS to retrieve the value of an extended
 * attribute name. This method is called by getxattr(2) function call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static ssize_t monitorfs_getxattr(struct dentry * dentry, const char *name,
			       void * value, size_t size)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *lower_dentry_inode = lower_dentry->d_inode;
	ssize_t err = 0;

	if (!lower_dentry_inode) {
		err = -ENOENT;
		d_drop(dentry);
		goto out;
	}

	if (!lower_dentry_inode->i_op ||
	    !lower_dentry_inode->i_op->getxattr) {
		err = -ENOSYS;
		goto out;
	}

        err = lower_dentry_inode->i_op->getxattr(lower_dentry, name,
						 value, size);
out:
        return err;
}

/**
 * monitorfs_listxattr - do something.
 * @dentry: is something.
 * @list: is something.
 * @size: is something.
 *
 * Description: Called by the VFS to list all extended attributes for a
 * given file. This method is called by listxattr(2) system call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static ssize_t monitorfs_listxattr(struct dentry *dentry, char *list,
				size_t size)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *lower_dentry_inode = lower_dentry->d_inode;
	int err = 0;

	if (!lower_dentry_inode) {
		err = -ENOENT;
		d_drop(dentry);
		goto out;
	}

	if (!lower_dentry_inode->i_op ||
	    !lower_dentry_inode->i_op->listxattr) {
		err = -ENOSYS;
		goto out;
	}

        err = lower_dentry_inode->i_op->listxattr(lower_dentry, list, size);
out:
        return err;
}

/**
 * monitorfs_removexattr - do something.
 * @dentry: is something.
 * @name: is something.
 *
 * Description: Called by the VFS to remove an extended attribute from a
 * file. This method is called by removexattr(2) system call.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_removexattr(struct dentry *dentry, const char *name)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct inode *lower_dentry_inode = lower_dentry->d_inode;
	int err = 0;

	if (!lower_dentry_inode) {
		err = -ENOENT;
		d_drop(dentry);
		goto out;
	}

	if (!lower_dentry_inode->i_op ||
	    !lower_dentry_inode->i_op->removexattr) {
		err = -ENOSYS;
		goto out;
	}

        err = lower_dentry_inode->i_op->removexattr(lower_dentry, name);
out:
        return err;
}

/**
 * monitorfs_link - do something.
 * @old_dentry: is something.
 * @dir: is something.
 * @new_dentry: is something.
 *
 * Description: Called by the link(2) system call. Only required if you want
 * to support hard links. You will probably need to call d_instantiate()
 * just as you would in the create() method.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_link(struct dentry *old_dentry, struct inode *dir,
		       struct dentry *new_dentry)
{
	struct dentry *lower_old_dentry = GET_LOWER_DENTRY(old_dentry);
	struct dentry *lower_new_dentry = GET_LOWER_DENTRY(new_dentry);
	struct dentry *lower_dentry_parent = dget(lower_new_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err = -ENOENT;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_link(lower_old_dentry, lower_dentry_parent_inode,
		       lower_new_dentry);
	if (err)
		goto out;

	err = monitorfs_interpose(lower_new_dentry, new_dentry, dir->i_sb, 0);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	fsstack_copy_inode_size(dir, lower_dentry_parent_inode);
	monitorfs_log_operation(MONITORFS_OPS_CREATE, new_dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_unlink - do something.
 * @dir: is something.
 * @dentry: is something.
 *
 * Description: Called by the unlink(2) system call. Only required if you
 * want to support deleting inodes.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_unlink(struct inode *dir, struct dentry *dentry)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_unlink(lower_dentry_parent_inode, lower_dentry);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	dentry->d_inode->i_nlink =
		GET_LOWER_INODE(dentry->d_inode)->i_nlink;
	fsstack_copy_attr_times(dentry->d_inode, dir);
	monitorfs_log_operation(MONITORFS_OPS_DELETE, dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	return err;
}

/**
 * monitorfs_rmdir - do something.
 * @dir: is something.
 * @dentry: is something.
 *
 * Description: Called by the rmdir(2) system call. Only required if you
 * want to support deleting subdirectories.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_rmdir(struct inode *dir, struct dentry *dentry)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);
	struct dentry *lower_dentry_parent = dget(lower_dentry->d_parent);
	struct inode *lower_dentry_parent_inode = lower_dentry_parent->d_inode;
	int err;

	mutex_lock_nested(&(lower_dentry_parent_inode->i_mutex),
			  I_MUTEX_PARENT);

	err = vfs_rmdir(lower_dentry_parent_inode, lower_dentry);
	if (err)
		goto out;

	fsstack_copy_attr_times(dir, lower_dentry_parent_inode);
	dir->i_nlink = lower_dentry_parent_inode->i_nlink;
	monitorfs_log_operation(MONITORFS_OPS_DELETE, dentry, NULL, NULL);
out:
	mutex_unlock(&(lower_dentry_parent_inode->i_mutex));
	dput(lower_dentry_parent);

	if (!err)
		d_drop(dentry);

	return err;
}

/**
 * monitorfs_rename - do something.
 * @old_dir: is something.
 * @old_dentry: is something.
 * @new_dir: is something.
 * @new_dentry: is something.
 *
 * Description: Called by the rename(2) system call to rename the object to
 * have the parent and name given by the second inode and dentry.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_rename(struct inode *old_dir, struct dentry *old_dentry,
			 struct inode *new_dir, struct dentry *new_dentry)
{
	struct dentry *lower_old_dentry = GET_LOWER_DENTRY(old_dentry);
	struct dentry *lower_new_dentry = GET_LOWER_DENTRY(new_dentry);
	struct dentry *lower_old_dentry_parent =
		dget(lower_old_dentry->d_parent);
	struct dentry *lower_new_dentry_parent =
		dget(lower_new_dentry->d_parent);
	struct inode *lower_old_dentry_parent_inode =
		lower_old_dentry_parent->d_inode;
	struct inode *lower_new_dentry_parent_inode =
		lower_new_dentry_parent->d_inode;
	int err = -ENOENT;

	if (!lower_old_dentry_parent_inode) {
		d_drop(old_dentry);
		goto out;
	}

	if (!lower_new_dentry_parent_inode) {
		d_drop(new_dentry);
		goto out;
	}

	lock_rename(lower_old_dentry_parent, lower_new_dentry_parent);
	err = vfs_rename(lower_old_dentry_parent_inode, lower_old_dentry,
			 lower_new_dentry_parent_inode, lower_new_dentry);
	unlock_rename(lower_old_dentry_parent, lower_new_dentry_parent);

	if (err)
		goto out;

	fsstack_copy_attr_all(new_dir, lower_new_dentry_parent_inode, NULL);
	if (new_dir != old_dir)
		fsstack_copy_attr_all(old_dir, lower_old_dentry_parent_inode,
				      NULL);

	monitorfs_log_operation(MONITORFS_OPS_RENAME, old_dentry, new_dentry, NULL);
out:
	dput(lower_old_dentry_parent);
	dput(lower_new_dentry_parent);

	return err;
}

/**
 * Unused operations:
 *   - create
 *   - lookup
 *   - link
 *   - unlink
 *   - symlink
 *   - mkdir
 *   - rmdir
 *   - mknod
 *   - rename
 *   - truncate
 *   - getattr
 *   - truncate_range
 *   - fallocate
 */
static struct inode_operations monitorfs_symlink_iops = {
	.readlink	= monitorfs_readlink,
	.follow_link	= monitorfs_follow_link,
	.put_link	= monitorfs_put_link,
	.permission	= monitorfs_permission,
	.setattr	= monitorfs_setattr,
	.setxattr	= monitorfs_setxattr,
	.getxattr	= monitorfs_getxattr,
	.listxattr	= monitorfs_listxattr,
	.removexattr	= monitorfs_removexattr,
};

/**
 * Unused operations:
 *   - readlink
 *   - follow_link
 *   - put_link
 *   - truncate
 *   - getattr
 *   - truncate_range
 *   - fallocate
 */
static struct inode_operations monitorfs_dir_iops = {
	.create		= monitorfs_create,
	.lookup		= monitorfs_lookup,
	.link		= monitorfs_link,
	.unlink		= monitorfs_unlink,
	.symlink	= monitorfs_symlink,
	.mkdir		= monitorfs_mkdir,
	.rmdir		= monitorfs_rmdir,
	.mknod		= monitorfs_mknod,
	.rename		= monitorfs_rename,
	.permission	= monitorfs_permission,
	.setattr	= monitorfs_setattr,
	.setxattr	= monitorfs_setxattr,
	.getxattr	= monitorfs_getxattr,
	.listxattr	= monitorfs_listxattr,
	.removexattr	= monitorfs_removexattr,
};

/**
 * Unused operations:
 *   - create
 *   - lookup
 *   - link
 *   - unlink
 *   - symlink
 *   - mkdir
 *   - rmdir
 *   - mknod
 *   - rename
 *   - readlink
 *   - follow_link
 *   - put_link
 *   - truncate
 *   - getattr
 *   - truncate_range
 *   - fallocate
 */
static struct inode_operations monitorfs_main_iops = {
	.permission	= monitorfs_permission,
	.setattr	= monitorfs_setattr,
	.setxattr	= monitorfs_setxattr,
	.getxattr	= monitorfs_getxattr,
	.listxattr	= monitorfs_listxattr,
	.removexattr	= monitorfs_removexattr,
};

