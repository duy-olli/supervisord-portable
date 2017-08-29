# Echo server program
import socket
import sys,time

s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind("../monitorfs.sock")
while 1:
    data = s.recv(1024)
    if not data: continue
    print "-" + data
    time.sleep(.001)
    #s.send(data)

