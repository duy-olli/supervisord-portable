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

#ifndef _LINUX_MONITORFS_FS_H
#define _LINUX_MONITORFS_FS_H

#define MONITORFS_VERSION_MAJOR		"0"
#define MONITORFS_VERSION_MINOR		"0"
#define MONITORFS_VERSION_REVISION		"4"
#define MONITORFS_VERSION_RELEASE		"1"

/* this must be defined for all release candidate versions */
/* #define MONITORFS_RC */

struct monitorfs_sb_info {
	struct super_block *lower_sb;
};

struct monitorfs_inode_info {
	struct inode *lower_inode;

	/*
	 * the inode (embedded)
	 */
	struct inode vfs_inode;
};

struct monitorfs_dentry_info {
	struct dentry *lower_dentry;
	struct vfsmount *lower_mnt;
};

struct monitorfs_file_info {
	struct file *lower_file;
	u8 written;
};

static inline struct monitorfs_sb_info *GET_SB_INFO(struct super_block *upper_sb)
{
        return upper_sb->s_fs_info;
}

static inline void SET_SB_INFO(struct super_block *upper_sb,
			       struct monitorfs_sb_info *sbi)
{
        upper_sb->s_fs_info = sbi;
}

static inline struct super_block *GET_LOWER_SB(struct super_block *upper_sb)
{
        return ((struct monitorfs_sb_info *)upper_sb->s_fs_info)->lower_sb;
}

static inline void SET_LOWER_SB(struct super_block *upper_sb,
				struct super_block *lower_sb)
{
       ((struct monitorfs_sb_info *)upper_sb->s_fs_info)->lower_sb = lower_sb;
}

static inline struct monitorfs_inode_info *
GET_INODE_INFO(struct inode *upper_inode)
{
        return container_of(upper_inode, struct monitorfs_inode_info, vfs_inode);
}

static inline struct inode *GET_LOWER_INODE(struct inode *upper_inode)
{
        return ((struct monitorfs_inode_info *)
		container_of(upper_inode, struct monitorfs_inode_info,
			     vfs_inode))->lower_inode;
}

static inline void SET_LOWER_INODE(struct inode *upper_inode,
				   struct inode *lower_inode)
{
        ((struct monitorfs_inode_info *)
	 container_of(upper_inode, struct monitorfs_inode_info,
		      vfs_inode))->lower_inode = lower_inode;
}

static inline struct monitorfs_dentry_info *
GET_DENTRY_INFO(struct dentry *upper_dentry)
{
	return upper_dentry->d_fsdata;
}

static inline void SET_DENTRY_INFO(struct dentry *upper_dentry,
				   struct monitorfs_dentry_info *dentryi)
{
	upper_dentry->d_fsdata = dentryi;
}

static inline struct dentry *GET_LOWER_DENTRY(struct dentry *upper_dentry)
{
	return ((struct monitorfs_dentry_info *)
		upper_dentry->d_fsdata)->lower_dentry;
}

static inline struct vfsmount *GET_LOWER_MNT(struct dentry *upper_dentry)
{
	return ((struct monitorfs_dentry_info *)
		upper_dentry->d_fsdata)->lower_mnt;
}

static inline void SET_LOWER_DENTRY(struct dentry *upper_dentry,
				    struct dentry *lower_dentry,
				    struct vfsmount *lower_mnt)
{
	((struct monitorfs_dentry_info *)upper_dentry->d_fsdata)->lower_dentry =
		lower_dentry;
	((struct monitorfs_dentry_info *)upper_dentry->d_fsdata)->lower_mnt =
		lower_mnt;
}

static inline struct monitorfs_file_info *GET_FILE_INFO(struct file *upper_file)
{
	return upper_file->private_data;
}

static inline void SET_FILE_INFO(struct file *upper_file,
				 struct monitorfs_file_info *filei)
{
	upper_file->private_data = filei;
}

static inline struct file *GET_LOWER_FILE(struct file *upper_file)
{
	return ((struct monitorfs_file_info *)
		upper_file->private_data)->lower_file;
}

static inline void SET_LOWER_FILE(struct file *upper_file,
				  struct file *lower_file)
{
	((struct monitorfs_file_info *)upper_file->private_data)->lower_file =
		lower_file;
}

#define MONITORFS_MSG_HELO 100
#define MONITORFS_MSG_ACK 101
#define MONITORFS_TIMEOUT (HZ*3)

#define NETLINK_MONITORFS        30
#define MONITORFS_DEFAULT_SEND_TIMEOUT HZ

struct monitorfs_modified_op_t {
	char *src_pathname;
	char *dst_pathname;
	char *buffer;
	struct mutex mod_op_mux;
	struct mutex send_ack_mux;
	pid_t pid;
#define MONITORFS_OPS_CREATE 1
#define MONITORFS_OPS_MODIFY 2
#define MONITORFS_OPS_DELETE 3
#define MONITORFS_OPS_RENAME 4
	u8 operation;
	u8 status; // waiting response
#define MONITORFS_STATUS_ACK 0
#define MONITORFS_STATUS_WAITING 1
	u32 seqnum;
	wait_queue_head_t waitq;
	struct file *file;
};

extern void monitorfs_log_operation(u8 operation, struct dentry *src_dentry, struct dentry *dst_dentry, struct file *file);

extern int monitorfs_send_and_ack(char *data, int data_len, pid_t pid);			  
			  
extern int monitorfs_init_netlink(void);
extern void monitorfs_release_netlink(void);

#endif  /* _LINUX_MONITORFS_FS_H */

