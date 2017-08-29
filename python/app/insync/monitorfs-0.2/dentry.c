/* monitorfs: pass-through stackable filesystem

   Copyright (C) 1997-2003 Erez Zadok
   Copyright (C) 2001-2003 Stony Brook University
   Copyright (C) 2004-2006 International Business Machines Corp.
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
#include <linux/fs_stack.h>
#include "monitorfs_fs.h"

extern struct kmem_cache *monitorfs_dentry_info_cachep;

/**
 * monitorfs_d_revalidate - revalidate a dentry found in the dcache
 * @dentry: dentry to revalidate
 * @nd: nameidata associated with dentry
 *
 * Description: Called when the VFS needs to revalidate a dentry. This is
 * called whenever a name look-up finds a dentry in the dcache. Most
 * filesystems leave this as NULL, because all their dentries in the dcache
 * are valid.
 *
 * Call d_revalidate() on the lower dentry if available. The mnt/dentry
 * (path) data in the nameidata needs to be temporarily swapped out for the
 * lower call.
 *
 * After the call, the original path data is restored and the dentry's inode
 * attributes are updated to match the lower inode.
 *
 * Returns 1 if dentry is valid, otherwise 0.
 */
static int monitorfs_d_revalidate(struct dentry *dentry, struct nameidata *nd)
{
	struct vfsmount *lower_mnt;
	struct dentry *lower_dentry;
	struct vfsmount *vfsmount_save;
	struct dentry *dentry_save;
	int valid;

	valid = 1;

	lower_dentry = GET_LOWER_DENTRY(dentry);

	if (!lower_dentry->d_op || !lower_dentry->d_op->d_revalidate)
		goto out;

	lower_mnt = GET_LOWER_MNT(dentry);

	vfsmount_save = nd->mnt;
	dentry_save = nd->dentry;

	nd->mnt = mntget(lower_mnt);
	nd->dentry = dget(lower_dentry);

	valid = lower_dentry->d_op->d_revalidate(lower_dentry, nd);

	mntput(lower_mnt);
	dput(lower_dentry);

	nd->mnt = vfsmount_save;
	nd->dentry = dentry_save;

	/* update the inode, even if d_revalidate() != 1 */
	if (dentry->d_inode) {
		struct inode *lower_inode;

		lower_inode = GET_LOWER_INODE(dentry->d_inode);

                fsstack_copy_attr_all(dentry->d_inode, lower_inode, NULL);
        }
out:
        return valid;
}

/**
 * monitorfs_d_hash - hash the given name
 * @dentry: the parent dentry
 * @name: the name to hash
 *
 * Description: Called when the VFS adds a dentry to the hash table.
 *
 * Call d_hash() on the lower dentry if available. Otherwise monitorfs
 * does nothing. This is ok because the VFS will compute a default
 * hash.
 *
 * Returns 0 on success.
 */
static int monitorfs_d_hash(struct dentry *dentry, struct qstr *name)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);

	if (!lower_dentry || !lower_dentry->d_op ||
	    !lower_dentry->d_op->d_hash) {
		return 0;
	}

	return lower_dentry->d_op->d_hash(lower_dentry, name);
}

/**
 * monitorfs_d_release - clean up dentry
 * @dentry: the dentry that will be released
 *
 * Description: Called when a dentry is really deallocated.
 *
 * Release our hold on the lower dentry and mnt. Then free the structure
 * (from the cache) containing the lower data for this dentry.
 */
static void monitorfs_d_release(struct dentry *dentry)
{
	if (GET_DENTRY_INFO(dentry)) {
		dput(GET_LOWER_DENTRY(dentry));
		mntput(GET_LOWER_MNT(dentry));

		kmem_cache_free(monitorfs_dentry_info_cachep,
				GET_DENTRY_INFO(dentry));
	}
}

/**
 * monitorfs_d_compare - used to compare dentry's
 * @dentry: the parent dentry
 * @a: qstr of an existing dentry
 * @b: qstr of a second dentry (dentry may not be valid)
 *
 * Description: Called when a dentry should be compared with another.
 *
 * Call d_compare() on the lower dentry if available. Otherwise, perform
 * some basic comparisons between the two qstr's.
 *
 * Returns 0 if they are the same, otherwise 1.
 */
