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
#include <linux/version.h>
#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/mount.h>
#include <linux/pagemap.h>
#include "monitorfs_fs.h"

extern struct monitorfs_modified_op_t monitorfs_modified_op;
extern struct dentry_operations monitorfs_dops;

static struct kmem_cache *monitorfs_inode_info_cachep = NULL;
static struct kmem_cache *monitorfs_sb_info_cachep = NULL;
struct kmem_cache *monitorfs_dentry_info_cachep = NULL;
struct kmem_cache *monitorfs_file_info_cachep = NULL;

/* binary version stamp */
const char *MONITORFS_VERSION_STAMP = "\nmonitorfsVersion="
	MONITORFS_VERSION_MAJOR "."
	MONITORFS_VERSION_MINOR "."
	MONITORFS_VERSION_REVISION "."
	MONITORFS_VERSION_RELEASE "\n";

/* version string for display */
const char *MONITORFS_VERSION_STRING =
	MONITORFS_VERSION_MAJOR "."
	MONITORFS_VERSION_MINOR "."
	MONITORFS_VERSION_REVISION
#ifdef MONITORFS_RC
"-rc" MONITORFS_VERSION_RELEASE
#endif
;

int monitorfs_interpose(struct dentry *lower_dentry, struct dentry *dentry,
		     struct super_block *sb, int flag);

/**
 * monitorfs_alloc_inode - do something.
 * @sb: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static struct inode *monitorfs_alloc_inode(struct super_block *sb)
{
	struct monitorfs_inode_info *inodei;

	inodei = kmem_cache_alloc(monitorfs_inode_info_cachep, GFP_KERNEL);
	if (!inodei)
		return NULL;

	/*
	 * The inode is embedded within the monitorfs_inode_info struct.
	 */
	return &(inodei->vfs_inode);
}

/**
 * monitorfs_destroy_inode - do something.
 * @inode: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static void monitorfs_destroy_inode(struct inode *inode)
{
	/*
	 * The inode is embedded within the monitorfs_inode_info struct.
	 */
	kmem_cache_free(monitorfs_inode_info_cachep,
			GET_INODE_INFO(inode));
}

/**
 * monitorfs_statfs - do something.
 * @dentry: is something.
 * @buf: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_statfs(struct dentry *dentry, struct kstatfs *buf)
{
	return vfs_statfs(GET_LOWER_DENTRY(dentry), buf);
}

/**
 * monitorfs_clear_inode - do something.
 * @inode: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void monitorfs_clear_inode(struct inode *inode)
{
	iput(GET_LOWER_INODE(inode));
}

/**
 * monitorfs_put_super - do something.
 * @sb: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void monitorfs_put_super(struct super_block *sb)
{
	struct monitorfs_sb_info *sbi = GET_SB_INFO(sb);

	if (sbi)
		kmem_cache_free(monitorfs_sb_info_cachep, sbi);
}

/**
 * Unused operations:
 *   - dirty_inode
 *   - write_inode
 *   - put_inode
 *   - drop_inode
 *   - delete_inode
 *   - write_super
 *   - sync_fs
 *   - write_super_lockfs
 *   - unlockfs
 *   - remount_fs
 *   - umount_begin
 *   - show_options
 *   - show_stats
 *   - quota_read
 *   - quota_write
 */
static struct super_operations monitorfs_sops = {
	.alloc_inode	= monitorfs_alloc_inode,
	.destroy_inode	= monitorfs_destroy_inode,
	.put_super	= monitorfs_put_super,
	.statfs		= monitorfs_statfs,
	.clear_inode	= monitorfs_clear_inode,
};

