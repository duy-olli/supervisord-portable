/*
 * Copyright (c) 1997-2007 Erez Zadok <ezk@cs.stonybrook.edu>
 * Copyright (c) 2001-2007 Stony Brook University
 *
 * For specific licensing information, see the COPYING file distributed with
 * this package, or get one from
 * ftp://ftp.filesystems.org/pub/fistgen/COPYING.
 *
 * This Copyright notice must be kept intact and distributed with all
 * fistgen sources INCLUDING sources generated by fistgen.
 */
/*
 * File: fistgen/templates/Linux-2.6/file.c
 */

#ifdef FISTGEN
# include "fist_monitorfs.h"
#endif /* FISTGEN */
#include "fist.h"
#include "monitorfs.h"
#include <linux/mount.h>
#include <linux/security.h>

/*******************
 * File Operations *
 *******************/


STATIC loff_t
monitorfs_llseek(file_t *file, loff_t offset, int origin)
{
	loff_t err;
	file_t *lower_file = NULL;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);

	fist_dprint(6, "monitorfs_llseek: file=%p, offset=0x%llx, origin=%d\n",
                    file, offset, origin);

	BUG_ON(!lower_file);

	/* always set lower position to this one */
	lower_file->f_pos = file->f_pos;


	memcpy(&(lower_file->f_ra), &(file->f_ra), sizeof(struct file_ra_state));

	if (lower_file->f_op && lower_file->f_op->llseek)
		err = lower_file->f_op->llseek(lower_file, offset, origin);
	else
		err = generic_file_llseek(lower_file, offset, origin);

	if (err < 0)
		goto out;

	if (err != file->f_pos) {
		file->f_pos = err;
		// ION maybe this?
		// 	file->f_pos = lower_file->f_pos;
		file->f_version ++ ;//
	}
out:
	print_exit_status((int) err);
	return err;
}



STATIC ssize_t
monitorfs_read(file_t *file, char *buf, size_t count, loff_t *ppos)
{
	int err = -EINVAL;
	file_t *lower_file = NULL;
	loff_t pos = *ppos;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	if (!lower_file->f_op || !lower_file->f_op->read)
		goto out;

	err = lower_file->f_op->read(lower_file, buf, count, &pos);

	if (err >= 0) {
		/* atime should also be updated for reads of size zero or more */
		fist_copy_attr_atime(file->f_dentry->d_inode,
                                     lower_file->f_dentry->d_inode);
	}

	// MAJOR HACK
	/*
	 * because pread() does not have any way to tell us that it is
	 * our caller, then we don't know for sure if we have to update
	 * the file positions.  This hack relies on read() having passed us
	 * the "real" pointer of its struct file's f_pos field.
	 */
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,0)
	if (ppos == &file->f_pos)
#endif /* LINUX_VERSION_CODE < KERNEL_VERSION(2,6,0) */
		lower_file->f_pos = *ppos = pos;

//    if (lower_file->f_reada) { /* update readahead information if needed */  // XXX: ZH: any way to check if it changed? flag doesn't exist
	memcpy(&(file->f_ra), &(lower_file->f_ra), sizeof(struct file_ra_state));	// XXX: ZH: this a new structure.
//    }

out:
	print_exit_status(err);
	return err;
}


/* this monitorfs_write() does not modify data pages! */
STATIC ssize_t
monitorfs_write(file_t *file, const char *buf, size_t count, loff_t *ppos)
{
	int err = -EINVAL;
	file_t *lower_file = NULL;
	inode_t *inode;
	inode_t *lower_inode;
	loff_t pos = *ppos;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	inode = file->f_dentry->d_inode;
	lower_inode = INODE_TO_LOWER(inode);

	if (!lower_file->f_op || !lower_file->f_op->write)
		goto out;

	/* adjust for append -- seek to the end of the file */
	if ((file->f_flags & O_APPEND) && (count != 0))
		pos = i_size_read(inode);

	if (count != 0)
		err = lower_file->f_op->write(lower_file, buf, count, &pos);
	else
		err = 0;

	/*
	 * copy ctime and mtime from lower layer attributes
	 * atime is unchanged for both layers
	 */
	if (err >= 0)
		fist_copy_attr_times(inode, lower_inode);

	/*
	 * XXX: MAJOR HACK
	 *
	 * because pwrite() does not have any way to tell us that it is
	 * our caller, then we don't know for sure if we have to update
	 * the file positions.  This hack relies on write() having passed us
	 * the "real" pointer of its struct file's f_pos field.
	 */
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,0)
	if (ppos == &file->f_pos)
