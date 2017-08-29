#!/opt/python/bin/python
import my_xml, multiprocessing, os, httplib, time, sys, base64
from trigger import Trigger

root_dir = "/data/detikcom/baru"
tpl_dir = root_dir + "/xml/news/tpl"
map_kanal_website_news = root_dir + "/xml/news/other/otomatisasi/masterkanalintegrasinews.xml"
map_kanal_website_foto = root_dir + "/xml/news/other/otomatisasi/masterkanalintegrasifoto.xml"
watched_file = ['headline.xml', 'nonheadline.xml']
jahex = "http://jahex.detik.com/servrutin/detikcom/index.php"
kangkung = "http://kangkung.detik.com/index.php?fuseaction=aksi.generateLayout"

def gen_detikcom():
	try:
		url = httplib.urlsplit(jahex)
		http = httplib.HTTPConnection(url.netloc, timeout=60)
		headers = { 'Host': url.netloc }
		http.request("GET", url.path + (url.query != "" and "?"+url.query or ""), headers=headers)
		resp = http.getresponse()
		sys.stdout.write("%s : Create static on %s : %s\n" % (time.ctime(), jahex, resp.status))
		sys.stdout.flush()
	
		base64string = base64.encodestring('%s:%s' % ('detik','kenthir2010'))[:-1]
		url = httplib.urlsplit(kangkung)
		http = httplib.HTTPConnection(url.netloc, timeout=60)
		headers = { 'Host' : url.netloc, 'Authorization' : 'Basic %s' % base64string }
		http.request("GET", url.path + (url.query != "" and "?"+url.query or ""), headers=headers)
		resp = http.getresponse()
		sys.stdout.write("%s : Create static on %s : %s\n" % (time.ctime(), kangkung, resp.status))
		sys.stdout.flush()
	except Exception, e:
		pass
	

def read_kanal_config():
        try:
                kanal_mapping = {}
                news = my_xml.parse_file(map_kanal_website_news).xpath("detikcom/integrasi/news/item")
                if str(news) != '':
                        for item in news:
                                kanal_mapping[item.at_idkanal] = item.value
                
                foto = my_xml.parse_file(map_kanal_website_foto).xpath("detikcom/integrasi/foto/item")
                if str(foto) != '':
                        for item in foto:
                                kanal_mapping[item.at_idkanal] = item.value
        except Exception, e:
                kanal_mapping = None
                sys.stdout.write("Error reading kanal mapping to website\n")
		sys.stdout.flush()
                return False

        return kanal_mapping   

update_interval = 30 # seconds
def kanal_creator(server, pipe):
	websites = {}
	proc = None
	while True:
		generated = False
		if pipe.poll():
			fullurl = pipe.recv()
			if fullurl == "::exit::": break
			if not websites.has_key(fullurl) and not fullurl == 'http://www.detik.com':
				websites[fullurl] = time.time()
		
		now = time.time()
		for ws in websites.keys():
			if now >=  websites[ws] + update_interval:
				try:
					url = httplib.urlsplit(ws)
					http = httplib.HTTPConnection(server, timeout=60)
					headers = { 'Host': url.netloc }
					http.request("GET", os.path.join(url.path=="" and "/" or url.path,"create"), headers=headers)
					resp = http.getresponse()
					sys.stdout.write("%s : Create static on %s : %s\n" % (time.ctime(), ws, resp.status))
					sys.stdout.flush()
					generated = True
				except Exception, e:
					pass
				websites.pop(ws)
		if generated and (proc is None or not proc.is_alive()):
			if not proc is None:
				proc.join()
			proc = multiprocessing.Process(target=gen_detikcom, args=())
			proc.start()
		time.sleep(1)

class generate_static(Trigger):
	def __init__(self, params):
		self.manager = multiprocessing.Manager()
		self.kanals = self.manager.dict()
		self.masterkanal = read_kanal_config()
		self.server = params['server']
		self.pipe_send, self.pipe_recv = multiprocessing.Pipe()
                proc = multiprocessing.Process(target=kanal_creator, args=(self.server, self.pipe_recv))
                proc.start()

	def on_modified(self, pathname, data):
		kanal = os.path.relpath(pathname, tpl_dir).split('/')[0]
		filename = os.path.basename(pathname)[len(kanal)+1:]
		#file_val = filename in watched_file and 2**watched_file.index(filename) or 0

		#if not file_val: return
		#if not self.kanals.has_key(kanal): self.kanals[kanal] = 0
		#if not self.kanals[kanal] and file_val != 1 : return # always start with headline

		#self.kanals[kanal] |= file_val
		#if self.kanals[kanal] == 7:
		if filename in watched_file and kanal in self.masterkanal:
			# trigger create statik
			#print "Kirim ", kanal, self.masterkanal[kanal]
			self.pipe_send.send(self.masterkanal[kanal])
			#self.kanals[kanal] = 0	

	def on_deleted(self, pathname):
		pass
	def on_renamed(self, pathname, new_pathname):
		pass
	def on_terminated(self):
		self.pipe_send.send("::exit::")
