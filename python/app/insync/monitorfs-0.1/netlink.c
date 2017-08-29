/**
 * monitorfs: Linux filesystem monitoring layer
 *
 * Copyright (C) 2004-2006 International Business Machines Corp.
 * Copyright (C) 2011 Dogmaphobia
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License version
 * 2 as published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 * 02111-1307, USA.
 */
#ifdef FISTGEN
#include "fist_monitorfs.h"
#endif /* FISTGEN */
#include "fist.h"
#include <net/sock.h>
#include "monitorfs.h"

static struct sock *monitorfs_nl_sock;
static u32 seqnum;

static void monitorfs_process_nl_helo(struct sk_buff *skb)
{
	printk("Got pid = %d\n", NETLINK_CREDS(skb)->pid);
	monitorfs_modified_op.pid = NETLINK_CREDS(skb)->pid;
}

static int monitorfs_process_nl_ack(struct sk_buff *skb)
{
	struct nlmsghdr *nlh = (struct nlmsghdr *)skb->data;
	u32 seqnum = *((u32 *) NLMSG_DATA(nlh));
	int rc = -1;
	
	mutex_lock(&monitorfs_modified_op.send_ack_mux);	
	if (monitorfs_modified_op.seqnum == seqnum && 
			monitorfs_modified_op.status == MONITORFS_STATUS_WAITING) {
		monitorfs_modified_op.status = MONITORFS_STATUS_ACK;
		rc = 0;
	} 
	mutex_unlock(&monitorfs_modified_op.send_ack_mux);	
	wake_up(&monitorfs_modified_op.waitq);	
	return rc;
}
/**
 * monitorfs_receive_nl_message
 *
 * Callback function called by netlink system when a message arrives.
 * If the message looks to be valid, then an attempt is made to assign
 * it to its desired netlink context element and wake up the process
 * that is waiting for a response.
 */
static void monitorfs_receive_nl_message(struct sock *sk, int len)
{
	struct sk_buff *skb;
	struct nlmsghdr *nlh;
	int rc = 0;

receive:
	skb = skb_recv_datagram(sk, 0, 0, &rc);
	if (rc == -EINTR)
		goto receive;
	else if (rc < 0) {
		printk("Error occurred while "
				"receiving monitorfs netlink message; "
				"rc = [%d]\n", rc);
		return;
	}
	nlh = (struct nlmsghdr *)skb->data;
	if (!NLMSG_OK(nlh, skb->len)) {
		printk("Received corrupt netlink message\n");
		goto free;
	}
	
	switch (nlh->nlmsg_type) {
		case MONITORFS_MSG_HELO:
			monitorfs_process_nl_helo(skb);
			break;
		case MONITORFS_MSG_ACK:
			if (monitorfs_process_nl_ack(skb)) {
				printk("Failed to fulfill QUIT request\n");
			}
			break;
		default:
			printk("Dropping netlink message of unrecognized type [%d]\n",
					nlh->nlmsg_type);
			break;
	}	
free:
	kfree_skb(skb);
}


int monitorfs_send_and_ack(char *data, int data_len, pid_t pid)
{
	struct sk_buff *skb;
	struct nlmsghdr *nlh;
	char *nldata;
	int rc;
	signed long timeout;

	skb = alloc_skb(NLMSG_SPACE(data_len), GFP_KERNEL);
	if (!skb) {
		rc = -ENOMEM;
		printk("Failed to allocate socket buffer\n");
		goto out;
	}

	nlh = NLMSG_PUT(skb, 0, 0, 0, data_len);
	nlh->nlmsg_flags = 0;
	nlh->nlmsg_seq = ++monitorfs_modified_op.seqnum;
	if (data_len) {
		nldata = NLMSG_DATA(nlh);
		memcpy(nldata, data, data_len);
	}

	mutex_lock(&monitorfs_modified_op.send_ack_mux);
	rc = netlink_unicast(monitorfs_nl_sock, skb, pid, 0);
	if (rc < 0) {
		printk("Failed to send monitorfs netlink message; rc = [%d]\n", rc);
		monitorfs_modified_op.pid = 0;
		mutex_unlock(&monitorfs_modified_op.send_ack_mux);
		goto out;
	}
	monitorfs_modified_op.status = MONITORFS_STATUS_WAITING;
	mutex_unlock(&monitorfs_modified_op.send_ack_mux);
	
	wait_event_interruptible_timeout(monitorfs_modified_op.waitq, 
			monitorfs_modified_op.status == MONITORFS_STATUS_ACK, MONITORFS_TIMEOUT);

	if (monitorfs_modified_op.status != MONITORFS_STATUS_ACK) {
		rc = -ENOMSG;
		printk("Failed to receive acknowledge netlink message\n");
	} 

	goto out;
nlmsg_failure:
	rc = -EMSGSIZE;
	kfree_skb(skb);
out:
	return rc;
}


/**
 * monitorfs_init_netlink
 *
 * Initializes the daemon id hash list, netlink context array, and
 * necessary locks.  Returns zero upon success; non-zero upon error.
 */
int monitorfs_init_netlink(void)
{
	int rc;

	monitorfs_nl_sock = netlink_kernel_create(NETLINK_MONITORFS, 0,
						 monitorfs_receive_nl_message,
						 THIS_MODULE);
	if (!monitorfs_nl_sock) {
		rc = -EIO;
		printk("Failed to create netlink socket\n");
		goto out;
	}
	monitorfs_nl_sock->sk_sndtimeo = MONITORFS_DEFAULT_SEND_TIMEOUT;
	rc = 0;
out:
	return rc;
}

/**
 * monitorfs_release_netlink
 *
 * Frees all memory used by the netlink context array and releases the
 * netlink socket.
 */
void monitorfs_release_netlink(void)
{
	if (monitorfs_nl_sock && monitorfs_nl_sock->sk_socket)
		sock_release(monitorfs_nl_sock->sk_socket);
	monitorfs_nl_sock = NULL;
}