#endif /* LINUX_VERSION_CODE < KERNEL_VERSION(2,6,0) */
		lower_file->f_pos = *ppos = pos;

	/* update this inode's size */
	if (pos > i_size_read(inode))
		i_size_write(inode, pos);
		
	FILE_TO_PRIVATE(file)->written = 1;
out:
	print_exit_status(err);
	return err;
}


#if defined(FIST_FILTER_NAME) || defined(FIST_FILTER_SCA)
struct monitorfs_getdents_callback {
	void *dirent;
	struct dentry *dentry;
	filldir_t filldir;
	int err;
	int filldir_called;
	int entries_written;
};

/* copied from generic filldir in fs/readir.c */
STATIC int
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,19)
monitorfs_filldir(void *dirent, const char *name, int namlen, loff_t offset, ino_t ino, unsigned int d_type)
#else
monitorfs_filldir(void *dirent, const char *name, int namlen, loff_t offset, u64 ino, unsigned int d_type)
#endif
{
	struct monitorfs_getdents_callback *buf = (struct monitorfs_getdents_callback *) dirent;
	int err;

	print_entry_location();

	buf->filldir_called++;


	err = buf->filldir(buf->dirent, name, namlen, offset, ino, d_type);
        if (err >= 0) {
                buf->entries_written++;
	}

out:
	print_exit_status(err);
	return err;
}
#endif /* FIST_FILTER_NAME || FIST_FILTER_SCA */


STATIC int
monitorfs_readdir(file_t *file, void *dirent, filldir_t filldir)
{
	int err = -ENOTDIR;
	file_t *lower_file = NULL;
	inode_t *inode;
#if defined(FIST_FILTER_NAME) || defined(FIST_FILTER_SCA)
	struct monitorfs_getdents_callback buf;
#endif /* FIST_FILTER_NAME || FIST_FILTER_SCA */

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	inode = file->f_dentry->d_inode;

	fist_checkinode(inode, "monitorfs_readdir"); // XXX: ZH: Halcrow commented this out, he doesnt like debugging info
	lower_file->f_pos = file->f_pos;

#if defined(FIST_FILTER_NAME) || defined(FIST_FILTER_SCA)
	/* prepare for callback */
	buf.dirent = dirent;
	buf.dentry = file->f_dentry;
	buf.filldir = filldir;
retry:
	buf.filldir_called = 0;
	buf.entries_written = 0;
	buf.err = 0;
	err = vfs_readdir(lower_file, monitorfs_filldir, (void *) &buf);
	if (buf.err) {
		err = buf.err;
	}
	if (buf.filldir_called && !buf.entries_written) {
		goto retry;
	}
#else /* not FIST_FILTER_NAME || FIST_FILTER_SCA */
	err = vfs_readdir(lower_file, filldir, dirent);
#endif /* not FIST_FILTER_NAME || FIST_FILTER_SCA */

	file->f_pos = lower_file->f_pos;
	if (err >= 0)
		fist_copy_attr_atime(inode, lower_file->f_dentry->d_inode);

	fist_checkinode(inode, "post monitorfs_readdir");
	print_exit_status(err);
	return err;
}


STATIC unsigned int
monitorfs_poll(file_t *file, poll_table *wait)
{
	unsigned int mask = DEFAULT_POLLMASK;
	file_t *lower_file = NULL;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	if (!lower_file->f_op || !lower_file->f_op->poll)
		goto out;

	mask = lower_file->f_op->poll(lower_file, wait);

out:
	print_exit_status(mask);
	return mask;
}