static int monitorfs_d_compare(struct dentry *dentry, struct qstr *a,
			    struct qstr *b)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);

	if (lower_dentry && lower_dentry->d_op &&
	    lower_dentry->d_op->d_compare) {

		return lower_dentry->d_op->d_compare(lower_dentry, a, b);
	}

	if (a->len != b->len)
		return 1;
	if (memcmp(a->name, b->name, a->len))
		return 1;

	return 0;

}

#ifdef MONITORFS_HOOK_UNNEEDED
/**
 * monitorfs_d_delete - called when refcount is 0
 * @dentry: dentry to delete
 *
 * Description: Called when the last reference to a dentry is deleted.
 * This means no-one is using the dentry, however it is still valid and
 * in the dcache.
 *
 * monitorfs does not need to do anything here. When the last reference to
 * a lower dentry is deleted, the VFS subsystem will call this function
 * directly on the lower dentry.
 *
 * Returns 0 on success.
 */
static int monitorfs_d_delete(struct dentry *dentry)
{
	return 0;
}

/**
 * monitorfs_d_iput - called when dentry loses its inode
 * @dentry: dentry that loses the inode
 * @inode: the inode being lost
 *
 * Description: Called when a dentry loses its inode (just prior to its
 * being deallocated). The default when this is NULL is that the VFS calls
 * iput(). If you define this method, you must call iput() yourself.
 *
 * monitorfs does not need to do anything with the lower dentry here. When
 * the lower dentry loses its inode, the VFS subsystem will call this
 * function directy on the lower dentry.
 */
static void monitorfs_d_iput(struct dentry *dentry, struct inode *inode)
{
	iput(inode);
}
#endif /* MONITORFS_HOOK_UNNEEDED */

#ifdef MONITORFS_HOOK_UNWANTED
/**
 * monitorfs_d_dname: dynamically create a name for the dentry
 * @dentry: the dentry to create a name for
 * @buffer: buffer to hold the name
 * @buflen: size of the buffer
 *
 * Description: Called when the pathname of a dentry should be generated.
 * Usefull for some pseudo filesystems (sockfs, pipefs, ...) to delay
 * pathname generation. (Instead of doing it when dentry is created, its
 * done only when the path is needed.). Real filesystems probably don't
 * want to use it, because their dentries are present in global dcache
 * hash, so their hash should be an invariant. As no lock is held,
 * d_dname() should not try to modify the dentry itself, unless
 * appropriate SMP safety is used. CAUTION : d_path() logic is quite tricky.
 * The correct way to return for example "Hello" is to put it at the end of
 * the buffer, and returns a pointer to the first char. dynamic_dname()
 * helper function is provided to take care of this.
 *
 * Call d_name() on the lower dentry if available. Otherwise, handle this
 * the way that pipefs does it.
 *
 * WARNING: If this hook is enabled, _ALL_ dpath() lookups will result
 *          in this function being called instead of doing a real file
 *          name lookup.
 *
 * Returns a dynamically created name (as a pointer within the buffer).
 */
static char * monitorfs_d_dname(struct dentry *dentry, char *buffer, int buflen)
{
	struct dentry *lower_dentry = GET_LOWER_DENTRY(dentry);

	if (lower_dentry && lower_dentry->d_op &&
	    lower_dentry->d_op->d_dname) {

		return lower_dentry->d_op->d_dname(dentry, buffer, buflen);
	}

	return dynamic_dname(dentry, buffer, buflen, "monitorfs:[%lu]",
			     dentry->d_inode->i_ino);
}
#endif /* MONITORFS_HOOK_UNWANTED */

struct dentry_operations monitorfs_dops = {
	.d_revalidate	= monitorfs_d_revalidate,
	.d_hash		= monitorfs_d_hash,
	.d_release	= monitorfs_d_release,
	.d_compare	= monitorfs_d_compare,
#ifdef MONITORFS_HOOK_UNNEEDED
	.d_delete	= monitorfs_d_delete,
	.d_iput		= monitorfs_d_iput,
#endif
#ifdef MONITORFS_HOOK_UNWANTED
	.d_dname	= monitorfs_d_dname,
#endif
};

