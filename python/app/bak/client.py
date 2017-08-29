import socket, sys

s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
#s.connect("/tmp/echo.socket")
s.setblocking(0)
s.sendto(sys.argv[1],"echo.sock")
#data = s.recv(1024)
s.close()
#print 'Received', repr(data)