STATIC int
monitorfs_ioctl(inode_t *inode, file_t *file, unsigned int cmd, unsigned long arg)
{
	int err = 0;		/* don't fail by default */
	file_t *lower_file = NULL;
	vfs_t *this_vfs;
	vnode_t *this_vnode;
	int val;
#ifdef FIST_COUNT_WRITES
	extern unsigned long count_writes, count_writes_middle;
#endif /* FIST_COUNT_WRITES */

	print_entry_location();

	this_vfs = inode->i_sb;
	this_vnode = inode;

	/* check if asked for local commands */
	switch (cmd) {
	case FIST_IOCTL_GET_DEBUG_VALUE:
		val = fist_get_debug_value();
		printk("IOCTL GET: send arg %d\n", val);
		err = put_user(val, (int *) arg);
#ifdef FIST_COUNT_WRITES
		printk("COUNT_WRITES:%lu:%lu\n", count_writes, count_writes_middle);
#endif /* FIST_COUNT_WRITES */
		break;

	case FIST_IOCTL_SET_DEBUG_VALUE:
		err = get_user(val, (int *) arg);
		if (err)
			break;
		fist_dprint(6, "IOCTL SET: got arg %d\n", val);
		if (val < 0 || val > 20) {
			err = -EINVAL;
			break;
		}
		fist_set_debug_value(val);
		break;

		/* add non-debugging fist ioctl's here */
		

                        default:
		BUG_ON(!FILE_TO_PRIVATE(file));
		lower_file = FILE_TO_LOWER(file);
		/* pass operation to lower filesystem, and return status */
		if (lower_file && lower_file->f_op && lower_file->f_op->ioctl)
			err = lower_file->f_op->ioctl(INODE_TO_LOWER(inode), lower_file, cmd, arg);
		else
			err	= -ENOTTY;	/* this is an unknown ioctl */
	} /* end of outer switch statement */

	print_exit_status(err);
	return err;
}


/* FIST-LITE special version of mmap */
STATIC int
monitorfs_mmap(file_t *file, vm_area_t *vma)
{
	int err = 0;
	file_t *lower_file = NULL;
	inode_t *inode;
	inode_t *lower_inode;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);

	BUG_ON(!lower_file);
	if (!lower_file->f_op || !lower_file->f_op->mmap) {
		err = -ENODEV;
		goto out;
	}
	BUG_ON(!lower_file->f_op);
	BUG_ON(!lower_file->f_op->mmap);

	vma->vm_file = lower_file;
	err = lower_file->f_op->mmap(lower_file, vma);
	get_file(lower_file); /* make sure it doesn't get freed on us */
	fput(file);			/* no need to keep extra ref on ours */

out:
	print_exit_status(err);
	return err;
}


STATIC int
monitorfs_open(inode_t *inode, file_t *file)
{
	int err = 0;
	int lower_flags;  // XXX: ZH: killed "lower_mode" because it is not used...
	file_t *lower_file = NULL;
	struct dentry *lower_dentry = NULL;

	print_entry_location();

	/* don't open unhashed/deleted files */
	//if (d_unhashed(file->f_dentry)) {
	//	err = -ENOENT;
	//	goto out;
	//}

	FILE_TO_PRIVATE_SM(file) = KMALLOC(sizeof(struct monitorfs_file_info), GFP_KERNEL);
	if (!FILE_TO_PRIVATE(file)) {
		err = -ENOMEM;
		goto out;
	}
	FILE_TO_PRIVATE(file)->written = 0;
	
	lower_dentry = monitorfs_lower_dentry(file->f_dentry);

	fist_print_dentry("monitorfs_open IN lower_dentry", lower_dentry);

	dget(lower_dentry);

	lower_flags = file->f_flags;

	/*
	 * dentry_open will decrement mnt refcnt if err.
	 * otherwise fput() will do an mntput() for us upon file close.
	 */
	mntget(DENTRY_TO_LVFSMNT(file->f_dentry));
	lower_file = dentry_open(lower_dentry, 
                DENTRY_TO_LVFSMNT(file->f_dentry), 
                lower_flags
#ifdef HAVE_CRED_IN_DENTRY_OPEN
                , current_cred()
#endif
            );
	if (IS_ERR(lower_file)) {
		err = PTR_ERR(lower_file);
		//lower_file = FILE_TO_LOWER(file);
		//if (lower_file) {
		//	FILE_TO_LOWER(file) = NULL;
		//	fput(lower_file);
		//}
		goto out;
	}

	FILE_TO_LOWER(file) = lower_file;	/* link two files */

out:
	if (err < 0 && FILE_TO_PRIVATE(file)) {
		KFREE(FILE_TO_PRIVATE(file));
	}
	fist_print_dentry("monitorfs_open OUT lower_dentry", lower_dentry);
	print_exit_status(err);
	return err;
}


