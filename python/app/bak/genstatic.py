#!/opt/python/bin/python
import my_xml, multiprocessing, os, httplib
from trigger import Trigger

root_dir = "/data/detikcom/baru"
tpl_dir = root_dir + "/xml/news/tpl"
map_kanal_website_news = root_dir + "/xml/news/other/otomatisasi/masterkanalintegrasinews.xml"
map_kanal_website_foto = root_dir + "/xml/news/other/otomatisasi/masterkanalintegrasifoto.xml"
watched_file = ['headline.xml', 'nonheadline.xml', 'topn.xml']

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
                print "Error reading kanal mapping to website"
                return False

        return kanal_mapping   

class generate_static(Trigger):
	def __init__(self, params):
		self.manager = multiprocessing.Manager()
		self.kanals = self.manager.dict()
		self.masterkanal = read_kanal_config()
		self.server_create = params['server']
			
	def on_modified(self, pathname):
		kanal = os.path.relpath(pathname, tpl_dir).split('/')[0]
		file_val = watched_file.index(os.path.basename(pathname)[len(kanal)+1:])**2
		if not self.kanals.has_key(kanal): self.kanals[kanal] = 0
		self.kanals[kanal] |= file_val
		if self.kanals[kanal] == 7:
			print kanal, ": submit create statik to website ", self.masterkanal[kanal]
			# trigger create statik
			#http = httplib.HTTPConnection(server_create)
			#headers = { 'Host': self.masterkanal[kanal] }
			#http.request("GET", "/create", headers=headers)
			#http.getresponse()
			#self.kanals[kanal] = 0	
	def on_deleted(self, pathname):
		pass
	def on_renamed(self, pathname, new_pathname):
		pass
