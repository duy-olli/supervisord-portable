#!/opt/python/bin/python
import dns.message
import dns.rrset
import dns.query
import socket, daemon, sys, re, os

dns_real = '203.190.240.131'
fake_domains = {}
fake_list = [] # to keep the list in order
def requestHandler(address, message):
    resp = None
    try:
        message_id = ord(message[0]) * 256 + ord(message[1])
        print 'msg id = ' + str(message_id)
        if message_id in serving_ids:
            # the request is already taken, drop this message
            print 'I am already serving this request.'
            return
        serving_ids.append(message_id)
        try:
            msg = dns.message.from_wire(message)
            try:
                op = msg.opcode()
                if op == 0:
                    # standard and inverse query
                    qs = msg.question
                    if len(qs) > 0:
                        q = qs[0]
                        print 'request is ' + str(q)
                        if q.rdtype == dns.rdatatype.A:
                            resp = std_qry(msg)
                        else:
                            # forward to real dns
                            print 'use real dns', dns_real
                            resp = dns.query.udp(msg, dns_real)
                else:
                    # forward to real dns
                    print 'use real dns', dns_real
                    resp = dns.query.udp(msg, dns_real)

            except Exception, e:
                print 'got ' + repr(e)
                resp = self.make_response(qry=msg, RCODE=2)   # RCODE =  2    Server Error
                print 'resp = ' + repr(resp.to_wire())

        except Exception, e:
            print 'got ' + repr(e)
            resp = self.make_response(id=message_id, RCODE=1)   # RCODE =  1    Format Error
            print 'resp = ' + repr(resp.to_wire())

    except Exception, e:
        # message was crap, not even the ID
        print 'got ' + repr(e)

    if resp:
        s.sendto(resp.to_wire(), address)


def std_qry(msg):
    qs = msg.question
    print str(len(qs)) + ' questions.'

    answers = []
    nxdomain = False
    for q in qs:
        qname = q.name.to_text()[:-1].lower()
        print 'q name = ' + qname

        if qname in fake_list:
            resp = make_response(qry=msg)
            rrset = dns.rrset.from_text(q.name, 1000, dns.rdataclass.IN, dns.rdatatype.A, fake_domains[qname])
            resp.answer.append(rrset)
            return resp
        else:
            # iterate using regex
            for domain in fake_list:
                  pat = re.compile(domain)
                  if pat.match(qname):
                        resp = make_response(qry=msg)
                        rrset = dns.rrset.from_text(q.name, 1000, dns.rdataclass.IN, dns.rdatatype.A, fake_domains[domain])
                        resp.answer.append(rrset)
                        return resp

            print 'use real dns', dns_real
            return dns.query.udp(msg, dns_real)
            #return make_response(qry=msg, RCODE=3)   # RCODE =  3    Name Error


def make_response(qry=None, id=None, RCODE=0):
    if qry is None and id is None:
        raise Exception, 'bad use of make_response'
    if qry is None:
        resp = dns.message.Message(id)
        # QR = 1
        resp.flags |= dns.flags.QR
        if RCODE != 1:
            raise Exception, 'bad use of make_response'
    else:
        resp = dns.message.make_response(qry)
    resp.flags |= dns.flags.AA
    resp.flags |= dns.flags.RA
    resp.set_rcode(RCODE)
    return resp

prog = os.path.splitext(sys.argv[0])[0]
daemon.daemonize(prog + '.pid')
if len(sys.argv) > 1: dns_real = sys.argv[1]
for line in open(prog + '.conf', 'r'):
	if line.strip().startswith("#"): continue
	if line.strip() == '': continue
	domain, ip = line.split()
	if domain.strip() == 'realdns':
		dns_real = ip.strip()
		continue	
	fake_domains[domain.strip()] = ip.strip()
	fake_list.append(domain.strip())
	
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 53))
print 'binded to UDP port 53.'
serving_ids = []

while True:
    print 'waiting requests.'
    message, address = s.recvfrom(1024)
    print 'serving a request.'
    requestHandler(address, message)