STATIC int
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,18)
monitorfs_flush(file_t *file)
#else
monitorfs_flush(file_t *file, fl_owner_t id)
#endif
{
	int err = 0;		/* assume ok (see open.c:close_fp) */
	file_t *lower_file = NULL;

	print_entry_location();

	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file); /* CPW: Moved after print_entry_location */
	BUG_ON(!lower_file);

	if (!lower_file->f_op || !lower_file->f_op->flush)
		goto out;

#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,18)
	err = lower_file->f_op->flush(lower_file);
#else
	err = lower_file->f_op->flush(lower_file, id);
#endif /* LINUX_VERSION_CODE < KERNEL_VERSION(2,6,18) */

out:
	print_exit_status(err);
	return err;
}


STATIC int
monitorfs_release(inode_t *inode, file_t *file)
{
	int err = 0;
	file_t *lower_file = NULL;
	struct dentry *lower_dentry;
	inode_t *lower_inode = NULL;

	print_entry_location();

	BUG_ON(!FILE_TO_PRIVATE(file));
	
	if (FILE_TO_PRIVATE(file)->written)
		monitorfs_log_operation(MONITORFS_OPS_MODIFY, file->f_dentry, NULL, file);
	
	lower_file = FILE_TO_LOWER(file);
	KFREE(FILE_TO_PRIVATE(file));

	BUG_ON(!lower_file);

	BUG_ON(!inode);
	lower_inode = INODE_TO_LOWER(inode);
	BUG_ON(!lower_inode);

	fist_print_dentry("monitorfs_release IN lower_dentry", lower_file->f_dentry);
	fist_checkinode(inode, "monitorfs_release");
	/*
	 * will decrement file refcount, and if 0, destroy the file,
	 * which will call the lower file system's file release function.
	 */
	lower_dentry = lower_file->f_dentry;
	fput(lower_file);

	/*
         * Ext2 does something strange: if you compile Ext2 with
         * EXT2_PREALLOCATE, then it will prealocate N more blocks of data to
         * the file in anticipation of the file growing in the near future.  If,
         * however, the file doesn't grow, then ext2 will deallocate these
         * pre-allocated blocks on ext2_release.  However, our stacking template
         * copies the number of blocks in a file in prepare_write and
         * commit_write, at which point the lower file reports more blocks than
         * it would have later on once the file is closed.  This was confirmed
         * by using a C program that runs fsync() on an ext2 file that's open in
         * the middle of the session.  The solution here is to copy the number
         * of blocks of the lower file to the upper file.  (It's possible to
         * copy all attributes, but might be overkill -- I'd rather copy only
         * what we need.)  WARNING: this code is definitely wrong for SCA!
         *   -Erez.
         */
	inode->i_blocks = lower_inode->i_blocks;

	fist_dprint(6, "monitorfs_release done\n");
	fist_checkinode(inode, "post monitorfs_release");

	fist_print_dentry("monitorfs_release OUT lower_dentry", lower_dentry);
	print_exit_status(err);
	return err;
}


STATIC int
monitorfs_fsync(file_t *file, struct dentry *dentry, int datasync)
{
        int err = -EINVAL;
        file_t *lower_file = NULL;
        struct dentry *lower_dentry;

	print_entry_location();

        /* when exporting upper file system through NFS with sync option,
           nfsd_sync_dir() sets struct file as NULL. Use inode's i_fop->fsync instead of file's.
           see fs/nfsd/vfs.c */
        if (file == NULL) {
                lower_dentry = monitorfs_lower_dentry(dentry);

                if (lower_dentry->d_inode->i_fop && lower_dentry->d_inode->i_fop->fsync) {
                        lock_inode(lower_dentry->d_inode);
                        err = lower_dentry->d_inode->i_fop->fsync(lower_file, lower_dentry, datasync);
                        unlock_inode(lower_dentry->d_inode);
                }

        } else {
                if (FILE_TO_PRIVATE(file) != NULL) {
                        lower_file = FILE_TO_LOWER(file);
                        BUG_ON(!lower_file);

                        lower_dentry = monitorfs_lower_dentry(dentry);

                        if (lower_file->f_op && lower_file->f_op->fsync) {
                                lock_inode(lower_dentry->d_inode);
                                err = lower_file->f_op->fsync(lower_file, lower_dentry, datasync);
                                unlock_inode(lower_dentry->d_inode);
                        }
                }
        }

	print_exit_status(err);
	return err;
}


