#!/opt/python/bin/python
import os, time, sys

fd = None
line = 0
currname = None
while True:
	minute = time.localtime()[4]
	if (not fd or currname != minute) and os.path.exists("/dev/shm/monitorfs/%02d" % minute):
		if fd: 
			# catch last lines which might be missed
			lines = fd.readlines()
			if len(lines):
				for i in lines:
                        		line += 1
			fd.close()
		fd = open("/dev/shm/monitorfs/%02d" % minute, "r")
		currname = minute
	
	if fd:	
		lines = fd.readlines()
		if len(lines):
			for i in lines:
				line += 1
		else: time.sleep(.5)
	else: time.sleep(1)