/**
 * monitorfs_parse_mount_options - do something.
 * @options: is something.
 * @sb: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_parse_mount_options(char *options, struct super_block *sb)
{
	return 0;
}

/**
 * monitorfs_fill_super - do something.
 * @sb: is something.
 * @data: is something.
 * @silent: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_fill_super(struct super_block *sb, void *data, int silent)
{
	struct monitorfs_sb_info *sbi;
	struct dentry *root;
	static const struct qstr name = { .name = "/", .len = 1 };
	struct monitorfs_dentry_info *di;

	sbi =  kmem_cache_zalloc(monitorfs_sb_info_cachep, GFP_KERNEL);
	if (!sbi)
		return -ENOMEM;

	sb->s_op = &monitorfs_sops;

	root = d_alloc(NULL, &name);
	if (!root) {
		kmem_cache_free(monitorfs_sb_info_cachep, sbi);
		return -ENOMEM;
	}

	sb->s_root = root;

	sb->s_root->d_op = &monitorfs_dops;
	sb->s_root->d_sb = sb;
	sb->s_root->d_parent = sb->s_root;

	di = kmem_cache_zalloc(monitorfs_dentry_info_cachep, GFP_KERNEL);
	if (!di) {
		kmem_cache_free(monitorfs_sb_info_cachep, sbi);
		dput(sb->s_root);
		return -ENOMEM;
	}

	SET_DENTRY_INFO(sb->s_root, di);

	SET_SB_INFO(sb, sbi);

	return 0;
}

/**
 * monitorfs_read_super - do something.
 * @sb: is something.
 * @dev_name: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_read_super(struct super_block *sb, const char *dev_name)
{
	struct nameidata nd;
	struct dentry *lower_root;
	struct vfsmount *lower_mnt;
	int err;

	memset(&nd, 0, sizeof(struct nameidata));
	err = path_lookup(dev_name, LOOKUP_FOLLOW | LOOKUP_DIRECTORY, &nd);
	if (err)
		return err;

	lower_root = dget(nd.dentry);
	lower_mnt = mntget(nd.mnt);

	if (IS_ERR(lower_root)) {
		err = PTR_ERR(lower_root);
		goto out_put;
	}

	if (!lower_root->d_inode) {
		err = -ENOENT;
		goto out_put;
	}

	SET_LOWER_SB(sb, lower_root->d_sb);
	sb->s_maxbytes = lower_root->d_sb->s_maxbytes;
	SET_LOWER_DENTRY(sb->s_root, lower_root, lower_mnt);

	err = monitorfs_interpose(lower_root, sb->s_root, sb, 0);
	if (err)
		goto out_put;
	goto out;

out_put:
	dput(lower_root);
	mntput(lower_mnt);
out:
	//path_put(&nd.path);
	dput(nd.dentry);
	mntput(nd.mnt);	
	return err;
}

/**
 * monitorfs_get_sb - do something.
 * @fs_type: is something.
 * @flags: is something.
 * @dev_name: is something.
 * @mnt: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int monitorfs_get_sb(struct file_system_type *fs_type,
	int flags, const char *dev_name, void *data, struct vfsmount *mnt)
{
	struct super_block *sb;
	int err;

	err = get_sb_nodev(fs_type, flags, data, monitorfs_fill_super, mnt);
	if (err)
		goto out;

	sb = mnt->mnt_sb;

	err = monitorfs_parse_mount_options(data, sb);
	if (err)
		goto out_abort;

	err = monitorfs_read_super(sb, dev_name);
	if (err)
		goto out_abort;

	goto out;

out_abort:
	up_write(&sb->s_umount);
	deactivate_super(sb);
out:
	return err;
}

/**
 * init_once - do something.
 * @cachep: is something.
 * @vptr: is something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void init_once(void *vptr, struct kmem_cache *cachep, unsigned long flags )
{
	struct monitorfs_inode_info *inode_info =
		(struct monitorfs_inode_info *)vptr;

	memset(inode_info, 0, sizeof(struct monitorfs_inode_info));
	inode_init_once(&(inode_info->vfs_inode));
}

/**
 * destroy_caches - do something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void destroy_caches(void)
{
	if (monitorfs_inode_info_cachep) {
		kmem_cache_destroy(monitorfs_inode_info_cachep);
		monitorfs_inode_info_cachep = NULL;
	}

	if (monitorfs_sb_info_cachep) {
		kmem_cache_destroy(monitorfs_sb_info_cachep);
		monitorfs_sb_info_cachep = NULL;
	}

	if (monitorfs_dentry_info_cachep) {
		kmem_cache_destroy(monitorfs_dentry_info_cachep);
		monitorfs_dentry_info_cachep = NULL;
	}

	if (monitorfs_file_info_cachep) {
		kmem_cache_destroy(monitorfs_file_info_cachep);
		monitorfs_file_info_cachep = NULL;
	}
	kfree(monitorfs_modified_op.buffer);
}

/**
 * init_caches - do something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int init_caches(void)
{
	monitorfs_inode_info_cachep =
		kmem_cache_create("monitorfs_inode_info_cache",
				  sizeof(struct monitorfs_inode_info), 0,
				  SLAB_HWCACHE_ALIGN,
				  init_once, NULL);
	if (!monitorfs_inode_info_cachep)
		goto out_nomem;

	monitorfs_sb_info_cachep =
		kmem_cache_create("monitorfs_sb_info_cache",
				  sizeof(struct monitorfs_sb_info), 0,
				  SLAB_HWCACHE_ALIGN,
				  NULL, NULL);
	if (!monitorfs_sb_info_cachep)
		goto out_nomem;

	monitorfs_dentry_info_cachep =
		kmem_cache_create("monitorfs_dentry_info_cache",
				  sizeof(struct monitorfs_dentry_info), 0,
				  SLAB_HWCACHE_ALIGN,
				  NULL, NULL);
	if (!monitorfs_dentry_info_cachep)
		goto out_nomem;

	monitorfs_file_info_cachep =
		kmem_cache_create("monitorfs_file_info_cache",
				  sizeof(struct monitorfs_file_info), 0,
				  SLAB_HWCACHE_ALIGN,
				  NULL, NULL);
	if (!monitorfs_file_info_cachep)
		goto out_nomem;

	monitorfs_modified_op.buffer = kmalloc(PAGE_CACHE_SIZE, GFP_KERNEL);
	if (!monitorfs_modified_op.buffer) {
			goto out_nomem;		
	}
	memset(monitorfs_modified_op.buffer, 0, PAGE_CACHE_SIZE);
	monitorfs_modified_op.src_pathname = NULL;
	monitorfs_modified_op.dst_pathname = NULL;
	monitorfs_modified_op.pid = 0;
	monitorfs_modified_op.seqnum = 0;
	mutex_init(&monitorfs_modified_op.mod_op_mux);
	mutex_init(&monitorfs_modified_op.send_ack_mux);
	init_waitqueue_head(&monitorfs_modified_op.waitq);
		
	return 0;

out_nomem:
	destroy_caches();
	return -ENOMEM;
}

static struct file_system_type monitorfs_fs_type = {
	.owner		= THIS_MODULE,
	.name		= "monitorfs",
	.get_sb		= monitorfs_get_sb,
	/*
	 * XXX: We are using kill_anon_super() instead of my own function.
	 *      Is this OK?
	 */
	.kill_sb	= kill_anon_super,
	.fs_flags	= 0,
};

/**
 * init_monitorfs_fs - do something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 *
 * Returns some result.
 */
static int __init init_monitorfs_fs(void)
{
	int err;

	err = init_caches();
	if (err)
		return err;
		
	err = monitorfs_init_netlink();
	if (err) {
		destroy_caches();
		goto out;
	}
		
	err = register_filesystem(&monitorfs_fs_type);
	if (err) {
		destroy_caches();

	} else {
		printk(KERN_INFO "monitorfs: loaded, version=%s\n",
		       MONITORFS_VERSION_STRING);
	}
out:
	return err;
}

/**
 * exit_monitorfs_fs - do something.
 *
 * Description: Does something.
 *
 * We do some stuff and then call the lower function version.
 */
static void __exit exit_monitorfs_fs(void)
{
	monitorfs_release_netlink();
	unregister_filesystem(&monitorfs_fs_type);
	destroy_caches();
	printk(KERN_INFO "monitorfs: unloaded, version=%s\n",
	       MONITORFS_VERSION_STRING);
}

MODULE_AUTHOR("John Ogness");
MODULE_DESCRIPTION("pass-through stackable filesystem");
MODULE_LICENSE("GPL");
module_init(init_monitorfs_fs)
module_exit(exit_monitorfs_fs)