STATIC int
monitorfs_fasync(int fd, file_t *file, int flag)
{
	int err = 0;
	file_t *lower_file = NULL;

	print_entry_location();
	BUG_ON(!FILE_TO_PRIVATE(file));
	lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	if (lower_file->f_op && lower_file->f_op->fasync)
		err = lower_file->f_op->fasync(fd, lower_file, flag);

	print_exit_status(err);
	return err;
}

static inline void __locks_delete_block(struct file_lock *waiter)
{
        list_del_init(&waiter->fl_block);
        list_del_init(&waiter->fl_link);
        waiter->fl_next = NULL;
}

static void locks_delete_block(struct file_lock *waiter)
{
        lock_kernel();
        __locks_delete_block(waiter);
        unlock_kernel();
}

STATIC inline int
monitorfs_posix_lock(file_t *file, struct file_lock *fl, int cmd)
{
    int error;
#ifdef HAVE_3_ARG_POSIX_LOCK_FILE
    struct file_lock conflock;
    for(;;) {
        error = posix_lock_file(file, fl, &conflock);
#else
    for(;;) {
        error = posix_lock_file(file, fl);
#endif /* HAVE_3_ARG_POSIX_LOCK_FILE */
        if ((error != -EAGAIN) || (cmd == F_SETLK))
            break;

        error = wait_event_interruptible(fl->fl_wait, !fl->fl_next);
        if(!error)
            continue;

        locks_delete_block(fl);
        break;
    }

    return error;
}

STATIC int
monitorfs_setlk(file_t *file, int cmd, struct file_lock *fl)
{
    int error;
    inode_t *inode, *lower_inode;
    file_t *lower_file = NULL;

    print_entry_location();

    error = -EINVAL;
    BUG_ON(!FILE_TO_PRIVATE(file));
    lower_file = FILE_TO_LOWER(file);
    BUG_ON(!lower_file);

    inode = file->f_dentry->d_inode;
    lower_inode = lower_file->f_dentry->d_inode;

    /* Don't allow mandatory locks on files that may be memory mapped
     * and shared.
     */
    if (IS_MANDLOCK(lower_inode) &&
       (lower_inode->i_mode & (S_ISGID | S_IXGRP)) == S_ISGID &&
       mapping_writably_mapped(lower_file->f_mapping)) {
                error = -EAGAIN;
                goto out;
    }

    if (cmd == F_SETLKW) {
        fl->fl_flags |= FL_SLEEP;
    }

    error = -EBADF;
    switch (fl->fl_type) {
        case F_RDLCK:
            if (!(lower_file->f_mode & FMODE_READ))
                goto out;
            break;
        case F_WRLCK:
            if (!(lower_file->f_mode & FMODE_WRITE))
                goto out;
            break;
        case F_UNLCK:
            break;
        default:
            error = -EINVAL;
            goto out;
    }

    fl->fl_file = lower_file;
    if (lower_file->f_op && lower_file->f_op->lock != NULL) {
        error = lower_file->f_op->lock(lower_file, cmd, fl);
        if (error)
            goto out;
        goto upper_lock;
    }

    error = monitorfs_posix_lock(lower_file, fl, cmd);
    if (error)
        goto out;


upper_lock:
    fl->fl_file = file;
    error = monitorfs_posix_lock(file, fl, cmd);
    if (error) {
        fl->fl_type = F_UNLCK;
        fl->fl_file = lower_file;
        monitorfs_posix_lock(lower_file, fl, cmd);
    }

out:
    print_exit_status(error);
    return error;
}

STATIC int
monitorfs_getlk(file_t *file, struct file_lock *fl)
{
    int error=0;
    struct file_lock *tempfl=NULL;
#ifdef HAVE_3_ARG_INT_POSIX_TEST_LOCK
    struct file_lock cfl;
#endif /* HAVE_3_ARG_INT_POSIX_TEST_LOCK */

    print_entry_location();

    if (file->f_op && file->f_op->lock) {
        error = file->f_op->lock(file, F_GETLK, fl);
        if (error < 0)
            goto out;
#if LINUX_VERSION_CODE < KERNEL_VERSION(2,6,11)
        else if (error == LOCK_USE_CLNT)
            /* Bypass for NFS with no locking - 2.0.36 compat */
            tempfl = posix_test_lock(file, fl);
#endif /* LINUX_VERSION_CODE < KERNEL_VERSION(2,6,11) */
    } else {
#if defined(HAVE_3_ARG_INT_POSIX_TEST_LOCK)
        tempfl = (posix_test_lock(file, fl, &cfl) ? &cfl : NULL);
#else
        posix_test_lock(file, fl);
	goto out;
#endif /* HAVE_3_ARG_INT_POSIX_TEST_LOCK */
    }

    if (!tempfl)
        fl->fl_type = F_UNLCK;
    else
        memcpy(fl, tempfl, sizeof(struct file_lock));

out:
    print_exit_status(error);
    return error;
}

STATIC int
monitorfs_lock(file_t *file, int cmd, struct file_lock *fl)
{
        int err = 0;
        file_t *lower_file = NULL;
        struct file_lock *tmpfl = NULL;

        print_entry_location();

        BUG_ON(!FILE_TO_PRIVATE(file));
        lower_file = FILE_TO_LOWER(file);
        BUG_ON(!lower_file);

        err = -EINVAL;
        if (!fl)
                goto out;

        fl->fl_file = lower_file;
        switch(cmd) {
                case F_GETLK:
#ifdef F_GETLK64
		case F_GETLK64:
#endif /* F_GETLK64 */
                        err = monitorfs_getlk(lower_file, fl);
                        break;

                case F_SETLK:
                case F_SETLKW:
#ifdef F_SETLK64
                case F_SETLK64:
#endif /* F_SETLK64 */
#ifdef F_SETLKW64
                case F_SETLKW64:
#endif /* F_SETLKW64 */
                        fl->fl_file = file;
                        err = monitorfs_setlk(file, cmd, fl);
                        break;

                default:
                        err = -EINVAL;
        }
        fl->fl_file = file;

out:
        print_exit_status(err);
        return err;
}

#if defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0)
STATIC
ssize_t monitorfs_sendfile(file_t *file, loff_t *ppos,
                size_t count, read_actor_t actor, void *target)
{
	file_t *lower_file = NULL;
	int err = -EINVAL;

	if (FILE_TO_PRIVATE(file) != NULL)
		lower_file = FILE_TO_LOWER(file);
	BUG_ON(!lower_file);

	if (lower_file->f_op && lower_file->f_op->sendfile)
		err = lower_file->f_op->sendfile(lower_file, ppos, count,
						actor, target);

	return err;
}
#endif /* defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0) */

struct file_operations monitorfs_dir_fops =
{
	llseek:   monitorfs_llseek,
	read:     monitorfs_read,
	write:    monitorfs_write,
	readdir:  monitorfs_readdir,
	poll:     monitorfs_poll,
	ioctl:    monitorfs_ioctl,
	mmap:     monitorfs_mmap,
	open:     monitorfs_open,
	flush:    monitorfs_flush,
	release:  monitorfs_release,
	fsync:    monitorfs_fsync,
	fasync:   monitorfs_fasync,
	lock:     monitorfs_lock,
#if defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0)
	sendfile: monitorfs_sendfile,
#endif /* defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0) */
	/* not needed: readv */
	/* not needed: writev */
	/* not implemented: sendpage */
	/* not implemented: get_unmapped_area */
};

struct file_operations monitorfs_main_fops =
{
	llseek:   monitorfs_llseek,
	read:     monitorfs_read,
	write:    monitorfs_write,
	readdir:  monitorfs_readdir,
	poll:     monitorfs_poll,
	ioctl:    monitorfs_ioctl,
	mmap:     monitorfs_mmap,
	open:     monitorfs_open,
	flush:    monitorfs_flush,
	release:  monitorfs_release,
	fsync:    monitorfs_fsync,
	fasync:   monitorfs_fasync,
	lock:     monitorfs_lock,
#if defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0)
	sendfile: monitorfs_sendfile,
#endif /* defined(FIST_FILTER_DATA) && LINUX_VERSION_CODE > KERNEL_VERSION(2,6,0) */
	/* not needed: readv */
	/* not needed: writev */
	/* not implemented: sendpage */
	/* not implemented: get_unmapped_area */
};

/*
 * Local variables:
 * c-basic-offset: 4
 * End:
 */