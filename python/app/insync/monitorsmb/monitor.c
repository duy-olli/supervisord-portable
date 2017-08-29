/*
 * MONITOR - External VFS Bridge
 * This transparent VFS module sends VFS operations over a Unix domain
 * socket for external handling.
 *
 * Copyright (C) 2004 Steven R. Farley.  All rights reserved.
 */

#include "includes.h"

#undef DBGC_CLASS
#define DBGC_CLASS DBGC_VFS

#define MONITOR_MSG_OUT_SIZE 4000
#define MONITOR_MSG_IN_SIZE 3
#define MONITOR_FAIL_ERROR -1
#define MONITOR_FAIL_AUTHORIZATION -2
#define MONITOR_SUCCESS_TRANSPARENT 0
#define MONITOR_SOCKET_FILE "/tmp/monitor-socket"

 /* MONITOR communication functions */

static void monitor_write_socket(const char *str, int close_socket)
{
	static int connected = 0;
	static int sd = -1;
	static int count = 0;
	char out[MONITOR_MSG_OUT_SIZE];
	char in[MONITOR_MSG_IN_SIZE];
	int ret;
	struct sockaddr_un sa;
	struct stat buf;
	int result = MONITOR_FAIL_ERROR;
	struct timeval timeout;

	if (!connected) {
		if (stat(MONITOR_SOCKET_FILE, &buf))
			return;
		sd = socket(AF_UNIX, SOCK_STREAM, 0);
		if (sd != -1) {
			timeout.tv_sec = 3;
			timeout.tv_usec = 0;
			setsockopt(sd, SOL_SOCKET, SO_RCVTIMEO, (struct timeval *)&timeout, sizeof(timeout));
			setsockopt(sd, SOL_SOCKET, SO_SNDTIMEO, (struct timeval *)&timeout, sizeof(timeout));
			strncpy(sa.sun_path, MONITOR_SOCKET_FILE, strlen(MONITOR_SOCKET_FILE) + 1);
			sa.sun_family = AF_UNIX;
			ret = connect(sd, (struct sockaddr *) &sa, sizeof(sa));
			if (ret != -1) {
				//syslog(LOG_NOTICE, "monitor_write_socket connect succeeded");
				connected = 1;
			}
			else {
				//syslog(LOG_NOTICE, "monitor_write_socket connect failed");
				close(sd);
			}
		}
		else {
			//syslog(LOG_NOTICE, "monitor_write_socket open failed");
		}
	}

	if (close_socket) {
		//syslog(LOG_NOTICE, "monitor_write_socket closing normally");
		close(sd);
		connected = 0;
	}	
	
	if (connected) {
		memset(out, 0, MONITOR_MSG_OUT_SIZE);
		strncpy(out, str, strlen(str) + 1);
		ret = write(sd, out, strlen(str) + 1);
		if (ret != -1) {
			memset(in, 0, MONITOR_MSG_IN_SIZE);
			ret = read(sd, in, MONITOR_MSG_IN_SIZE);
			if (ret != -1) {
				result = atoi(in);
				//syslog(LOG_NOTICE, "monitor_write_socket (%d) received '%s'", count++, in);
			} else {
				//syslog(LOG_NOTICE, "monitor_write_socket read failed");
				close(sd);
				connected = 0;
			}
		} else {
			//syslog(LOG_NOTICE, "monitor_write_socket write failed");
			close(sd);
			connected = 0;
		}
	}
}

static void monitor_execute(const char *buf, int count)
{
	int close_sock = 0;

	if (strncmp(buf, "disconnect", 10) == 0) {
		close_sock = 1;
	}

	if (count > 0) {
		monitor_write_socket(buf, close_sock);
	}
}

static const char* pathname(const char *path) {
	if (strncmp(path, "./", 2) == 0) 
		return path + 2;
	return path;
}

/* VFS handler functions */

static int monitor_connect(vfs_handle_struct *handle, const char *svc, const char *user)
{
	return SMB_VFS_NEXT_CONNECT(handle, svc, user);
}

static void monitor_disconnect(vfs_handle_struct *handle)
{
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "disconnect");
	monitor_execute(buf, count);
	SMB_VFS_NEXT_DISCONNECT(handle);
	
	return;
}

