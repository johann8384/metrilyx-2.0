#!/usr/bin/env python

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(
						os.path.abspath(__file__))))
import ujson as json
import time
import logging

import multiprocessing
from optparse import OptionParser

from twisted.internet import reactor
from twisted.python import log

from autobahn.twisted.websocket import WebSocketServerFactory, listenWS

from metrilyx.metrilyxconfig import config
from metrilyx.dataserver.protocols import GraphServerProtocol, \
										EventGraphServerProtocol, \
										acceptedCompression
from metrilyx.dataserver.dataproviders import getEventDataProvider, \
										getPerfDataProvider

LOG_FORMAT = "%(asctime)s [%(levelname)s %(name)s %(lineno)d] %(message)s"


class MetrilyxWebSocketServerFactory(WebSocketServerFactory):

	clients = []

	def addClient(self, client):
		self.clients.append(client)
		logger.warning("WebSocket clients: %d" %(len(self.clients)))

	def removeClient(self, client):
		self.clients.remove(client)
		logger.warning("WebSocket clients: %d" %(len(self.clients)))


def spawnWebsocketServer(uri, logLevel, protocol, externalPort=None):
	#if logLevel == "DEBUG":
	#	isDebug = True
	#else:
	#	isDebug = False

	factory = MetrilyxWebSocketServerFactory(uri, debug=False, externalPort=externalPort)
	factory.protocol = protocol
	factory.setProtocolOptions(perMessageCompressionAccept=acceptedCompression)

	listenWS(factory)
	reactor.run()

def spawnServers(protocol):
	global logger, opts
	procs = []
	for i in range(opts.serverCount):
		uri = "%s:%d" %(opts.uri, opts.startPort+i)
		proc = multiprocessing.Process(
						target=spawnWebsocketServer,
						args=(uri, opts.logLevel, protocol, opts.externalPort))
		proc.start()
		logger.warning("Started server - %s" %(uri))
		procs.append(proc)
	return procs


def getLogger(level):
	try:
		logging.basicConfig(level=eval("logging.%s" %(opts.logLevel)),
			format=LOG_FORMAT)
		return logging.getLogger(__name__)
	except Exception,e:
		print "[ERROR] %s" %(str(e))
		parser.print_help()
		sys.exit(2)

if __name__ == '__main__':

	parser = OptionParser()
	parser.add_option("-l", "--log-level", dest="logLevel", default="INFO",
		help="Logging level.")
	parser.add_option("-u", "--uri", dest="uri", default="ws://localhost",
		help="ws://<hostname>")
	parser.add_option("-s", "--start-port", dest="startPort", type="int", default=9000,
		help="Starting point of the port range to listen on. This is only applicable when multiple servers are launched.")
	parser.add_option("-c","--server-count", dest="serverCount", type="int", default=1,
		help="Number of servers to spawn. If 0 is specified, the count will be based off of the number cpus/cores")
	parser.add_option("-e", "--external-port", dest="externalPort", type="int", default=None,
		help="External port to use.  This is needed when running the servers behind a reverse proxy (i.e nginx)")

	(opts, args) = parser.parse_args()

	if opts.logLevel == "DEBUG":
		# twisted logger (may not be needed)
		log.startLogging(sys.stdout)
		observer = log.PythonLoggingObserver()
		observer.start()
	logger = getLogger(opts.logLevel)

	if not opts.uri:
		print " --uri required!"
		parser.print_help()
		sys.exit(1)

	if opts.serverCount == 0:
		logger.warning("Using auto-spawn count.")
		opts.serverCount = multiprocessing.cpu_count()-1
		if opts.serverCount == 0:
			opts.serverCount = 1

	try:
		perfDP = getPerfDataProvider()
		logger.warning('Performance dataprovider [loaded]')
		if config['annotations']['enabled']:
			eventDP = getEventDataProvider()
			logger.warning('Event dataprovider [loaded]')

			class EventGraphProtocol(EventGraphServerProtocol):
				dataprovider = perfDP
				eventDataprovider = eventDP

			proto = EventGraphProtocol
		else:
			class GraphProtocol(GraphServerProtocol):
				dataprovider = perfDP

			proto = GraphProtocol
	except Exception,e:
		logger.error("Could not set dataprovider and/or protocol: %s" %(str(e)))
		sys.exit(2)

	logger.warning("Protocol: %s" %(str(proto)))

	logger.warning("Spawning %d server/s..." %(opts.serverCount))
	server_procs = spawnServers(proto)

	try:
		for p in server_procs:
			p.join()
	except KeyboardInterrupt:
		logger.warning("Stopping...")
