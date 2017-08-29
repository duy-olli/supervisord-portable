#
# Makefile for the Linux 2.6 base0fs
# $Id: Makefile,v 1.16 2006/09/26 01:16:46 jsipek Exp $
#

# this is where your kernel sources are
LINUXSRC = /lib/modules/$(shell uname -r)/build
# this should point to where your kernel headers are
TOPINC = -I${LINUXSRC}/include

# Fedora Core has the annoying habit of changing the kernel prototypes on us.
#FEDORAVER=$(shell rpm -q fedora-release | cut -d- -f3)
#KERNELEXTRA=x$(shell uname -r | cut -d- -f 2 -s)
#ifeq ($(FEDORAVER),2)
#ifneq ($(KERNELEXTRA),x)
#EXTRA_CFLAGS += -DFEDORACORE2
#endif
#endif

# allow custmom override of TOPINC and LINUXSRC
#-include fistdev.mk

CC	= gcc
EXTRA_CFLAGS += -DFISTGEN -I. ${TOPINC} ${EXTRACFLAGS} -O2 -Wall -Wno-unused -fno-strict-aliasing -Werror
UCFLAGS = -DFISTGEN -I. ${TOPINC} -g -O2 -Wall -Wno-unused # -Werror

obj-m := monitorfs.o
ADD_M_SRC =  
monitorfs-objs :=    fist_monitorfs.o \
	dentry.o file.o inode.o main.o super.o print.o netlink.o \
	${ADD_M_SRC:.c=.o}

all:	
	make -C ${LINUXSRC} SUBDIRS=$(PWD) modules

clean:
	rm -f ${obj-m:.o=.ko} ${monitorfs-objs} *.o *.mod.* *.d .*.o.cmd .*.flags \#* *~
	rm -f ${BINS} TAGS
# dependencies
${monitorfs-objs}: monitorfs.h fist.h fist_monitorfs.h lock.h 

# additional makefile rules, if any