static int monitor_mkdir(vfs_handle_struct *handle, const char *path, mode_t mode)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "c|/%s", pathname(path));
	result = SMB_VFS_NEXT_MKDIR(handle, path, mode);
	if (result >= 0)
		monitor_execute(buf, count);
	return result;
}

static int monitor_rmdir(vfs_handle_struct *handle, const char *path)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "d|/%s", pathname(path));
	result = SMB_VFS_NEXT_RMDIR(handle, path);
	if (result >= 0)
		monitor_execute(buf, count);
	return result;
}

static int monitor_open(vfs_handle_struct *handle, const char *fname, files_struct *fsp, int flags, mode_t mode)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "c|/%s", pathname(fname));
	result = SMB_VFS_NEXT_OPEN(handle, fname, fsp, flags, mode);
	if (result >= 0 && (flags & O_CREAT))
		monitor_execute(buf, count);
		
	return result;	
}

static int monitor_close(vfs_handle_struct *handle, files_struct *fsp, int fd)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	result = SMB_VFS_NEXT_CLOSE(handle, fsp, fd);
	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "m|/%s", pathname(fsp->fsp_name));
	if (result >= 0 && fsp->modified)
		monitor_execute(buf, count);
		
	return result;
}

static int monitor_rename(vfs_handle_struct *handle, const char *old, const char *new)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "r|/%s|/%s", pathname(new), pathname(old));
	result = SMB_VFS_NEXT_RENAME(handle, old, new);
	if (result >= 0)
		monitor_execute(buf, count);

	return result;
}

static int monitor_unlink(vfs_handle_struct *handle, const char *path)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "d|/%s", pathname(path));
	result = SMB_VFS_NEXT_UNLINK(handle, path);
	if (result >= 0)
		monitor_execute(buf, count);
		
	return result;
}

static int monitor_mknod(vfs_handle_struct *handle, const char *path, mode_t mode, SMB_DEV_T dev)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "c|/%s", pathname(path));
	result = SMB_VFS_NEXT_MKNOD(handle, path, mode, dev);
	if (result >= 0)
		monitor_execute(buf, count);
	return result;
}

static int monitor_link(vfs_handle_struct *handle,  const char *old, const char *new)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "c|/%s", pathname(new));
	result = SMB_VFS_NEXT_LINK(handle, old, new);
	if (result >= 0)
		monitor_execute(buf, count);
	return result;
}

static int monitor_symlink(vfs_handle_struct *handle,  const char *old, const char *new)
{
	int result = -1;
	int count;
	char buf[MONITOR_MSG_OUT_SIZE];

	count = snprintf(buf, MONITOR_MSG_OUT_SIZE, "c|/%s", pathname(new));
	result = SMB_VFS_NEXT_SYMLINK(handle, old, new);
	if (result >= 0)
		monitor_execute(buf, count);
	return result;
}
/* VFS operations */

static vfs_op_tuple monitor_op_tuples[] = {

	/* Disk operations */

	{SMB_VFS_OP(monitor_connect), 		SMB_VFS_OP_CONNECT, 	SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_disconnect), 	SMB_VFS_OP_DISCONNECT, 	SMB_VFS_LAYER_TRANSPARENT},

	/* Directory operations */

	{SMB_VFS_OP(monitor_mkdir), 		SMB_VFS_OP_MKDIR, 		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_rmdir), 		SMB_VFS_OP_RMDIR, 		SMB_VFS_LAYER_TRANSPARENT},

	/* File operations */
	{SMB_VFS_OP(monitor_open),	 		SMB_VFS_OP_OPEN, 		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_close), 		SMB_VFS_OP_CLOSE, 		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_rename), 		SMB_VFS_OP_RENAME, 		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_unlink), 		SMB_VFS_OP_UNLINK, 		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_mknod),			SMB_VFS_OP_MKNOD,		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_link),			SMB_VFS_OP_LINK,		SMB_VFS_LAYER_TRANSPARENT},
	{SMB_VFS_OP(monitor_symlink),		SMB_VFS_OP_SYMLINK,		SMB_VFS_LAYER_TRANSPARENT},

	/* Finish VFS operations definition */

	{SMB_VFS_OP(NULL), 					SMB_VFS_OP_NOOP, 		SMB_VFS_LAYER_NOOP}
};

/* VFS module registration */

NTSTATUS init_module(void)
{
	return smb_register_vfs(SMB_VFS_INTERFACE_VERSION, "monitor", monitor_op_tuples);
}
