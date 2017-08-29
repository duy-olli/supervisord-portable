#!/opt/python/bin/python
import socket, struct, sys, time

sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 20)
sock.bind((0,1))
#sock.setblocking(0)
sock.settimeout(.5)
num = 1

data="helo"
hdr = struct.pack("IHHII", len(data) + 4*4, 100, 0, 0, 0)
sock.send(hdr + data)

fd=open("log.txt","w")
while True:
	try:
		data = sock.recv(8192)
	except Exception:
		continue
	lastidx = data[16:].find('\x00')
	msglen, msg_type, flags, seq, pid = struct.unpack("IHHII", data[:16])

	if lastidx < 0:
		print "Line %s: length unknown" % num
	data = data[16:16+lastidx]
	try:
		op, val = data.split("|",1)
	except Exception:
		print "Line %s: is wrong" % num
	fd.write("%s:%s|%s\n" % (num,seq, data))
	
	ack = struct.pack("IHHIII", 4 + 4*4, 101, 0, 0, 0, seq)
	sock.send(ack)
	#if op == sys.argv[1][0]:
	#print num, path
	#print op, path
	num += 1 
sock.close()
